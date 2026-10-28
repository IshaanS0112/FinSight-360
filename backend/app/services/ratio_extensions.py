"""DuPont decomposition, the cash conversion cycle, and multi-year trend.

Separate from ratio_engine.py because none of these is a ratio in the sense that
module means: DuPont is an identity that decomposes one, the cycle is a day
count, and the trend block compares years.

Three judgements, each tested:
  DuPont is withheld wherever ROE is withheld (at non-positive equity every term
  still multiplies out to a plausible number).
  The decomposition is reconciled against ROE computed directly, not asserted.
  Day counts use average balances where a prior year exists, ending balances
  otherwise, and record which.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.services import line_items as li

DAYS_IN_YEAR = 365

DUPONT_3_TERMS: tuple[str, ...] = ("net_margin", "asset_turnover", "equity_multiplier")
DUPONT_5_TERMS: tuple[str, ...] = (
    "tax_burden",
    "interest_burden",
    "operating_margin",
    "asset_turnover",
    "equity_multiplier",
)

DUPONT_DEFINITIONS: dict[str, str] = {
    "net_margin": "net_income / revenue",
    "asset_turnover": "revenue / total_assets",
    "equity_multiplier": "total_assets / shareholder_equity",
    "tax_burden": "net_income / pretax_income",
    "interest_burden": "pretax_income / ebit",
    "operating_margin": "ebit / revenue",
}

DUPONT_MEANINGS: dict[str, str] = {
    "net_margin": "What survives to the bottom line out of every unit of revenue.",
    "asset_turnover": "How hard the asset base is worked - revenue per unit of assets.",
    "equity_multiplier": "Leverage. Rises purely by funding the same assets with less equity.",
    "tax_burden": "The share of pre-tax profit kept after tax.",
    "interest_burden": "The share of operating profit left after financing cost.",
    "operating_margin": "Operating profitability before capital structure and tax.",
}

CYCLE_DEFINITIONS: dict[str, str] = {
    "dio": "365 * inventory / cogs",
    "dso": "365 * accounts_receivable / revenue",
    "dpo": "365 * accounts_payable / cogs",
    "ccc": "dio + dso - dpo",
}

_ROUND = 4
_EPS = 1e-9


@dataclass
class ExtensionResult:
    dupont: dict[str, Any] = field(default_factory=dict)
    cash_conversion_cycle: dict[str, Any] = field(default_factory=dict)
    trend: dict[str, Any] = field(default_factory=dict)
    omitted: list[dict[str, str]] = field(default_factory=list)
    calculation_basis: dict[str, Any] = field(default_factory=dict)


def _round(value: float) -> float:
    return round(value, _ROUND)


def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    """A quotient, or ``None`` if either side is missing or the divisor is zero."""
    if numerator is None or denominator is None or abs(denominator) < _EPS:
        return None
    return numerator / denominator


def compute_dupont(items: dict[str, float]) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Three- and five-step DuPont, each reconciled against ROE computed directly.

    A form whose terms cannot all be computed is absent with a reason. A partial
    DuPont product is not an estimate of ROE, it is a different number.
    """
    omitted: list[dict[str, str]] = []
    equity = li.get(items, "shareholder_equity")
    net_income = li.get(items, "net_income")

    if equity is None or net_income is None:
        omitted.append(
            {"metric": "dupont", "reason": "net_income or shareholder_equity not reported"}
        )
        return {}, omitted
    if equity <= 0:
        omitted.append(
            {
                "metric": "dupont",
                "reason": (
                    "shareholder_equity is zero or negative, so ROE itself is undefined "
                    "and there is nothing to decompose. The equity multiplier would go "
                    "negative and the terms would still multiply out to a plausible "
                    "number - which is precisely the trap the ratio engine refuses."
                ),
            }
        )
        return {}, omitted

    terms: dict[str, float] = {}
    for name in ("net_margin", "asset_turnover", "equity_multiplier", "operating_margin"):
        numerator, denominator = {
            "net_margin": ("net_income", "revenue"),
            "asset_turnover": ("revenue", "total_assets"),
            "equity_multiplier": ("total_assets", "shareholder_equity"),
            "operating_margin": ("ebit", "revenue"),
        }[name]
        value = _ratio(li.get(items, numerator), li.get(items, denominator))
        if value is not None:
            terms[name] = value

    pretax = li.get(items, "pretax_income")
    tax_burden = _ratio(net_income, pretax)
    interest_burden = _ratio(pretax, li.get(items, "ebit"))
    if tax_burden is not None:
        terms["tax_burden"] = tax_burden
    if interest_burden is not None:
        terms["interest_burden"] = interest_burden

    roe = net_income / equity
    result: dict[str, Any] = {"roe": _round(100.0 * roe), "roe_basis": "100 * net_income / equity"}

    for label, required in (("three_step", DUPONT_3_TERMS), ("five_step", DUPONT_5_TERMS)):
        missing = [t for t in required if t not in terms]
        if missing:
            omitted.append(
                {
                    "metric": f"dupont_{label}",
                    "reason": f"terms not computable from the reported line items: {missing}",
                }
            )
            continue
        product = 1.0
        for term in required:
            product *= terms[term]
        residual = product - roe
        result[label] = {
            "terms": {
                term: {
                    "value": _round(terms[term]),
                    "definition": DUPONT_DEFINITIONS[term],
                    "meaning": DUPONT_MEANINGS[term],
                }
                for term in required
            },
            "product_roe_pct": _round(100.0 * product),
            "residual_pct": _round(100.0 * residual),
            # A non-zero residual means a term came from a different period.
            "reconciles": abs(residual) <= max(abs(roe), _EPS) * 0.001,
        }

    return result, omitted


