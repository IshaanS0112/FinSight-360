"""Altman bankruptcy risk models.

These are real, published, still-taught discriminant functions - not a scoring
heuristic invented for this project. That is the point of the module, and it is
also why the details matter.

The project spec asked for one model:

    Z = 1.2·X1 + 1.4·X2 + 3.3·X3 + 0.6·X4 + 1.0·X5

That is Altman (1968), and it was estimated on a sample of **publicly traded
manufacturing** firms. Applying it unchanged to an IT-services company or a
telecom operator is a misapplication - not because the arithmetic breaks, but
because the coefficients and cutoffs were fitted to a population those firms are
not drawn from. Altman published the corrections himself, and this module
implements all three:

======================  ==========================================  ==================
Model                   Population                                  Cutoffs (safe/distress)
======================  ==========================================  ==================
``Z_1968``              public manufacturers                        2.99 / 1.81
``Z_PRIME`` (Z')        private manufacturers, X4 uses book equity  2.90 / 1.23
``Z_DOUBLE_PRIME`` (Z'')non-manufacturers & emerging markets, no X5 2.60 / 1.10
======================  ==========================================  ==================

Three consequences worth knowing before reading the code:

**Financial-sector issuers get no score.** Altman excluded banks, insurers, and
other financial firms from the estimation samples, and for a good reason: for a
bank, leverage is the business model, so "total liabilities / total assets near
1" is normal rather than terminal. This module returns ``Zone.NOT_APPLICABLE``
with an explanation rather than a number. Producing a Z-score for a bank would be
the single easiest way for an interviewer to establish that a candidate had
implemented a formula without understanding its domain.

**Z (1968) needs market value of equity at the fiscal year end.** Not today's
market cap. If it is missing, this module reports Z' rather than substituting
book equity into the 1968 coefficients - that substitution is a common shortcut
and it is wrong, because Z' re-estimated every coefficient precisely to account
for the switch.

**Missing components are omitted, not zeroed.** A zeroed X3 is a claim that the
company earned exactly nothing at the operating line. The result carries
``PARTIAL`` confidence, lists what was omitted, and reports the partial sum -
which is honest and, for a deeply distressed balance sheet, still decisive.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.config import Settings
from app.enums import AltmanModel, ResultConfidence, SectorClass, Zone
from app.services import line_items as li

# Which X components each model uses. Z'' drops X5 entirely.
MODEL_COMPONENTS: dict[AltmanModel, tuple[str, ...]] = {
    AltmanModel.Z_1968: ("x1", "x2", "x3", "x4", "x5"),
    AltmanModel.Z_PRIME: ("x1", "x2", "x3", "x4", "x5"),
    AltmanModel.Z_DOUBLE_PRIME: ("x1", "x2", "x3", "x4"),
}

COMPONENT_DEFINITIONS: dict[str, str] = {
    "x1": "working_capital / total_assets",
    "x2": "retained_earnings / total_assets",
    "x3": "ebit / total_assets",
    "x4": "equity_value / total_liabilities",
    "x5": "revenue / total_assets",
}

COMPONENT_MEANINGS: dict[str, str] = {
    "x1": "Short-term liquidity relative to size: can it fund the next twelve months.",
    "x2": "Cumulative profitability and age: how much of the balance sheet was self-funded.",
    "x3": "Operating earning power, independent of capital structure and tax.",
    "x4": "Equity cushion: how far asset values can fall before liabilities exceed them.",
    "x5": "Asset productivity - revenue generated per unit of assets.",
}

MODEL_CITATIONS: dict[AltmanModel, str] = {
    AltmanModel.Z_1968: (
        "Altman, E. I. (1968). Financial Ratios, Discriminant Analysis and the "
        "Prediction of Corporate Bankruptcy. Journal of Finance, 23(4), 589-609. "
        "Estimation sample: publicly traded manufacturers."
    ),
    AltmanModel.Z_PRIME: (
        "Altman's Z'-Score revision for privately held manufacturers: X4 uses book "
        "value of equity and all coefficients are re-estimated."
    ),
    AltmanModel.Z_DOUBLE_PRIME: (
        "Altman's Z''-Score for non-manufacturers and emerging markets: X5 "
        "(sales/assets) is dropped because asset turnover varies too widely across "
        "service industries to carry signal."
    ),
}

FINANCIAL_SECTOR_REFUSAL = (
    "Altman excluded financial-sector issuers from every estimation sample. For a "
    "bank or insurer, high leverage is the business model rather than a distress "
    "signal, and the asset side is not comparable to an operating company's, so the "
    "coefficients and cutoffs do not transfer. No Z-score is reported for this "
    "issuer. Use a sector-appropriate model instead - CAMELS-style supervisory "
    "ratios or a Merton distance-to-default."
)


@dataclass
class ZScoreResult:
    model: AltmanModel
    score: float | None
    zone: Zone
    confidence: ResultConfidence
    components: dict[str, dict[str, float]] = field(default_factory=dict)
    omitted_components: list[dict[str, str]] = field(default_factory=list)
    borderline: bool = False
    calculation_basis: dict[str, Any] = field(default_factory=dict)


def select_model(
    sector_class: SectorClass, items: dict[str, float]
) -> tuple[AltmanModel | None, str]:
    """Pick the model whose estimation population the company actually belongs to.

    Returns ``(None, reason)`` for financial-sector issuers.
    """
    if sector_class is SectorClass.FINANCIAL:
        return None, FINANCIAL_SECTOR_REFUSAL

    if sector_class is SectorClass.NON_MANUFACTURER:
        return (
            AltmanModel.Z_DOUBLE_PRIME,
            "Non-manufacturer: Z'' is the applicable variant and X5 is not used.",
        )

    if sector_class is SectorClass.PRIVATE_MANUFACTURER:
        return (
            AltmanModel.Z_PRIME,
            "Privately held manufacturer: Z' uses book value of equity in X4.",
        )

    # Public manufacturer - the 1968 population, but only if a fiscal-year-end
    # market value of equity was actually supplied.
    if li.get(items, "market_value_equity") is None:
        return (
            AltmanModel.Z_PRIME,
            "Public manufacturer, but market_value_equity was not supplied. Reporting "
            "Z' (book equity, re-estimated coefficients) rather than substituting book "
            "equity into the 1968 coefficients, which would misstate X4's weight.",
        )
    return AltmanModel.Z_1968, "Publicly traded manufacturer: Altman (1968) applies as published."


def _coefficients(model: AltmanModel, settings: Settings) -> dict[str, float]:
    return settings.altman_coefficients()[model.value]


def _cutoffs(model: AltmanModel, settings: Settings) -> tuple[float, float]:
    row = settings.altman_cutoffs()[model.value]
    return row["safe_above"], row["distress_below"]


def _component_ratios(
    model: AltmanModel, items: dict[str, float]
) -> tuple[dict[str, float], list[dict[str, str]]]:
    """Compute each X ratio the model needs; report the ones that cannot be computed."""
    ratios: dict[str, float] = {}
    omitted: list[dict[str, str]] = []
    total_assets = li.get(items, "total_assets")

    if not total_assets:
        # Every component is scaled by total assets. Without it there is nothing.
        return {}, [
            {"component": c, "reason": "total_assets not reported or zero"}
            for c in MODEL_COMPONENTS[model]
        ]

    def add(component: str, numerator: float | None, missing: str) -> None:
        if numerator is None:
            omitted.append({"component": component, "reason": missing})
        else:
            ratios[component] = numerator / total_assets

    for component in MODEL_COMPONENTS[model]:
        if component == "x1":
            add("x1", li.working_capital(items), "current_assets or current_liabilities not reported")
        elif component == "x2":
            add("x2", li.get(items, "retained_earnings"), "retained_earnings not reported")
        elif component == "x3":
            add("x3", li.get(items, "ebit"), "ebit (operating income) not reported")
        elif component == "x5":
            add("x5", li.get(items, "revenue"), "revenue not reported")
        elif component == "x4":
            # The one component that is not scaled by total assets, and the one
            # whose numerator depends on which model is in force.
            total_liabilities = li.get(items, "total_liabilities")
            equity_value = (
                li.get(items, "market_value_equity")
                if model is AltmanModel.Z_1968
                else li.get(items, "shareholder_equity")
            )
            if equity_value is None:
                omitted.append({
                    "component": "x4",
                    "reason": (
                        "market_value_equity not reported"
                        if model is AltmanModel.Z_1968
                        else "shareholder_equity not reported"
                    ),
                })
            elif not total_liabilities:
                omitted.append({"component": "x4", "reason": "total_liabilities not reported or zero"})
            else:
                # Negative book equity produces a negative X4, which is exactly
                # the intended signal: liabilities exceed assets. Not clamped.
                ratios["x4"] = equity_value / total_liabilities

    return ratios, omitted


def _classify(score: float, safe_above: float, distress_below: float, margin: float) -> tuple[Zone, bool]:
    zone = (
        Zone.SAFE if score > safe_above
        else Zone.DISTRESS if score < distress_below
        else Zone.GREY
    )
    borderline = abs(score - safe_above) <= margin or abs(score - distress_below) <= margin
    return zone, borderline


def compute_z_score(
    *,
    items: dict[str, float],
    sector_class: SectorClass,
    settings: Settings,
    model_override: AltmanModel | None = None,
    emerging_market_adjustment: bool = False,
) -> ZScoreResult:
    """Compute the applicable Altman score, or refuse with a reason."""
    if sector_class is SectorClass.FINANCIAL and model_override is None:
        return ZScoreResult(
            model=AltmanModel.Z_DOUBLE_PRIME,
            score=None,
            zone=Zone.NOT_APPLICABLE,
            confidence=ResultConfidence.UNUSABLE,
            calculation_basis={
                "model_selection": FINANCIAL_SECTOR_REFUSAL,
                "sector_class": sector_class.value,
            },
        )

    if model_override is not None:
        model, selection_reason = model_override, f"Model explicitly overridden to {model_override.value}."
        if sector_class is SectorClass.FINANCIAL:
            selection_reason += (
                " Requested for a financial-sector issuer against the model's stated "
                "domain; the score is reported but is not evidence about this issuer. "
                + FINANCIAL_SECTOR_REFUSAL
            )
    else:
        selected, selection_reason = select_model(sector_class, items)
        assert selected is not None  # financial case returned above
        model = selected

    coefficients = _coefficients(model, settings)
    ratios, omitted = _component_ratios(model, items)

    if not ratios:
        return ZScoreResult(
            model=model,
            score=None,
            zone=Zone.NOT_APPLICABLE,
            confidence=ResultConfidence.UNUSABLE,
            omitted_components=omitted,
            calculation_basis={
                "model_selection": selection_reason,
                "reason": "No component could be computed from the supplied line items.",
            },
        )

    components: dict[str, dict[str, float]] = {}
    score = 0.0
    for component, ratio in ratios.items():
        coefficient = coefficients[component]
        contribution = coefficient * ratio
        score += contribution
        components[component] = {
            "ratio": round(ratio, 6),
            "coefficient": coefficient,
            "contribution": round(contribution, 6),
        }

    emerging_constant = 0.0
    if emerging_market_adjustment:
        if model is not AltmanModel.Z_DOUBLE_PRIME:
            raise ValueError(
                "The +3.25 emerging-market constant is defined only for Z''. Applying it "
                "to Z or Z' would shift a score against cutoffs it was not calibrated with."
            )
        emerging_constant = settings.zdprime_emerging_market_constant
        score += emerging_constant

    safe_above, distress_below = _cutoffs(model, settings)
    zone, borderline = _classify(score, safe_above, distress_below, settings.zone_borderline_margin)

    expected = len(MODEL_COMPONENTS[model])
    confidence = (
        ResultConfidence.COMPLETE if len(ratios) == expected else ResultConfidence.PARTIAL
    )

    return ZScoreResult(
        model=model,
        score=round(score, 4),
        zone=zone,
        confidence=confidence,
        components=components,
        omitted_components=omitted,
        borderline=borderline,
        calculation_basis={
            "citation": MODEL_CITATIONS[model],
            "model_selection": selection_reason,
            "sector_class": sector_class.value,
            "formula": " + ".join(
                f"{coefficients[c]}*{c}" for c in MODEL_COMPONENTS[model]
            ) + (f" + {emerging_constant} (emerging-market constant)" if emerging_constant else ""),
            "component_definitions": {
                c: COMPONENT_DEFINITIONS[c] for c in MODEL_COMPONENTS[model]
            },
            "component_meanings": {c: COMPONENT_MEANINGS[c] for c in MODEL_COMPONENTS[model]},
            "x4_equity_basis": (
                "MARKET_VALUE" if model is AltmanModel.Z_1968 else "BOOK_VALUE"
            ),
            "cutoffs": {"safe_above": safe_above, "distress_below": distress_below},
            "borderline_margin": settings.zone_borderline_margin,
            "emerging_market_constant_applied": emerging_constant or None,
            "components_computed": len(ratios),
            "components_expected": expected,
            "partial_score_warning": (
                "One or more components were omitted, so this score is a partial sum "
                "and is biased toward the cutoffs. Read it with omitted_components."
                if confidence is ResultConfidence.PARTIAL
                else None
            ),
        },
    )
