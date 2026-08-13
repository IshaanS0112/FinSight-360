"""Altman models: published coefficients, correct variant, honest degradation.

The two validation tests at the top are the ones the README points at. Everything
below them exists because a formula implemented without its domain is a liability,
not an asset.
"""

from __future__ import annotations

import pytest

from app.enums import AltmanModel, ResultConfidence, SectorClass, Zone
from app.services.altman_zscore import (
    FINANCIAL_SECTOR_REFUSAL,
    MODEL_COMPONENTS,
    compute_z_score,
    select_model,
)


# --- Validation against companies with known outcomes ------------------------

def test_caterpillar_known_healthy_lands_in_safe_zone(cat_items, caterpillar, settings):
    """Known-healthy public manufacturer, the exact 1968 estimation population."""
    result = compute_z_score(
        items=cat_items, sector_class=SectorClass.PUBLIC_MANUFACTURER, settings=settings
    )
    assert result.model is AltmanModel.Z_1968
    assert result.confidence is ResultConfidence.COMPLETE
    assert result.zone is Zone.SAFE
    assert result.zone.value == caterpillar["expected"]["zone"]
    # Hand-computed: 0.18336 + 0.94676 + 0.49150 + 1.56023 + 0.73845
    assert result.score == pytest.approx(3.9203, abs=1e-4)
    assert not result.borderline, "well clear of the 2.99 cutoff, not a marginal call"


def test_vodafone_idea_known_distressed_lands_in_distress_zone(vi_items, vodafone_idea, settings):
    """Known-distressed case: liabilities exceed assets by 1,041,668m INR.

    The verdict is driven by X1 (working capital is -412,315) and X2 (accumulated
    deficit of -2,339,687 against total assets of 1,849,977). Both are balance-sheet
    facts, not estimates.
    """
    result = compute_z_score(
        items=vi_items, sector_class=SectorClass.NON_MANUFACTURER, settings=settings
    )
    assert result.model is AltmanModel.Z_DOUBLE_PRIME
    assert result.zone is Zone.DISTRESS
    assert result.zone.value == vodafone_idea["expected"]["zone"]
    assert result.score == pytest.approx(-5.9633, abs=1e-4)
    assert result.components["x2"]["contribution"] < 0


def test_infosys_known_healthy_non_manufacturer_lands_in_safe_zone(infy_items, infosys, settings):
    result = compute_z_score(
        items=infy_items, sector_class=SectorClass.NON_MANUFACTURER, settings=settings
    )
    assert result.model is AltmanModel.Z_DOUBLE_PRIME
    assert result.confidence is ResultConfidence.COMPLETE
    assert result.zone is Zone.SAFE
    assert result.zone.value == infosys["expected"]["zone"]
    assert result.score == pytest.approx(8.6494, abs=1e-4)


def test_vodafone_idea_partial_but_decisive(vi_items, settings):
    """EBIT is genuinely unavailable, so X3 is omitted rather than invented.

    The result is labelled PARTIAL, names the missing component, and carries a
    warning that a partial sum is biased toward the cutoffs - and the four
    remaining terms still put the company well below the 1.10 distress line, so
    the verdict does not depend on the missing term.
    """
    result = compute_z_score(
        items=vi_items, sector_class=SectorClass.NON_MANUFACTURER, settings=settings
    )
    assert result.confidence is ResultConfidence.PARTIAL
    assert [c["component"] for c in result.omitted_components] == ["x3"]
    assert "x3" not in result.components
    assert result.calculation_basis["partial_score_warning"]
    assert result.score < settings.zdprime_distress_below


# --- Published coefficients --------------------------------------------------

@pytest.mark.parametrize(
    "model,expected",
    [
        (AltmanModel.Z_1968, {"x1": 1.2, "x2": 1.4, "x3": 3.3, "x4": 0.6, "x5": 1.0}),
        (AltmanModel.Z_PRIME, {"x1": 0.717, "x2": 0.847, "x3": 3.107, "x4": 0.420, "x5": 0.998}),
        (AltmanModel.Z_DOUBLE_PRIME, {"x1": 6.56, "x2": 3.26, "x3": 6.72, "x4": 1.05}),
    ],
)
def test_coefficients_are_the_published_ones(model, expected, settings):
    assert settings.altman_coefficients()[model.value] == expected


