"""Bankruptcy risk suite: the Altman family, Ohlson's logit, and their verdict.

Altman (1968) is a discriminant function fitted on 66 manufacturers. Ohlson
(1980) is a logit fitted on 2,163 industrial firms and returns a probability
rather than an index. When they disagree, that disagreement is the output -
see MIXED_SIGNAL in consensus_verdict().

SIZE is ln(total_assets), not Ohlson's ln(total_assets / GNP deflator). That
is a documented deviation; see SIZE_SUBSTITUTION_NOTE and docs/architecture.md.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from app.config import Settings
from app.enums import AltmanModel, ConsensusVerdict, ResultConfidence, SectorClass, Zone
from app.services import line_items as li
from app.services.altman_zscore import (
    FINANCIAL_SECTOR_REFUSAL,
    ZScoreResult,
    compute_z_score,
)

OHLSON_CITATION = (
    "Ohlson, J. A. (1980). Financial Ratios and the Probabilistic Prediction of "
    "Bankruptcy. Journal of Accounting Research, 18(1), 109-131. Model one, "
    "estimated on 105 bankrupt and 2,058 non-bankrupt industrial firms, 1970-1976."
)

SIZE_SUBSTITUTION_NOTE = (
    "SIZE is implemented as ln(total_assets). Ohlson's original is "
    "ln(total_assets / GNP price-level index), deflating to constant dollars "
    "against a historical U.S. GNP implicit price deflator that is not "
    "practically sourceable for a general-purpose tool and has no meaning for a "
    "non-U.S. filer. ln(total_assets) is the standard modern reproduction. This "
    "is a documented deviation from the 1980 paper, not the paper as published: "
    "it shifts every O-Score by -0.407 x ln(deflator), a constant for a given "
    "year, so relative ordering is preserved and the absolute probability is not."
)

TERM_DEFINITIONS: dict[str, str] = {
    "size": "ln(total_assets)  [substituted; see size_substitution]",
    "tlta": "total_liabilities / total_assets",
    "wcta": "working_capital / total_assets",
    "clca": "current_liabilities / current_assets",
    "oeneg": "1 if total_liabilities > total_assets else 0",
    "nita": "net_income / total_assets",
    "futl": "(net_income + depreciation_amortization) / total_liabilities",
    "intwo": "1 if net_income < 0 in both year t and year t-1 else 0",
    "chin": "(NI_t - NI_t-1) / (|NI_t| + |NI_t-1|)",
}

TERM_MEANINGS: dict[str, str] = {
    "size": "Scale. Larger firms fail less often, so the coefficient is negative.",
    "tlta": "Gearing. The largest positive weight in the model - the dominant distress term.",
    "wcta": "Short-term liquidity relative to size.",
    "clca": "Near-term funding pressure: current liabilities against current assets.",
    "oeneg": "A switch, not a scale: liabilities already exceed assets.",
    "nita": "Current profitability relative to size.",
    "futl": "Funds from operations against total debt - can the business service what it owes.",
    "intwo": "Persistence: two consecutive loss years, not one bad one.",
    "chin": "Direction and scale of the change in earnings, bounded to [-1, 1].",
}

# Values can only be 0 or 1, so an omitted one still bounds the probability.
BINARY_TERMS: frozenset[str] = frozenset({"oeneg", "intwo"})


@dataclass
class OhlsonResult:
    o_score: float | None
    probability: float | None
    confidence: ResultConfidence
    components: dict[str, dict[str, float]] = field(default_factory=dict)
    omitted: list[dict[str, str]] = field(default_factory=list)
    probability_bounds: dict[str, float] | None = None
    calculation_basis: dict[str, Any] = field(default_factory=dict)


@dataclass
class RiskSuiteResult:
    altman: ZScoreResult
    ohlson: OhlsonResult
    consensus: ConsensusVerdict
    variants: dict[str, dict[str, Any]] = field(default_factory=dict)
    calculation_basis: dict[str, Any] = field(default_factory=dict)


def logistic(o_score: float) -> float:
    """``e^O / (1 + e^O)``, computed so a large negative O does not overflow."""
    if o_score >= 0:
        return 1.0 / (1.0 + math.exp(-o_score))
    exponential = math.exp(o_score)
    return exponential / (1.0 + exponential)


def _ohlson_terms(
    items: dict[str, float], prior_items: dict[str, float] | None
) -> tuple[dict[str, float], list[dict[str, str]]]:
    """Each of the nine terms, or a reason it could not be computed."""
    terms: dict[str, float] = {}
    omitted: list[dict[str, str]] = []

    def omit(term: str, reason: str) -> None:
        omitted.append({"term": term, "reason": reason})

    total_assets = li.get(items, "total_assets")
    total_liabilities = li.get(items, "total_liabilities")
    net_income = li.get(items, "net_income")

    if not total_assets or total_assets <= 0:
        return {}, [
            {"term": term, "reason": "total_assets not reported, zero or negative"}
            for term in TERM_DEFINITIONS
        ]

    terms["size"] = math.log(total_assets)

    if total_liabilities is None:
        omit("tlta", "total_liabilities not reported")
        omit("oeneg", "total_liabilities not reported")
        omit("futl", "total_liabilities not reported")
    else:
        terms["tlta"] = total_liabilities / total_assets
        terms["oeneg"] = 1.0 if total_liabilities > total_assets else 0.0
        depreciation = li.get(items, "depreciation_amortization")
        if net_income is None or depreciation is None:
            omit(
                "futl",
                "net_income or depreciation_amortization not reported; funds from "
                "operations cannot be proxied without both",
            )
        elif abs(total_liabilities) < 1e-9:
            omit("futl", "total_liabilities is zero")
        else:
            terms["futl"] = (net_income + depreciation) / total_liabilities

    working_capital = li.working_capital(items)
    if working_capital is None:
        omit("wcta", "current_assets or current_liabilities not reported")
    else:
        terms["wcta"] = working_capital / total_assets

    current_assets = li.get(items, "current_assets")
    current_liabilities = li.get(items, "current_liabilities")
    if current_assets is None or current_liabilities is None:
        omit("clca", "current_assets or current_liabilities not reported")
    elif abs(current_assets) < 1e-9:
        omit("clca", "current_assets is zero")
    else:
        terms["clca"] = current_liabilities / current_assets

    if net_income is None:
        omit("nita", "net_income not reported")
        omit("intwo", "net_income not reported")
        omit("chin", "net_income not reported")
        return terms, omitted

    terms["nita"] = net_income / total_assets

    prior_net_income = li.get(prior_items or {}, "net_income")
    if prior_net_income is None:
        reason = (
            "prior-year net_income not on file; both of these terms compare year t "
            "against year t-1 and neither is substituted from the current year"
        )
        omit("intwo", reason)
        omit("chin", reason)
        return terms, omitted

    terms["intwo"] = 1.0 if (net_income < 0 and prior_net_income < 0) else 0.0
    denominator = abs(net_income) + abs(prior_net_income)
    if denominator < 1e-9:
        omit("chin", "net income is zero in both years; the scaled change is undefined")
    else:
        terms["chin"] = (net_income - prior_net_income) / denominator

    return terms, omitted


def compute_ohlson_o_score(
    *,
    items: dict[str, float],
    prior_items: dict[str, float] | None,
    settings: Settings,
    sector_class: SectorClass | None = None,
) -> OhlsonResult:
    """Ohlson's 1980 logit, or a refusal with the reason.

    Missing terms are omitted, never zeroed. A partial logit cannot be read
    directionally, so an omitted binary term reports probability bounds instead.
    """
    coefficients = settings.ohlson_coefficients()

    if sector_class is SectorClass.FINANCIAL:
        return OhlsonResult(
            o_score=None,
            probability=None,
            confidence=ResultConfidence.UNUSABLE,
            calculation_basis={
                "citation": OHLSON_CITATION,
                "refusal": (
                    "Ohlson's estimation sample was industrial firms; financial-sector "
                    "issuers were excluded. TLTA carries the largest positive coefficient "
                    "in the model, and for a bank a TLTA near 1 is the business model "
                    "rather than a distress signal. " + FINANCIAL_SECTOR_REFUSAL
                ),
            },
        )

    terms, omitted = _ohlson_terms(items, prior_items)
    if not terms:
        return OhlsonResult(
            o_score=None,
            probability=None,
            confidence=ResultConfidence.UNUSABLE,
            omitted=omitted,
            calculation_basis={
                "citation": OHLSON_CITATION,
                "reason": "No term could be computed from the supplied line items.",
            },
        )

    o_score = coefficients["intercept"]
    components: dict[str, dict[str, float]] = {}
    for term, value in terms.items():
        coefficient = coefficients[term]
        contribution = coefficient * value
        o_score += contribution
        components[term] = {
            "value": round(value, 6),
            "coefficient": coefficient,
            "contribution": round(contribution, 6),
        }

    omitted_binary = [entry["term"] for entry in omitted if entry["term"] in BINARY_TERMS]
    bounds: dict[str, float] | None = None
    if omitted_binary:
        swing = sum(abs(coefficients[term]) for term in omitted_binary)
        low = min(
            logistic(o_score), logistic(o_score + sum(coefficients[t] for t in omitted_binary))
        )
        high = max(
            logistic(o_score), logistic(o_score + sum(coefficients[t] for t in omitted_binary))
        )
        bounds = {
            "terms": sorted(omitted_binary),
            "probability_low": round(low, 6),
            "probability_high": round(high, 6),
            "o_score_swing": round(swing, 6),
        }

    complete = len(terms) == len(TERM_DEFINITIONS)
    probability = logistic(o_score)

    return OhlsonResult(
        o_score=round(o_score, 4),
        probability=round(probability, 6),
        confidence=ResultConfidence.COMPLETE if complete else ResultConfidence.PARTIAL,
        components=components,
        omitted=omitted,
        probability_bounds=bounds,
        calculation_basis={
            "citation": OHLSON_CITATION,
            "size_substitution": SIZE_SUBSTITUTION_NOTE,
            "formula": "O = intercept + " + " + ".join(f"{coefficients[t]}*{t}" for t in terms),
            "term_definitions": {t: TERM_DEFINITIONS[t] for t in terms},
            "term_meanings": {t: TERM_MEANINGS[t] for t in terms},
            "intercept": coefficients["intercept"],
            "probability_transform": "e^O / (1 + e^O)",
            "distress_cutoff_probability": settings.ohlson_distress_probability,
            "predicted_distress": probability > settings.ohlson_distress_probability,
            "terms_computed": len(terms),
            "terms_expected": len(TERM_DEFINITIONS),
            "prior_year_available": prior_items is not None,
            "partial_score_warning": (
                None
                if complete
                else (
                    "One or more terms were omitted. Unlike a linear discriminant "
                    "score, a partial logit does not shift the reported probability "
                    "in a direction a reader can reason about, because the logistic "
                    "transform is non-linear. Read this with omitted, and with "
                    "probability_bounds where the missing term was binary."
                )
            ),
        },
    )


def consensus_verdict(
    *,
    zone: Zone,
    ohlson_probability: float | None,
    settings: Settings,
) -> tuple[ConsensusVerdict, str]:
    """Reconcile the Altman zone with Ohlson's probability. Returns (verdict, reason)."""
    if ohlson_probability is None or zone is Zone.NOT_APPLICABLE:
        return (
            ConsensusVerdict.INDETERMINATE,
            "One of the two models produced no opinion, so there is nothing to "
            "reconcile. A verdict here would be a single model wearing the word "
            "'consensus'.",
        )

    low, high = settings.consensus_low_risk_probability, settings.consensus_high_risk_probability

    if zone is Zone.SAFE and ohlson_probability < low:
        return (
            ConsensusVerdict.LOW_RISK,
            f"Altman places the company in the SAFE zone and Ohlson puts the "
            f"probability of distress at {ohlson_probability:.1%}, below the {low:.0%} "
            "agreement threshold. Two independently estimated models concur.",
        )
    if zone is Zone.DISTRESS and ohlson_probability > high:
        return (
            ConsensusVerdict.HIGH_RISK,
            f"Altman places the company in the DISTRESS zone and Ohlson puts the "
            f"probability of distress at {ohlson_probability:.1%}, above the {high:.0%} "
            "agreement threshold. Two independently estimated models concur.",
        )
    return (
        ConsensusVerdict.MIXED_SIGNAL,
        f"Altman reports the {zone.value} zone while Ohlson puts the probability of "
        f"distress at {ohlson_probability:.1%}. That is not a bug to resolve by "
        "picking a favourite: a 1968 discriminant function fitted on 66 manufacturers "
        "and a 1980 logit fitted on 2,163 industrial firms are reading the same "
        "balance sheet differently, and which of them to believe depends on how much "
        "this company resembles each estimation sample.",
    )