def _average(current: float | None, prior: float | None) -> tuple[float | None, str]:
    """Average of the two balances, or the ending balance with the basis named."""
    if current is None:
        return None, "UNAVAILABLE"
    if prior is None:
        return current, "ENDING_BALANCE"
    return (current + prior) / 2.0, "AVERAGE_BALANCE"


def compute_cash_conversion_cycle(
    items: dict[str, float], prior_items: dict[str, float] | None
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Days inventory, receivables and payables outstanding, and their net.

    Each leg stands alone: a missing DIO omits DIO and the total, not the block.
    """
    omitted: list[dict[str, str]] = []
    prior = prior_items or {}
    cogs = li.get(items, "cogs")
    revenue = li.get(items, "revenue")

    components: dict[str, Any] = {}
    bases: set[str] = set()

    for key, balance_key, driver, driver_name in (
        ("dio", "inventory", cogs, "cogs"),
        ("dso", "accounts_receivable", revenue, "revenue"),
        ("dpo", "accounts_payable", cogs, "cogs"),
    ):
        balance, basis = _average(li.get(items, balance_key), li.get(prior, balance_key))
        if balance is None:
            omitted.append({"metric": key, "reason": f"{balance_key} not reported"})
            continue
        if driver is None or abs(driver) < _EPS:
            omitted.append({"metric": key, "reason": f"{driver_name} not reported or zero"})
            continue
        components[key] = {
            "days": _round(DAYS_IN_YEAR * balance / driver),
            "balance_used": _round(balance),
            "balance_basis": basis,
            "definition": CYCLE_DEFINITIONS[key],
        }
        bases.add(basis)

    if {"dio", "dso", "dpo"} <= set(components):
        components["ccc"] = {
            "days": _round(
                components["dio"]["days"] + components["dso"]["days"] - components["dpo"]["days"]
            ),
            "definition": CYCLE_DEFINITIONS["ccc"],
            "meaning": (
                "Days of cash tied up between paying a supplier and collecting from a "
                "customer. Negative means the company is financed by its own supply chain."
            ),
        }
    else:
        omitted.append(
            {
                "metric": "ccc",
                "reason": (
                    "the cycle is the sum of all three day counts, and "
                    f"{sorted({'dio', 'dso', 'dpo'} - set(components))} could not be computed"
                ),
            }
        )

    if components:
        components["basis"] = "AVERAGE_BALANCE" if bases == {"AVERAGE_BALANCE"} else sorted(bases)
    return components, omitted


def compute_trend(history: dict[int, dict[str, float]]) -> tuple[dict[str, Any], list[str]]:
    """Year-on-year change and CAGR for every ratio present in two or more years.

    CAGR needs both endpoints strictly positive. A compound rate across a sign
    change is not a real number, so those series report absolute change instead.
    """
    years = sorted(history)
    if len(years) < 2:
        return {}, ["fewer than two fiscal years on file; no trend is computable"]

    first_year, last_year = years[0], years[-1]
    span = last_year - first_year
    series: dict[str, Any] = {}
    notes: list[str] = []

    keys = sorted({key for values in history.values() for key in values})
    for key in keys:
        points = {year: history[year][key] for year in years if key in history[year]}
        if len(points) < 2:
            continue
        ordered = sorted(points)
        start, end = points[ordered[0]], points[ordered[-1]]
        entry: dict[str, Any] = {
            "by_year": {str(year): points[year] for year in ordered},
            "first_year": ordered[0],
            "last_year": ordered[-1],
            "change": _round(end - start),
            "direction": "up" if end > start else "down" if end < start else "flat",
        }
        if abs(start) > _EPS:
            entry["change_pct"] = _round(100.0 * (end - start) / abs(start))
        if start > 0 and end > 0 and span > 0:
            entry["cagr_pct"] = _round(100.0 * ((end / start) ** (1.0 / span) - 1.0))
        else:
            entry["cagr_omitted"] = (
                "CAGR needs both endpoints strictly positive; a compound rate across a "
                "sign change or from zero is not a real number."
            )
        series[key] = entry

    if not series:
        notes.append("no ratio was computable in two or more of the years on file")
    return {"years": years, "span_years": span, "ratios": series}, notes


def compute_extensions(
    *,
    items: dict[str, float],
    prior_items: dict[str, float] | None,
    history: dict[int, dict[str, float]],
    fiscal_year: int | None,
) -> ExtensionResult:
    """DuPont, the cash conversion cycle and the trend block, in one pass."""
    dupont, dupont_omitted = compute_dupont(items)
    cycle, cycle_omitted = compute_cash_conversion_cycle(items, prior_items)
    trend, trend_notes = compute_trend(history)

    return ExtensionResult(
        dupont=dupont,
        cash_conversion_cycle=cycle,
        trend=trend,
        omitted=[
            {"ratio": entry["metric"], "reason": entry["reason"]}
            for entry in dupont_omitted + cycle_omitted
        ],
        calculation_basis={
            "fiscal_year": fiscal_year,
            "prior_year_available": prior_items is not None,
            "days_in_year": DAYS_IN_YEAR,
            "dupont_definitions": DUPONT_DEFINITIONS,
            "cycle_definitions": CYCLE_DEFINITIONS,
            "cycle_balance_basis": cycle.get("basis", "UNAVAILABLE"),
            "trend_notes": trend_notes,
            "notes": [
                "DuPont is an algebraic identity; the product of its terms is reconciled "
                "against ROE computed directly and the residual is reported.",
                "Day counts use average balances where a prior year exists and ending "
                "balances otherwise; balance_basis says which was used for each.",
            ],
        },
    )
