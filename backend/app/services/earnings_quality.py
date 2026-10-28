"""Piotroski F-Score and Beneish M-Score: is the reported number trustworthy.

Altman and Ohlson ask whether a company will fail. These ask the prior question -
whether the numbers those models were fed can be believed.

The two have deliberately opposite partial-result policies:
  Piotroski reports a partial score but withholds the band (bands are calibrated
  on all nine tests).
  Beneish withholds the score entirely. Each index sits near 1.0 by construction,
  so a dropped term removes ~its whole coefficient from a score measured against
  -1.78, and substituting the neutral 1.0 asserts the very thing under test.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.config import Settings
from app.enums import EarningsQualityBand, ResultConfidence
from app.services import line_items as li

PIOTROSKI_CITATION = (
    "Piotroski, J. D. (2000). Value Investing: The Use of Historical Financial "
    "Statement Information to Separate Winners from Losers. Journal of Accounting "
    "Research, 38 (Supplement), 1-41."
)

BENEISH_CITATION = (
    "Beneish, M. D. (1999). The Detection of Earnings Manipulation. Financial "
    "Analysts Journal, 55(5), 24-36. Eight-variable model, estimated on 74 firms "
    "with SEC-identified earnings manipulation against 2,332 control firms."
)

ROA_BASIS_NOTE = (
    "ROA here is net_income / ending total_assets, matching the ratio engine. "
    "Piotroski's paper uses income before extraordinary items divided by "
    "BEGINNING-of-year total assets. The difference is a denominator one year "
    "older. It cannot change the sign of test 1, and it moves test 3 only where "
    "the two years' asset bases differ by more than the change in return. This is "
    "a documented deviation from the paper, recorded here and in "
    "docs/architecture.md rather than presented as the original."
)

F_SCORE_TESTS: dict[str, dict[str, str]] = {
    "roa_positive": {
        "group": "profitability",
        "question": "Is return on assets positive?",
        "definition": "net_income / total_assets > 0",
    },
    "cfo_positive": {
        "group": "profitability",
        "question": "Is operating cash flow positive?",
        "definition": "operating_cash_flow > 0",
    },
    "roa_improving": {
        "group": "profitability",
        "question": "Did return on assets rise year on year?",
        "definition": "ROA(t) > ROA(t-1)",
    },
    "accruals": {
        "group": "profitability",
        "question": "Does operating cash flow exceed net income?",
        "definition": "operating_cash_flow > net_income",
    },
    "leverage_falling": {
        "group": "leverage_liquidity_funding",
        "question": "Did long-term debt fall as a share of assets?",
        "definition": "long_term_debt / total_assets decreased vs prior year",
    },
    "liquidity_rising": {
        "group": "leverage_liquidity_funding",
        "question": "Did the current ratio improve?",
        "definition": "current_ratio increased vs prior year",
    },
    "no_dilution": {
        "group": "leverage_liquidity_funding",
        "question": "Were no new shares issued?",
        "definition": "shares_outstanding did not increase vs prior year",
    },
    "margin_rising": {
        "group": "operating_efficiency",
        "question": "Did gross margin improve?",
        "definition": "gross_margin increased vs prior year",
    },
    "turnover_rising": {
        "group": "operating_efficiency",
        "question": "Did asset turnover improve?",
        "definition": "asset_turnover increased vs prior year",
    },
}

F_SCORE_MEANINGS: dict[str, str] = {
    "accruals": (
        "The accrual-quality test, and the one that overlaps with Beneish. Profit "
        "that is not turning into cash is the single most common signature of "
        "aggressive revenue recognition."
    ),
    "no_dilution": (
        "Piotroski reads an equity issue by an already-weak firm as management "
        "signalling it cannot fund itself internally."
    ),
}

M_SCORE_DEFINITIONS: dict[str, str] = {
    "dsri": "(receivables_t / sales_t) / (receivables_t-1 / sales_t-1)",
    "gmi": "gross_margin_t-1 / gross_margin_t",
    "aqi": (
        "[1 - (current_assets_t + ppe_t) / total_assets_t] / "
        "[1 - (current_assets_t-1 + ppe_t-1) / total_assets_t-1]"
    ),
    "sgi": "sales_t / sales_t-1",
    "depi": (
        "[depreciation_t-1 / (ppe_t-1 + depreciation_t-1)] / "
        "[depreciation_t / (ppe_t + depreciation_t)]"
    ),
    "sgai": "(sga_t / sales_t) / (sga_t-1 / sales_t-1)",
    "tata": "(income_continuing_ops_t - operating_cash_flow_t) / total_assets_t",
    "lvgi": (
        "[(current_liabilities_t + long_term_debt_t) / total_assets_t] / "
        "[(current_liabilities_t-1 + long_term_debt_t-1) / total_assets_t-1]"
    ),
}

M_SCORE_MEANINGS: dict[str, str] = {
    "dsri": "Receivables growing faster than sales - the classic channel-stuffing signature.",
    "gmi": "Deteriorating gross margin, which raises the incentive to manage earnings.",
    "aqi": "A rising share of assets that are neither current nor PP&E: capitalised soft costs.",
    "sgi": "Growth itself. High-growth firms face more pressure to sustain the number.",
    "depi": "A slowing depreciation rate, which flatters earnings without any cash effect.",
    "sgai": "Overhead rising faster than sales - a negative signal, hence the negative weight.",
    "tata": "Total accruals over assets. The largest weight in the model by a wide margin.",
    "lvgi": "Rising leverage, and with it the pressure of debt covenants.",
}

_EPS = 1e-9


@dataclass
class PiotroskiResult:
    score: int | None
    band: EarningsQualityBand | None
    components: dict[str, dict[str, Any]] = field(default_factory=dict)
    tests_evaluated: int = 0
    confidence: ResultConfidence = ResultConfidence.COMPLETE
    omitted: list[dict[str, str]] = field(default_factory=list)
    calculation_basis: dict[str, Any] = field(default_factory=dict)


@dataclass
class BeneishResult:
    m_score: float | None
    manipulation_flag: bool | None
    strict_manipulation_flag: bool | None
    components: dict[str, dict[str, float]] = field(default_factory=dict)
    confidence: ResultConfidence = ResultConfidence.COMPLETE
    omitted: list[dict[str, str]] = field(default_factory=list)
    calculation_basis: dict[str, Any] = field(default_factory=dict)


def _divide(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or abs(denominator) < _EPS:
        return None
    return numerator / denominator


def _gross_margin(items: dict[str, float]) -> float | None:
    gross_profit = li.derive_gross_profit(items)
    return _divide(gross_profit, li.get(items, "revenue"))


def compute_piotroski_f_score(
    items: dict[str, float], prior_items: dict[str, float] | None
) -> PiotroskiResult:
    """Nine binary tests, one point each, and a reason for every one skipped."""
    prior = prior_items or {}
    results: dict[str, dict[str, Any]] = {}
    omitted: list[dict[str, str]] = []

    def record(key: str, passed: bool | None, values: dict[str, Any], reason: str = "") -> None:
        entry: dict[str, Any] = {**F_SCORE_TESTS[key], **values}
        if key in F_SCORE_MEANINGS:
            entry["meaning"] = F_SCORE_MEANINGS[key]
        if passed is None:
            entry["status"] = "NOT_EVALUATED"
            entry["reason"] = reason
            omitted.append({"test": key, "reason": reason})
        else:
            entry["status"] = "PASS" if passed else "FAIL"
            entry["points"] = 1 if passed else 0
        results[key] = entry

    roa = _divide(li.get(items, "net_income"), li.get(items, "total_assets"))
    prior_roa = _divide(li.get(prior, "net_income"), li.get(prior, "total_assets"))
    cfo = li.get(items, "operating_cash_flow")
    net_income = li.get(items, "net_income")

    record(
        "roa_positive",
        None if roa is None else roa > 0,
        {"roa": roa},
        "net_income or total_assets not reported",
    )
    record(
        "cfo_positive",
        None if cfo is None else cfo > 0,
        {"operating_cash_flow": cfo},
        "operating_cash_flow not reported",
    )
    record(
        "roa_improving",
        None if roa is None or prior_roa is None else roa > prior_roa,
        {"roa": roa, "roa_prior": prior_roa},
        "return on assets is not computable in both years",
    )
    record(
        "accruals",
        None if cfo is None or net_income is None else cfo > net_income,
        {"operating_cash_flow": cfo, "net_income": net_income},
        "operating_cash_flow or net_income not reported",
    )

    leverage = _divide(li.get(items, "long_term_debt"), li.get(items, "total_assets"))
    prior_leverage = _divide(li.get(prior, "long_term_debt"), li.get(prior, "total_assets"))
    record(
        "leverage_falling",
        None if leverage is None or prior_leverage is None else leverage < prior_leverage,
        {"lt_debt_to_assets": leverage, "lt_debt_to_assets_prior": prior_leverage},
        "long_term_debt or total_assets is missing in one of the two years",
    )

    current_ratio = _divide(li.get(items, "current_assets"), li.get(items, "current_liabilities"))
    prior_current_ratio = _divide(
        li.get(prior, "current_assets"), li.get(prior, "current_liabilities")
    )
    record(
        "liquidity_rising",
        None
        if current_ratio is None or prior_current_ratio is None
        else current_ratio > prior_current_ratio,
        {"current_ratio": current_ratio, "current_ratio_prior": prior_current_ratio},
        "the current ratio is not computable in both years",
    )

    shares, prior_shares = li.get(items, "shares_outstanding"), li.get(prior, "shares_outstanding")
    record(
        "no_dilution",
        None if shares is None or prior_shares is None else shares <= prior_shares,
        {"shares_outstanding": shares, "shares_outstanding_prior": prior_shares},
        "shares_outstanding is missing in one of the two years",
    )

    margin, prior_margin = _gross_margin(items), _gross_margin(prior)
    record(
        "margin_rising",
        None if margin is None or prior_margin is None else margin > prior_margin,
        {"gross_margin": margin, "gross_margin_prior": prior_margin},
        "gross margin is not computable in both years",
    )

    turnover = _divide(li.get(items, "revenue"), li.get(items, "total_assets"))
    prior_turnover = _divide(li.get(prior, "revenue"), li.get(prior, "total_assets"))
    record(
        "turnover_rising",
        None if turnover is None or prior_turnover is None else turnover > prior_turnover,
        {"asset_turnover": turnover, "asset_turnover_prior": prior_turnover},
        "asset turnover is not computable in both years",
    )

    evaluated = [entry for entry in results.values() if entry["status"] != "NOT_EVALUATED"]
    score = sum(entry["points"] for entry in evaluated) if evaluated else None
    complete = len(evaluated) == len(F_SCORE_TESTS)

    band: EarningsQualityBand | None = None
    if complete and score is not None:
        band = (
            EarningsQualityBand.STRONG
            if score >= 8
            else EarningsQualityBand.WEAK
            if score <= 4
            else EarningsQualityBand.MIXED
        )

    return PiotroskiResult(
        score=score,
        band=band,
        components=results,
        tests_evaluated=len(evaluated),
        confidence=(
            ResultConfidence.COMPLETE
            if complete
            else ResultConfidence.UNUSABLE
            if not evaluated
            else ResultConfidence.PARTIAL
        ),
        omitted=omitted,
        calculation_basis={
            "citation": PIOTROSKI_CITATION,
            "roa_basis": ROA_BASIS_NOTE,
            "tests_evaluated": len(evaluated),
            "tests_total": len(F_SCORE_TESTS),
            "bands": {"STRONG": "8-9", "MIXED": "5-7", "WEAK": "0-4"},
            "band_withheld_reason": (
                None
                if complete
                else (
                    f"Only {len(evaluated)} of {len(F_SCORE_TESTS)} tests could be "
                    "evaluated. The score is the sum of those, but no band is assigned: "
                    "Piotroski's 8-9 / 5-7 / 0-4 reading is calibrated on the full nine, "
                    "and scoring a partial total against a full-scale band would report "
                    "a company as weak for not disclosing a line item."
                )
            ),
            "prior_year_available": prior_items is not None,
        },
    )


def _beneish_indices(
    items: dict[str, float], prior: dict[str, float]
) -> tuple[dict[str, float], list[dict[str, str]]]:
    """The eight ratio-of-ratios, and a reason for each that cannot be formed."""
    indices: dict[str, float] = {}
    omitted: list[dict[str, str]] = []

    def add(key: str, value: float | None, reason: str) -> None:
        if value is None:
            omitted.append({"component": key, "reason": reason})
        else:
            indices[key] = value

    sales, prior_sales = li.get(items, "revenue"), li.get(prior, "revenue")

    add(
        "dsri",
        _divide(
            _divide(li.get(items, "accounts_receivable"), sales),
            _divide(li.get(prior, "accounts_receivable"), prior_sales),
        ),
        "accounts_receivable or revenue is missing in one of the two years",
    )

    add(
        "gmi",
        _divide(_gross_margin(prior), _gross_margin(items)),
        "gross margin is not computable in both years",
    )

    def asset_quality(source: dict[str, float]) -> float | None:
        total_assets = li.get(source, "total_assets")
        current_assets = li.get(source, "current_assets")
        ppe = li.get(source, "ppe_net")
        if total_assets is None or current_assets is None or ppe is None:
            return None
        if abs(total_assets) < _EPS:
            return None
        return 1.0 - (current_assets + ppe) / total_assets

    add(
        "aqi",
        _divide(asset_quality(items), asset_quality(prior)),
        "total_assets, current_assets or ppe_net is missing in one of the two years",
    )

    add("sgi", _divide(sales, prior_sales), "revenue is missing in one of the two years")

    def depreciation_rate(source: dict[str, float]) -> float | None:
        depreciation = li.get(source, "depreciation_amortization")
        ppe = li.get(source, "ppe_net")
        if depreciation is None or ppe is None:
            return None
        return _divide(depreciation, ppe + depreciation)

    add(
        "depi",
        _divide(depreciation_rate(prior), depreciation_rate(items)),
        "depreciation_amortization or ppe_net is missing in one of the two years",
    )

    add(
        "sgai",
        _divide(
            _divide(li.get(items, "sga_expense"), sales),
            _divide(li.get(prior, "sga_expense"), prior_sales),
        ),
        "sga_expense or revenue is missing in one of the two years",
    )

    income = li.get(items, "income_continuing_ops")
    cfo = li.get(items, "operating_cash_flow")
    add(
        "tata",
        None
        if income is None or cfo is None
        else _divide(income - cfo, li.get(items, "total_assets")),
        "income_continuing_ops, operating_cash_flow or total_assets not reported",
    )

    def gearing(source: dict[str, float]) -> float | None:
        current_liabilities = li.get(source, "current_liabilities")
        long_term_debt = li.get(source, "long_term_debt")
        if current_liabilities is None or long_term_debt is None:
            return None
        return _divide(current_liabilities + long_term_debt, li.get(source, "total_assets"))

    add(
        "lvgi",
        _divide(gearing(items), gearing(prior)),
        "current_liabilities, long_term_debt or total_assets is missing in one of the two years",
    )

    return indices, omitted


def compute_beneish_m_score(
    items: dict[str, float], prior_items: dict[str, float] | None, settings: Settings
) -> BeneishResult:
    """The eight-variable M-Score, or a refusal naming what was missing.

    All eight components are required; see the module docstring for why.
    """
    coefficients = settings.beneish_coefficients()

    if prior_items is None:
        return BeneishResult(
            m_score=None,
            manipulation_flag=None,
            strict_manipulation_flag=None,
            confidence=ResultConfidence.UNUSABLE,
            omitted=[
                {
                    "component": key,
                    "reason": "no prior fiscal year on file; every Beneish index is a "
                    "ratio of year t to year t-1",
                }
                for key in M_SCORE_DEFINITIONS
            ],
            calculation_basis={
                "citation": BENEISH_CITATION,
                "reason": (
                    "Beneish compares a year against the one before it. With one year "
                    "on file there is nothing to compare, and the model is not "
                    "approximated from a single period."
                ),
            },
        )

    indices, omitted = _beneish_indices(items, prior_items)

    if omitted:
        return BeneishResult(
            m_score=None,
            manipulation_flag=None,
            strict_manipulation_flag=None,
            components={
                key: {"ratio": round(value, 6), "coefficient": coefficients[key]}
                for key, value in indices.items()
            },
            confidence=ResultConfidence.UNUSABLE,
            omitted=omitted,
            calculation_basis={
                "citation": BENEISH_CITATION,
                "refusal": (
                    "The M-Score is withheld because "
                    f"{sorted(entry['component'] for entry in omitted)} could not be "
                    "computed. Unlike the Altman score, a partial M-Score is not a "
                    "conservative estimate. Each index sits near 1.0 by construction, so "
                    "an unchanged receivables balance contributes 0.920 to M; dropping "
                    "that term removes 0.920 from a score compared against a threshold "
                    "of -1.78. Substituting the neutral value 1.0 is worse: it asserts "
                    "that nothing changed year over year, which is the claim the model "
                    "exists to test."
                ),
                "components_computed": sorted(indices),
                "components_required": sorted(M_SCORE_DEFINITIONS),
            },
        )

    m_score = coefficients["intercept"]
    components: dict[str, dict[str, float]] = {}
    for key in M_SCORE_DEFINITIONS:
        coefficient = coefficients[key]
        contribution = coefficient * indices[key]
        m_score += contribution
        components[key] = {
            "ratio": round(indices[key], 6),
            "coefficient": coefficient,
            "contribution": round(contribution, 6),
        }

    m_score = round(m_score, 4)
    return BeneishResult(
        m_score=m_score,
        manipulation_flag=m_score > settings.beneish_threshold,
        strict_manipulation_flag=m_score > settings.beneish_strict_threshold,
        components=components,
        confidence=ResultConfidence.COMPLETE,
        calculation_basis={
            "citation": BENEISH_CITATION,
            "formula": "M = intercept + "
            + " + ".join(f"{coefficients[k]}*{k.upper()}" for k in M_SCORE_DEFINITIONS),
            "intercept": coefficients["intercept"],
            "component_definitions": M_SCORE_DEFINITIONS,
            "component_meanings": M_SCORE_MEANINGS,
            "thresholds": {
                "beneish_1999": settings.beneish_threshold,
                "stricter_commonly_cited": settings.beneish_strict_threshold,
            },
            "threshold_note": (
                f"Beneish's own cutoff is {settings.beneish_threshold}; "
                f"{settings.beneish_strict_threshold} is widely cited in later work as a "
                "stricter alternative that trades false positives for false negatives. "
                "Both verdicts are reported. Picking one silently would be taking a side "
                "in a disagreement the literature has not settled."
            ),
            "interpretation_limit": (
                "A flag is a screening signal, not a finding of manipulation. Beneish's "
                "own model classified roughly half the manipulators in its sample and "
                "flagged a meaningful share of clean firms. It is a reason to open the "
                "file, not a conclusion about it - and it cannot distinguish aggressive "
                "accounting from a genuine change in the business."
            ),
        },
    )
