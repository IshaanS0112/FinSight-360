"""Merton distance-to-default: the market's view of the same balance sheet.

Equity is a call option on the firm's assets with strike equal to its debt.
Given observed equity value E and equity volatility sigma_E, solve two equations
for the unobserved asset value V and asset volatility sigma_V:

    E           = V * N(d1) - F * exp(-rT) * N(d2)
    sigma_E * E = N(d1) * sigma_V * V

then DD = [ln(V/F) + (r - sigma_V^2 / 2) T] / (sigma_V * sqrt(T)), PD = N(-DD).

F is the KMV default point: short-term debt + half of long-term debt. The drift
is the risk-free rate, so this is a risk-neutral DD.

Bharath and Shumway's (2008) "naive" DD is computed alongside as a closed-form
cross-check that needs no solver. When the two disagree badly, the solved model
is the one to distrust.

Unlike Altman and Ohlson, this model does not refuse banks: it is the model the
V1 financial-sector refusal has always pointed at.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from statistics import NormalDist
from typing import Any

from scipy.optimize import root

from app.enums import ResultConfidence

_N = NormalDist()

MERTON_CITATION = (
    "Merton, R. C. (1974). On the Pricing of Corporate Debt: The Risk Structure of "
    "Interest Rates. Journal of Finance, 29(2), 449-470."
)
NAIVE_CITATION = (
    "Bharath, S. T. and Shumway, T. (2008). Forecasting Default with the Merton "
    "Distance to Default Model. Review of Financial Studies, 21(3), 1339-1369."
)


@dataclass
class MertonInputs:
    equity_value: float
    equity_volatility: float
    default_point: float
    risk_free_rate: float
    horizon_years: float
    prior_year_equity_return: float | None = None


@dataclass
class MertonResult:
    distance_to_default: float | None
    probability_of_default: float | None
    confidence: ResultConfidence
    asset_value: float | None = None
    asset_volatility: float | None = None
    naive_distance_to_default: float | None = None
    naive_probability_of_default: float | None = None
    converged: bool = False
    calculation_basis: dict[str, Any] = field(default_factory=dict)


def default_point(
    total_debt: float | None, long_term_debt: float | None
) -> tuple[float | None, str]:
    """KMV default point, or the conservative fallback with its basis named."""
    if total_debt is None:
        return None, "UNAVAILABLE"
    if long_term_debt is None or long_term_debt > total_debt:
        # No split: all debt treated as due, which overstates the default point
        # and so overstates PD. Conservative, and recorded.
        return total_debt, "TOTAL_DEBT_NO_SPLIT"
    short_term = total_debt - long_term_debt
    return short_term + 0.5 * long_term_debt, "KMV_SHORT_PLUS_HALF_LONG"


def _equity_from_assets(v: float, sigma_v: float, f: float, r: float, t: float):
    d1 = (math.log(v / f) + (r + 0.5 * sigma_v**2) * t) / (sigma_v * math.sqrt(t))
    d2 = d1 - sigma_v * math.sqrt(t)
    equity = v * _N.cdf(d1) - f * math.exp(-r * t) * _N.cdf(d2)
    return equity, d1


def solve_asset_value(inputs: MertonInputs) -> tuple[float, float, bool, str]:
    """Solve the two Merton equations for (V, sigma_V). Returns (V, sigma_V, converged, message)."""
    e, sigma_e, f = inputs.equity_value, inputs.equity_volatility, inputs.default_point
    r, t = inputs.risk_free_rate, inputs.horizon_years

    # Unknowns are scaled by E so a balance sheet in rupee millions and one in
    # dollar millions look identical to the solver.
    def residuals(x):
        v, sigma_v = x[0] * e, x[1]
        if v <= 0 or sigma_v <= 1e-6:
            return [1e3, 1e3]
        equity, d1 = _equity_from_assets(v, sigma_v, f, r, t)
        return [(equity - e) / e, (_N.cdf(d1) * sigma_v * v - sigma_e * e) / e]

    start = [(e + f) / e, sigma_e * e / (e + f)]
    solution = root(residuals, start, method="hybr")
    v, sigma_v = float(solution.x[0] * e), float(solution.x[1])
    ok = bool(solution.success) and max(abs(z) for z in residuals(solution.x)) < 1e-8
    return v, sigma_v, ok, str(solution.message)


def naive_distance_to_default(inputs: MertonInputs) -> tuple[float, float] | None:
    """Bharath-Shumway closed form. Needs the prior-year equity return as drift."""
    if inputs.prior_year_equity_return is None:
        return None
    e, f, sigma_e, t = (
        inputs.equity_value,
        inputs.default_point,
        inputs.equity_volatility,
        inputs.horizon_years,
    )
    sigma_d = 0.05 + 0.25 * sigma_e
    sigma_v = e / (e + f) * sigma_e + f / (e + f) * sigma_d
    dd = (math.log((e + f) / f) + (inputs.prior_year_equity_return - 0.5 * sigma_v**2) * t) / (
        sigma_v * math.sqrt(t)
    )
    return dd, _N.cdf(-dd)


def compute_merton(inputs: MertonInputs | None, refusal: str = "") -> MertonResult:
    """Merton DD and PD, with the naive cross-check, or a refusal with the reason."""
    if inputs is None:
        return MertonResult(
            distance_to_default=None,
            probability_of_default=None,
            confidence=ResultConfidence.UNUSABLE,
            calculation_basis={"citation": MERTON_CITATION, "refusal": refusal},
        )

    v, sigma_v, converged, message = solve_asset_value(inputs)
    t = inputs.horizon_years
    naive = naive_distance_to_default(inputs)

    basis: dict[str, Any] = {
        "citation": MERTON_CITATION,
        "naive_citation": NAIVE_CITATION,
        "equations": [
            "E = V*N(d1) - F*exp(-rT)*N(d2)",
            "sigma_E*E = N(d1)*sigma_V*V",
        ],
        "distance_to_default": "[ln(V/F) + (r - sigma_V^2/2)T] / (sigma_V*sqrt(T))",
        "drift": "risk-free rate (risk-neutral DD)",
        "inputs": {
            "equity_value": round(inputs.equity_value, 4),
            "equity_volatility": round(inputs.equity_volatility, 6),
            "default_point": round(inputs.default_point, 4),
            "risk_free_rate": inputs.risk_free_rate,
            "horizon_years": t,
            "prior_year_equity_return": inputs.prior_year_equity_return,
        },
        "solver_message": message,
        "interpretation_limit": (
            "Merton assumes asset value follows a lognormal walk and that default can "
            "only happen at the horizon. Real defaults cluster earlier and fatter-tailed, "
            "so the PD is best read as a ranking signal rather than a literal frequency."
        ),
    }
    if naive is not None:
        basis["naive_formula"] = (
            "sigma_D = 0.05 + 0.25*sigma_E; sigma_V = E/(E+F)*sigma_E + F/(E+F)*sigma_D; "
            "DD = [ln((E+F)/F) + (r_prior - sigma_V^2/2)T] / (sigma_V*sqrt(T))"
        )

    if not converged:
        basis["refusal"] = (
            "The two Merton equations did not solve to tolerance for these inputs, so no "
            "solved DD is reported. The naive closed form is still shown."
        )
        return MertonResult(
            distance_to_default=None,
            probability_of_default=None,
            confidence=ResultConfidence.PARTIAL if naive else ResultConfidence.UNUSABLE,
            naive_distance_to_default=round(naive[0], 4) if naive else None,
            naive_probability_of_default=naive[1] if naive else None,
            converged=False,
            calculation_basis=basis,
        )

    dd = (math.log(v / inputs.default_point) + (inputs.risk_free_rate - 0.5 * sigma_v**2) * t) / (
        sigma_v * math.sqrt(t)
    )
    return MertonResult(
        distance_to_default=round(dd, 4),
        probability_of_default=_N.cdf(-dd),
        confidence=ResultConfidence.COMPLETE,
        asset_value=round(v, 4),
        asset_volatility=round(sigma_v, 6),
        naive_distance_to_default=round(naive[0], 4) if naive else None,
        naive_probability_of_default=naive[1] if naive else None,
        converged=True,
        calculation_basis=basis,
    )


def market_view(
    consensus: str | None, pd: float | None, low: float, high: float
) -> tuple[str, str]:
    """Does the market model agree with the accounting consensus? Returns (view, reason)."""
    if consensus is None or pd is None or consensus == "INDETERMINATE":
        return "UNAVAILABLE", "One side produced no opinion, so there is nothing to compare."
    market = "LOW" if pd < low else "HIGH" if pd > high else "ELEVATED"
    if (consensus, market) in {("LOW_RISK", "LOW"), ("HIGH_RISK", "HIGH")}:
        return "CONFIRMS", f"The equity market agrees with the accounting models ({consensus})."
    if (consensus, market) in {("LOW_RISK", "HIGH"), ("HIGH_RISK", "LOW")}:
        return (
            "CONTRADICTS",
            f"The accounting models say {consensus} but the market-implied PD of "
            f"{pd:.2%} says otherwise. One of them is seeing something the other is not.",
        )
    return (
        "PARTIAL",
        f"The accounting view is {consensus} and the market-implied PD is {pd:.2%}; "
        "neither a clear agreement nor a clear contradiction.",
    )
