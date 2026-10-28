"""DCF-lite: FCFF projected, discounted at a CAPM-derived WACC, Gordon terminal.

    FCFF   = EBIT(1-tax) + D&A - CapEx - change in NWC
    Re     = Rf + beta*(Rm - Rf)                 [CAPM]
    Rd     = interest_expense / total_debt       [pre-tax]
    WACC   = (E/V)*Re + (D/V)*Rd*(1-tax)
    TV     = FCFF_n*(1+g) / (WACC - g)           [Gordon growth]
    EV     = sum FCFF_t/(1+WACC)^t + TV/(1+WACC)^n
    Equity = EV - net debt

No assumption is ever a hidden constant: every input is either a reported line
item or a named field in DcfAssumptions, stored with the result.

Three refusals, each of which a naive implementation reports as a number:
terminal growth at or near WACC, negative base-year EBIT, and no share count.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from app.config import Settings
from app.enums import ResultConfidence
from app.services import line_items as li

_EPS = 1e-9


@dataclass(frozen=True)
class DcfAssumptions:
    """Every dial on the model, stored with the result."""

    revenue_growth: float
    terminal_growth: float
    tax_rate: float
    projection_years: int
    risk_free_rate: float
    equity_risk_premium: float
    beta: float
    # Bypass CAPM and the capital-structure weighting entirely.
    wacc_override: float | None = None
    cost_of_debt_override: float | None = None
    ebit_margin_override: float | None = None

    @classmethod
    def defaults(cls, settings: Settings, **overrides: Any) -> DcfAssumptions:
        base = {
            "revenue_growth": 0.03,
            "terminal_growth": settings.dcf_terminal_growth,
            "tax_rate": settings.dcf_tax_rate,
            "projection_years": settings.dcf_projection_years,
            "risk_free_rate": settings.dcf_risk_free_rate,
            "equity_risk_premium": settings.dcf_equity_risk_premium,
            "beta": settings.dcf_default_beta,
        }
        base.update({k: v for k, v in overrides.items() if v is not None})
        return cls(**base)


@dataclass
class DcfResult:
    assumptions: dict[str, Any]
    wacc: float | None = None
    cost_of_equity: float | None = None
    cost_of_debt: float | None = None
    fcff_projection: list[dict[str, float]] = field(default_factory=list)
    terminal_value: float | None = None
    enterprise_value: float | None = None
    equity_value: float | None = None
    implied_share_price: float | None = None
    upside_downside_pct: float | None = None
    confidence: ResultConfidence = ResultConfidence.COMPLETE
    omitted: list[dict[str, str]] = field(default_factory=list)
    calculation_basis: dict[str, Any] = field(default_factory=dict)


def cost_of_equity(assumptions: DcfAssumptions) -> float:
    """CAPM: ``Rf + beta x (Rm - Rf)``."""
    return assumptions.risk_free_rate + assumptions.beta * assumptions.equity_risk_premium


def compute_wacc(
    items: dict[str, float], assumptions: DcfAssumptions
) -> tuple[float | None, dict[str, Any]]:
    """Capital-structure-weighted cost of capital, or an explicit override.

    Equity is taken at market value where available: WACC weights are market
    weights, and book equity would understate the equity weight.
    """
    detail: dict[str, Any] = {"cost_of_equity": round(cost_of_equity(assumptions), 6)}

    if assumptions.wacc_override is not None:
        detail["source"] = "EXPLICIT_OVERRIDE"
        detail["note"] = (
            "WACC was supplied directly, so CAPM and the capital-structure weighting "
            "were not used. The cost of equity above is what CAPM would have produced."
        )
        return assumptions.wacc_override, detail

    equity_value = li.get(items, "market_value_equity")
    equity_basis = "MARKET_VALUE"
    if equity_value is None:
        shares, price = li.get(items, "shares_outstanding"), li.get(items, "share_price")
        if shares is not None and price is not None:
            equity_value, equity_basis = shares * price, "SHARES_X_PRICE"
        else:
            equity_value = li.get(items, "shareholder_equity")
            equity_basis = "BOOK_VALUE"

    debt = li.get(items, "total_debt")
    if equity_value is None or debt is None:
        detail["source"] = "UNAVAILABLE"
        detail["reason"] = (
            "market or book equity and total debt are both needed to weight the two "
            "costs of capital; supply wacc_override to bypass this."
        )
        return None, detail

    if equity_value <= 0:
        detail["source"] = "UNAVAILABLE"
        detail["reason"] = (
            "equity value is zero or negative, so the weights E/V and D/V are not a "
            "capital structure. A WACC computed from them would be arithmetic, not a "
            "discount rate."
        )
        return None, detail

    if assumptions.cost_of_debt_override is not None:
        rd, rd_basis = assumptions.cost_of_debt_override, "EXPLICIT_OVERRIDE"
    else:
        interest = li.get(items, "interest_expense")
        if interest is None or debt < _EPS:
            rd, rd_basis = 0.0, "ZERO_DEBT_OR_UNREPORTED_INTEREST"
        else:
            rd, rd_basis = abs(interest) / debt, "INTEREST_EXPENSE_OVER_TOTAL_DEBT"

    total = equity_value + debt
    equity_weight, debt_weight = equity_value / total, debt / total
    re = cost_of_equity(assumptions)
    wacc = equity_weight * re + debt_weight * rd * (1.0 - assumptions.tax_rate)

    detail |= {
        "source": "CAPM_AND_CAPITAL_STRUCTURE",
        "equity_value": round(equity_value, 4),
        "equity_basis": equity_basis,
        "debt": round(debt, 4),
        "equity_weight": round(equity_weight, 6),
        "debt_weight": round(debt_weight, 6),
        "cost_of_debt_pretax": round(rd, 6),
        "cost_of_debt_basis": rd_basis,
        "formula": "(E/V)*Re + (D/V)*Rd*(1 - tax)",
    }
    if equity_basis == "BOOK_VALUE":
        detail["equity_basis_warning"] = (
            "No market value of equity was supplied, so book equity was used to weight "
            "the capital structure. WACC weights are market weights: for a company "
            "trading above book, this overweights debt and understates the discount rate."
        )
    return wacc, detail


def _base_year_drivers(items: dict[str, float]) -> tuple[dict[str, float], list[dict[str, str]]]:
    """Ratios to revenue that the projection holds constant.

    Holding D&A, capex and working-capital intensity flat is what makes this
    DCF-lite. It is wrong for a company mid-way through a capex cycle.
    """
    missing: list[dict[str, str]] = []
    revenue = li.get(items, "revenue")
    ebit = li.get(items, "ebit")
    if revenue is None or revenue < _EPS:
        missing.append({"input": "revenue", "reason": "not reported or zero"})
    if ebit is None:
        missing.append({"input": "ebit", "reason": "not reported"})
    if missing:
        return {}, missing

    drivers = {"revenue": revenue, "ebit": ebit, "ebit_margin": ebit / revenue}

    for key, label in (
        ("depreciation_amortization", "da_pct_revenue"),
        ("capital_expenditure", "capex_pct_revenue"),
    ):
        value = li.get(items, key)
        if value is None:
            missing.append(
                {
                    "input": key,
                    "reason": (
                        f"not reported; FCFF needs it and it is not assumed to be zero, "
                        f"because a zero {key} is a claim about the business"
                    ),
                }
            )
        else:
            drivers[label] = abs(value) / revenue

    working_capital = li.working_capital(items)
    if working_capital is None:
        missing.append(
            {
                "input": "working_capital",
                "reason": "current_assets or current_liabilities not reported",
            }
        )
    else:
        drivers["nwc_pct_revenue"] = working_capital / revenue

    return drivers, missing


def _beta_note(beta: float, source: dict[str, Any] | None) -> str:
    if source and source.get("source") == "REGRESSION":
        return (
            f"Beta is {beta}, measured: the Blume-adjusted regression of monthly returns on "
            f"{source['benchmark']} over {source['observations']} months to "
            f"{source['window_end']} (raw beta {source['raw_beta']}, r-squared "
            f"{source['r_squared']}). Override it in the request to test another value."
        )
    return (
        f"Beta is an input, not a measurement. It is {beta}. Computing a real beta needs "
        "a price history; link this company to a listed ticker and the DCF will use a "
        "regression beta instead of this declared value."
    )


def compute_dcf(
    *,
    items: dict[str, float],
    assumptions: DcfAssumptions,
    settings: Settings,
    beta_source: dict[str, Any] | None = None,
) -> DcfResult:
    """Project, discount, and refuse where the model has no meaning.

    beta_source records where the beta came from when it was estimated by
    regression rather than declared.
    """
    stored = asdict(assumptions)
    result = DcfResult(assumptions=stored)

    drivers, missing = _base_year_drivers(items)
    if missing:
        result.confidence = ResultConfidence.UNUSABLE
        result.omitted = missing
        result.calculation_basis = {
            "reason": (
                "FCFF cannot be formed from the reported line items. Every missing input "
                "is listed; none is defaulted to zero."
            ),
            "inputs_required": [
                "revenue",
                "ebit",
                "depreciation_amortization",
                "capital_expenditure",
                "current_assets",
                "current_liabilities",
            ],
        }
        return result

    wacc, wacc_detail = compute_wacc(items, assumptions)
    result.cost_of_equity = wacc_detail.get("cost_of_equity")
    result.cost_of_debt = wacc_detail.get("cost_of_debt_pretax")
    if wacc is None:
        result.confidence = ResultConfidence.UNUSABLE
        result.omitted = [{"input": "wacc", "reason": wacc_detail.get("reason", "unavailable")}]
        result.calculation_basis = {"wacc": wacc_detail}
        return result

    result.wacc = round(wacc, 6)
    spread = wacc - assumptions.terminal_growth
    if spread < settings.dcf_min_wacc_terminal_spread:
        result.confidence = ResultConfidence.UNUSABLE
        result.calculation_basis = {
            "wacc": wacc_detail,
            "refusal": (
                f"Terminal growth ({assumptions.terminal_growth:.2%}) is within "
                f"{settings.dcf_min_wacc_terminal_spread:.2%} of WACC ({wacc:.2%}). The "
                "Gordon terminal value divides by (WACC - g): as the gap closes the "
                "value diverges to infinity, and past it the value turns negative while "
                "still looking like a price. No figure is reported. Lower the terminal "
                "growth rate, or state why this business compounds at the cost of "
                "capital forever."
            ),
            "wacc_terminal_spread": round(spread, 6),
        }
        return result

    margin = (
        assumptions.ebit_margin_override
        if assumptions.ebit_margin_override is not None
        else drivers["ebit_margin"]
    )

    revenue = drivers["revenue"]
    previous_revenue = revenue
    enterprise_value = 0.0
    projection: list[dict[str, float]] = []
    fcff = 0.0

    for year in range(1, assumptions.projection_years + 1):
        revenue *= 1.0 + assumptions.revenue_growth
        ebit = revenue * margin
        depreciation = revenue * drivers["da_pct_revenue"]
        capex = revenue * drivers["capex_pct_revenue"]
        # Working capital scales with revenue.
        change_in_nwc = (revenue - previous_revenue) * drivers["nwc_pct_revenue"]
        fcff = ebit * (1.0 - assumptions.tax_rate) + depreciation - capex - change_in_nwc

        discount_factor = 1.0 / ((1.0 + wacc) ** year)
        present_value = fcff * discount_factor
        enterprise_value += present_value

        projection.append(
            {
                "year": year,
                "revenue": round(revenue, 2),
                "ebit": round(ebit, 2),
                "nopat": round(ebit * (1.0 - assumptions.tax_rate), 2),
                "depreciation_amortization": round(depreciation, 2),
                "capital_expenditure": round(capex, 2),
                "change_in_nwc": round(change_in_nwc, 2),
                "fcff": round(fcff, 2),
                "discount_factor": round(discount_factor, 6),
                "present_value": round(present_value, 2),
            }
        )
        previous_revenue = revenue

    terminal_value = fcff * (1.0 + assumptions.terminal_growth) / spread
    discounted_terminal = terminal_value / ((1.0 + wacc) ** assumptions.projection_years)
    enterprise_value += discounted_terminal

    result.fcff_projection = projection
    result.terminal_value = round(terminal_value, 2)
    result.enterprise_value = round(enterprise_value, 2)

    cash = li.get(items, "cash_and_equivalents")
    debt = li.get(items, "total_debt")
    omitted: list[dict[str, str]] = []
    if debt is None:
        omitted.append(
            {"input": "total_debt", "reason": "not reported; enterprise value cannot be bridged"}
        )
    else:
        net_debt = debt - (cash or 0.0)
        if cash is None:
            omitted.append(
                {
                    "input": "cash_and_equivalents",
                    "reason": (
                        "not reported, so net debt is gross debt. This understates equity "
                        "value by the cash balance rather than overstating it."
                    ),
                }
            )
        result.equity_value = round(enterprise_value - net_debt, 2)

        shares = li.get(items, "shares_outstanding")
        if shares is None or shares < _EPS:
            omitted.append(
                {
                    "input": "shares_outstanding",
                    "reason": (
                        "not reported. Enterprise and equity value stand; the per-share "
                        "figure is withheld rather than divided by a guessed share count."
                    ),
                }
            )
        else:
            result.implied_share_price = round(result.equity_value / shares, 4)
            price = li.get(items, "share_price")
            if price is not None and price > _EPS:
                result.upside_downside_pct = round(
                    100.0 * (result.implied_share_price - price) / price, 2
                )

    negative_ebit = drivers["ebit"] < 0
    result.omitted = omitted
    result.confidence = (
        ResultConfidence.UNUSABLE
        if negative_ebit
        else ResultConfidence.COMPLETE
        if not omitted
        else ResultConfidence.PARTIAL
    )

    result.calculation_basis = {
        "formulas": {
            "fcff": "EBIT*(1-tax) + D&A - CapEx - change in NWC",
            "cost_of_equity": "Rf + beta*(Rm - Rf)   [CAPM]",
            "cost_of_debt": "interest_expense / total_debt   [pre-tax]",
            "wacc": "(E/V)*Re + (D/V)*Rd*(1-tax)",
            "terminal_value": "FCFF_n*(1+g) / (WACC - g)   [Gordon growth]",
            "enterprise_value": "sum FCFF_t/(1+WACC)^t + TV/(1+WACC)^n",
            "equity_value": "enterprise_value - (total_debt - cash)",
        },
        "wacc": wacc_detail,
        "wacc_terminal_spread": round(spread, 6),
        "base_year_drivers": {k: round(v, 6) for k, v in drivers.items()},
        "driver_note": (
            "D&A, capital expenditure and working-capital intensity are held flat as a "
            "share of revenue at their base-year levels. That is the simplification that "
            "makes this DCF-lite, and it is wrong for any company mid-way through a capex "
            "cycle. Run the scenario simulator to see how much the answer depends on it."
        ),
        "terminal_value_share_of_ev": (
            round(discounted_terminal / enterprise_value, 4)
            if abs(enterprise_value) > _EPS
            else None
        ),
        "terminal_value_note": (
            "The share of enterprise value coming from the terminal value is the single "
            "most useful diagnostic on any DCF. Above roughly 75% the answer is a "
            "perpetuity assumption with a five-year schedule attached to it."
        ),
        "beta_note": _beta_note(assumptions.beta, beta_source),
        "beta_source": beta_source or {"source": "DECLARED"},
        "negative_ebit_warning": (
            (
                f"Base-year EBIT is {drivers['ebit']:,.2f}. Every projected FCFF inherits "
                "the sign and the terminal value is a negative perpetuity, so the implied "
                "share price below is an arithmetic consequence of one assumption rather "
                "than a valuation. A loss-making company needs a recovery forecast, which "
                "this module deliberately does not invent."
            )
            if negative_ebit
            else None
        ),
        "market_price_basis": (
            "share_price is the fiscal-year-end close supplied with the filing, not a "
            "live quote. Any upside figure is measured against that date."
        ),
    }
    return result