@pytest.mark.parametrize(
    "model,safe,distress",
    [
        (AltmanModel.Z_1968, 2.99, 1.81),
        (AltmanModel.Z_PRIME, 2.90, 1.23),
        (AltmanModel.Z_DOUBLE_PRIME, 2.60, 1.10),
    ],
)
def test_cutoffs_are_the_published_ones(model, safe, distress, settings):
    cutoffs = settings.altman_cutoffs()[model.value]
    assert (cutoffs["safe_above"], cutoffs["distress_below"]) == (safe, distress)


def test_z_double_prime_drops_x5_entirely():
    """Not an oversight in the config: Z'' has four terms by construction."""
    assert "x5" not in MODEL_COMPONENTS[AltmanModel.Z_DOUBLE_PRIME]
    assert len(MODEL_COMPONENTS[AltmanModel.Z_DOUBLE_PRIME]) == 4


def test_score_is_the_sum_of_its_contributions(cat_items, settings):
    result = compute_z_score(
        items=cat_items, sector_class=SectorClass.PUBLIC_MANUFACTURER, settings=settings
    )
    total = sum(c["contribution"] for c in result.components.values())
    assert result.score == pytest.approx(total, abs=1e-4)


# --- Model selection ---------------------------------------------------------

def test_non_manufacturer_never_gets_the_1968_model(infy_items, settings):
    """The correction that matters.

    Infosys has a market value of equity available in principle, so a naive
    implementation would happily run the 1968 model on an IT services company.
    Selection is by sector class, not by which inputs happen to be present.
    """
    model, reason = select_model(SectorClass.NON_MANUFACTURER, {**infy_items, "market_value_equity": 1})
    assert model is AltmanModel.Z_DOUBLE_PRIME
    assert "Non-manufacturer" in reason


def test_public_manufacturer_without_market_cap_falls_back_to_z_prime(cat_items, settings):
    """Not to Z-1968-with-book-equity, which is the common wrong shortcut."""
    items = {k: v for k, v in cat_items.items() if k != "market_value_equity"}
    result = compute_z_score(
        items=items, sector_class=SectorClass.PUBLIC_MANUFACTURER, settings=settings
    )
    assert result.model is AltmanModel.Z_PRIME
    assert result.calculation_basis["x4_equity_basis"] == "BOOK_VALUE"
    assert "would misstate X4" in result.calculation_basis["model_selection"]
    # X4 now uses book equity 19,494 rather than market value 177,528.
    assert result.components["x4"]["ratio"] == pytest.approx(19494 / 68270, abs=1e-6)


def test_private_manufacturer_gets_z_prime(cat_items, settings):
    result = compute_z_score(
        items=cat_items, sector_class=SectorClass.PRIVATE_MANUFACTURER, settings=settings
    )
    assert result.model is AltmanModel.Z_PRIME
    assert result.calculation_basis["x4_equity_basis"] == "BOOK_VALUE"


def test_choosing_the_wrong_variant_changes_the_verdict_materially(cat_items, settings):
    """Why the variant is not a cosmetic detail.

    Scoring Caterpillar with Z'' instead of Z (1968) moves the score by ~0.59 AND
    moves the cutoff it is measured against by 0.39, so the reported headroom over
    the distress boundary roughly doubles. For a company nearer a cutoff than
    Caterpillar is, that is the difference between GREY and SAFE - which is why
    the variant is selected from the sector class rather than left to the caller.
    """
    correct = compute_z_score(
        items=cat_items, sector_class=SectorClass.PUBLIC_MANUFACTURER, settings=settings
    )
    wrong = compute_z_score(
        items=cat_items,
        sector_class=SectorClass.PUBLIC_MANUFACTURER,
        settings=settings,
        model_override=AltmanModel.Z_DOUBLE_PRIME,
    )
    assert abs(correct.score - wrong.score) > 0.5
    correct_headroom = correct.score - correct.calculation_basis["cutoffs"]["safe_above"]
    wrong_headroom = wrong.score - wrong.calculation_basis["cutoffs"]["safe_above"]
    assert wrong_headroom > correct_headroom * 2, (
        "the misapplied model reports roughly double the safety margin"
    )
    assert "explicitly overridden" in wrong.calculation_basis["model_selection"]