def compute_risk_suite(
    *,
    items: dict[str, float],
    prior_items: dict[str, float] | None,
    sector_class: SectorClass,
    settings: Settings,
    model_override: AltmanModel | None = None,
    emerging_market_adjustment: bool = False,
) -> RiskSuiteResult:
    """The applicable Altman variant, the other two for comparison, and Ohlson."""
    altman = compute_z_score(
        items=items,
        sector_class=sector_class,
        settings=settings,
        model_override=model_override,
        emerging_market_adjustment=emerging_market_adjustment,
    )

    # Run all three so the UI can show what the wrong variant would have said.
    variants: dict[str, dict[str, Any]] = {}
    for variant in AltmanModel:
        run = compute_z_score(
            items=items, sector_class=sector_class, settings=settings, model_override=variant
        )
        variants[variant.value] = {
            "score": run.score,
            "zone": run.zone.value,
            "confidence": run.confidence.value,
            "applicable": variant is altman.model and model_override is None,
            "x4_equity_basis": run.calculation_basis.get("x4_equity_basis"),
            "cutoffs": run.calculation_basis.get("cutoffs"),
            "omitted_components": run.omitted_components,
        }

    ohlson = compute_ohlson_o_score(
        items=items, prior_items=prior_items, settings=settings, sector_class=sector_class
    )
    verdict, reason = consensus_verdict(
        zone=altman.zone, ohlson_probability=ohlson.probability, settings=settings
    )

    return RiskSuiteResult(
        altman=altman,
        ohlson=ohlson,
        consensus=verdict,
        variants=variants,
        calculation_basis={
            "consensus_rule": (
                "LOW_RISK requires the Altman zone to be SAFE and Ohlson's probability "
                f"below {settings.consensus_low_risk_probability:.0%}. HIGH_RISK requires "
                "the zone to be DISTRESS and Ohlson's probability above "
                f"{settings.consensus_high_risk_probability:.0%}. Everything else is "
                "MIXED_SIGNAL, and INDETERMINATE means one model declined to produce a "
                "number at all."
            ),
            "consensus_reason": reason,
            "consensus_thresholds": {
                "low_risk_below": settings.consensus_low_risk_probability,
                "high_risk_above": settings.consensus_high_risk_probability,
            },
            "why_two_models": (
                "Altman (1968) is a linear discriminant function fitted on 33 bankrupt "
                "and 33 solvent manufacturers. Ohlson (1980) is a logit fitted on 105 "
                "bankrupt and 2,058 solvent industrial firms and returns a probability "
                "rather than an index. Different form, sample and decade: when they "
                "agree that is evidence, and when they disagree that is also evidence."
            ),
        },
    )
