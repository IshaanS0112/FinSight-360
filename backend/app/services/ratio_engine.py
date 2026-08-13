"""Deterministic ratio computation.

Ten ratios across the four standard categories. No model, no network, no
randomness - the same line items always produce the same numbers.

Three things in here are decisions rather than transcription, and each is
documented at its call site because each is the kind of thing an interviewer
pushes on:

1. **Definitions vary and the choice is visible.** Quick ratio has at least two
   accepted forms. Asset and inventory turnover can use ending or average
   balances. This module implements the specified form and records the exact
   formula string in the result, so a reader comparing against a data provider's
   figure can see immediately whether they disagree on arithmetic or on
   definition. ``docs/architecture.md`` works one such disagreement through.

2. **Some ratios are undefined rather than large.** ROE and debt-to-equity have
   no meaning at negative shareholders' equity: a company losing money with
   equity of -1bn produces a positive ROE, which reads as excellent performance.
   Those ratios are omitted with a reason, not reported.

3. **Nothing defaults to zero.** A missing line item omits the ratio that needs
   it. See ``line_items.get``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.enums import RatioCategory, ResultConfidence
from app.services import line_items as li
from app.services.benchmarks import RATIO_RULES, RULES_BY_CATEGORY


@dataclass
class RatioResult:
    liquidity: dict[str, float] = field(default_factory=dict)
    profitability: dict[str, float] = field(default_factory=dict)
    leverage: dict[str, float] = field(default_factory=dict)
    efficiency: dict[str, float] = field(default_factory=dict)
    omitted: list[dict[str, str]] = field(default_factory=list)
    calculation_basis: dict[str, Any] = field(default_factory=dict)
    confidence: ResultConfidence = ResultConfidence.COMPLETE

    @property
    def all_ratios(self) -> dict[str, float]:
        return {**self.liquidity, **self.profitability, **self.leverage, **self.efficiency}

    def by_category(self, category: RatioCategory) -> dict[str, float]:
        return {
            RatioCategory.LIQUIDITY: self.liquidity,
            RatioCategory.PROFITABILITY: self.profitability,
            RatioCategory.LEVERAGE: self.leverage,
            RatioCategory.EFFICIENCY: self.efficiency,
        }[category]


# Formula strings are stored in calculation_basis so the result is self-describing.
FORMULAS: dict[str, str] = {
    "current_ratio": "current_assets / current_liabilities",
    "quick_ratio": "(current_assets - inventory) / current_liabilities",
    "roe": "100 * net_income / shareholder_equity",
    "roa": "100 * net_income / total_assets",
    "net_margin": "100 * net_income / revenue",
    "gross_margin": "100 * (revenue - cogs) / revenue",
    "debt_to_equity": "total_debt / shareholder_equity",
    "interest_coverage": "ebit / interest_expense",
    "asset_turnover": "revenue / total_assets",
    "inventory_turnover": "cogs / inventory",
}

# Ratios expressed as percentages rather than multiples. Carried explicitly
# because the benchmark table has to be in the same unit as the computed ratio,
# and a percent-vs-fraction mismatch is a factor-of-100 error that still looks
# like a plausible number.
PERCENT_RATIOS: frozenset[str] = frozenset({"roe", "roa", "net_margin", "gross_margin"})

_ROUND = 4


def _round(value: float) -> float:
    return round(value, _ROUND)


def compute_ratios(items: dict[str, float]) -> RatioResult:
    """Compute every ratio the supplied line items support."""
    result = RatioResult()
    omitted: list[dict[str, str]] = []

    def omit(key: str, reason: str) -> None:
        omitted.append({"ratio": key, "reason": reason})

    get = li.get

    # --- Liquidity ---------------------------------------------------------
    current_assets = get(items, "current_assets")
    current_liabilities = get(items, "current_liabilities")
    inventory = get(items, "inventory")

    if current_assets is None or current_liabilities is None:
        omit("current_ratio", "current_assets or current_liabilities not reported")
        omit("quick_ratio", "current_assets or current_liabilities not reported")
    elif current_liabilities == 0:
        omit("current_ratio", "current_liabilities is zero")
        omit("quick_ratio", "current_liabilities is zero")
    else:
        result.liquidity["current_ratio"] = _round(current_assets / current_liabilities)
        if inventory is None:
            # Deliberately not defaulting inventory to 0: that would make the
            # quick ratio equal the current ratio and hide the omission.
            omit("quick_ratio", "inventory not reported; not assumed to be zero")
        else:
            result.liquidity["quick_ratio"] = _round(
                (current_assets - inventory) / current_liabilities
            )

    # --- Profitability -----------------------------------------------------
    net_income = get(items, "net_income")
    total_assets = get(items, "total_assets")
    equity = get(items, "shareholder_equity")
    revenue = get(items, "revenue")

    if net_income is None or equity is None:
        omit("roe", "net_income or shareholder_equity not reported")
    elif equity <= 0:
        omit(
            "roe",
            "shareholder_equity is zero or negative; ROE is undefined here. A loss "
            "divided by negative equity returns a positive number that reads as "
            "strong performance, so the ratio is withheld rather than reported.",
        )
    else:
        result.profitability["roe"] = _round(100.0 * net_income / equity)

    if net_income is None or total_assets is None:
        omit("roa", "net_income or total_assets not reported")
    elif total_assets == 0:
        omit("roa", "total_assets is zero")
    else:
        result.profitability["roa"] = _round(100.0 * net_income / total_assets)

    if net_income is None or revenue is None:
        omit("net_margin", "net_income or revenue not reported")
    elif revenue == 0:
        omit("net_margin", "revenue is zero")
    else:
        result.profitability["net_margin"] = _round(100.0 * net_income / revenue)

    gross_profit = li.derive_gross_profit(items)
    if gross_profit is None or revenue is None:
        omit("gross_margin", "gross_profit (or revenue and cogs) not reported")
    elif revenue == 0:
        omit("gross_margin", "revenue is zero")
    else:
        result.profitability["gross_margin"] = _round(100.0 * gross_profit / revenue)

    # --- Leverage ----------------------------------------------------------
    total_debt = get(items, "total_debt")
    ebit = get(items, "ebit")
    interest_expense = get(items, "interest_expense")

    if total_debt is None or equity is None:
        omit("debt_to_equity", "total_debt or shareholder_equity not reported")
    elif equity <= 0:
        omit(
            "debt_to_equity",
            "shareholder_equity is zero or negative; the ratio is undefined. Negative "
            "equity is itself the solvency finding - see the Altman X4 component, "
            "which handles it correctly.",
        )
    else:
        result.leverage["debt_to_equity"] = _round(total_debt / equity)

    if ebit is None or interest_expense is None:
        omit("interest_coverage", "ebit or interest_expense not reported")
    elif interest_expense == 0:
        omit(
            "interest_coverage",
            "interest_expense is zero; coverage is unbounded rather than infinite, "
            "which for a debt-free company is a finding and not a number.",
        )
    else:
        # Magnitude, because filings present interest expense with either sign.
        result.leverage["interest_coverage"] = _round(ebit / abs(interest_expense))

    # --- Efficiency --------------------------------------------------------
    cogs = get(items, "cogs")

    if revenue is None or total_assets is None:
        omit("asset_turnover", "revenue or total_assets not reported")
    elif total_assets == 0:
        omit("asset_turnover", "total_assets is zero")
    else:
        # Ending total assets, per the project spec. Providers that publish an
        # asset turnover figure commonly use AVERAGE assets across the year, so
        # a small disagreement with a published figure is expected and is a
        # definitional difference, not an arithmetic error. Worked through in
        # docs/architecture.md.
        result.efficiency["asset_turnover"] = _round(revenue / total_assets)

    if cogs is None or inventory is None:
        omit("inventory_turnover", "cogs or inventory not reported")
    elif inventory == 0:
        omit("inventory_turnover", "inventory is zero; turnover is undefined")
    else:
        # Ending inventory, not average inventory. The spec asks for average, but
        # this is a single-fiscal-year system by design (V1 scope) and there is
        # no prior-year balance to average with. Stating that is more useful than
        # calling an ending-balance figure an average.
        result.efficiency["inventory_turnover"] = _round(cogs / inventory)

    result.omitted = omitted
    computed = len(result.all_ratios)
    result.confidence = (
        ResultConfidence.COMPLETE
        if computed == len(RATIO_RULES)
        else ResultConfidence.UNUSABLE
        if computed == 0
        else ResultConfidence.PARTIAL
    )
    result.calculation_basis = {
        "formulas": {k: FORMULAS[k] for k in sorted(result.all_ratios)},
        "percent_ratios": sorted(PERCENT_RATIOS),
        "ratios_computed": computed,
        "ratios_possible": len(RATIO_RULES),
        "turnover_basis": "ENDING_BALANCE",
        "quick_ratio_definition": "(current_assets - inventory) / current_liabilities",
        "line_items_used": sorted(items),
        "notes": [
            "Every ratio is arithmetic over reported line items. No model is involved.",
            "A ratio absent from the output was not computed; see omitted_ratios for why.",
        ],
    }
    return result


def category_summary(result: RatioResult) -> dict[str, list[str]]:
    """Which ratios landed in each bucket, for the health score and the UI."""
    return {
        category.value: [
            rule.key for rule in RULES_BY_CATEGORY[category] if rule.key in result.all_ratios
        ]
        for category in RatioCategory
    }