def test_misapplied_1968_model_can_flip_a_verdict(settings):
    """Constructed to show the failure mode the sector guard prevents.

    A non-manufacturer scoring 2.74 under Z'' (SAFE, above the 2.60 cutoff) scores
    1.36 under the 1968 coefficients - DISTRESS, below the 1.81 cutoff. Same balance
    sheet, opposite verdict, purely from applying coefficients fitted to a different
    population against cutoffs calibrated for it.
    """
    items = {
        "total_assets": 1000.0,
        "current_assets": 400.0,
        "current_liabilities": 250.0,
        "total_liabilities": 600.0,
        "shareholder_equity": 400.0,
        "market_value_equity": 400.0,
        "retained_earnings": 200.0,
        "ebit": 60.0,
        "revenue": 300.0,
    }
    correct = compute_z_score(
        items=items, sector_class=SectorClass.NON_MANUFACTURER, settings=settings
    )
    misapplied = compute_z_score(
        items=items,
        sector_class=SectorClass.NON_MANUFACTURER,
        settings=settings,
        model_override=AltmanModel.Z_1968,
    )
    assert correct.model is AltmanModel.Z_DOUBLE_PRIME
    assert correct.zone is Zone.SAFE
    assert misapplied.zone is Zone.DISTRESS


# --- The refusal -------------------------------------------------------------

def test_financial_sector_issuer_gets_no_score(infy_items, settings):
    """Altman excluded financial firms from every estimation sample."""
    result = compute_z_score(
        items=infy_items, sector_class=SectorClass.FINANCIAL, settings=settings
    )
    assert result.score is None
    assert result.zone is Zone.NOT_APPLICABLE
    assert result.confidence is ResultConfidence.UNUSABLE
    assert result.calculation_basis["model_selection"] == FINANCIAL_SECTOR_REFUSAL


def test_financial_sector_override_still_carries_the_warning(infy_items, settings):
    """A user can force a score, but the result says it is not evidence."""
    result = compute_z_score(
        items=infy_items,
        sector_class=SectorClass.FINANCIAL,
        settings=settings,
        model_override=AltmanModel.Z_DOUBLE_PRIME,
    )
    assert result.score is not None
    assert "not evidence about this issuer" in result.calculation_basis["model_selection"]


# --- Edge cases --------------------------------------------------------------

def test_no_total_assets_means_no_score(settings):
    result = compute_z_score(
        items={"revenue": 100.0}, sector_class=SectorClass.NON_MANUFACTURER, settings=settings
    )
    assert result.score is None
    assert result.confidence is ResultConfidence.UNUSABLE
    assert {c["component"] for c in result.omitted_components} == {"x1", "x2", "x3", "x4"}


def test_negative_x4_is_not_clamped(vi_items, settings):
    """Negative book equity is the signal, so it must survive into the score."""
    result = compute_z_score(
        items=vi_items, sector_class=SectorClass.NON_MANUFACTURER, settings=settings
    )
    assert result.components["x4"]["ratio"] < 0
    assert result.components["x4"]["contribution"] < 0


def test_emerging_market_constant_only_applies_to_z_double_prime(cat_items, settings):
    with pytest.raises(ValueError, match="only for Z''"):
        compute_z_score(
            items=cat_items,
            sector_class=SectorClass.PUBLIC_MANUFACTURER,
            settings=settings,
            emerging_market_adjustment=True,
        )


def test_emerging_market_constant_shifts_the_score_by_exactly_325(vi_items, settings):
    plain = compute_z_score(
        items=vi_items, sector_class=SectorClass.NON_MANUFACTURER, settings=settings
    )
    adjusted = compute_z_score(
        items=vi_items,
        sector_class=SectorClass.NON_MANUFACTURER,
        settings=settings,
        emerging_market_adjustment=True,
    )
    assert adjusted.score == pytest.approx(plain.score + 3.25, abs=1e-4)
    assert adjusted.calculation_basis["emerging_market_constant_applied"] == 3.25
    # Still distress: a +3.25 shift does not rescue a -5.96 score.
    assert adjusted.zone is Zone.DISTRESS


def test_borderline_flag_fires_near_a_cutoff(settings):
    """Constructed so X2 alone lands the Z'' score just above the 2.60 line."""
    items = {"total_assets": 100.0, "retained_earnings": 100.0 * 2.70 / 3.26}
    result = compute_z_score(
        items=items, sector_class=SectorClass.NON_MANUFACTURER, settings=settings
    )
    assert result.score == pytest.approx(2.70, abs=1e-3)
    assert result.zone is Zone.SAFE
    assert result.borderline, "2.70 is within 0.15 of the 2.60 cutoff"
