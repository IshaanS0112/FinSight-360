"""Ohlson's O-Score, the Altman variant sweep, and the consensus verdict.

# roadmap: v2-03-bankruptcy-suite

The point of this module is not a second number. It is what happens when the two
models disagree, so most of these tests are about the verdict rather than the
arithmetic - and the arithmetic tests are hand-computed term by term, because a
coefficient typo in a logit is invisible in the output.
"""

from __future__ import annotations

import math

import pytest

from app.enums import AltmanModel, ConsensusVerdict, ResultConfidence, SectorClass, Zone
from app.services.bankruptcy_risk import (
    SIZE_SUBSTITUTION_NOTE,
    compute_ohlson_o_score,
    compute_risk_suite,
    consensus_verdict,
    logistic,
)

CAT_2024 = {
    "total_assets": 87764.0,
    "total_liabilities": 68270.0,
    "current_assets": 45682.0,
    "current_liabilities": 32272.0,
    "shareholder_equity": 19494.0,
    "retained_earnings": 59352.0,
    "net_income": 10792.0,
    "depreciation_amortization": 2153.0,
    "ebit": 13072.0,
    "revenue": 64809.0,
    "market_value_equity": 177528.0,
}
CAT_2023 = {"total_assets": 87476.0, "net_income": 10335.0}


def omitted_reason(result, term: str) -> str:
    for entry in result.omitted:
        if entry["term"] == term:
            return entry["reason"]
    raise AssertionError(f"{term} was computed, expected it to be omitted")


# --- Arithmetic ---------------------------------------------------------------


def test_ohlson_reproduces_a_hand_computation_term_by_term(settings):
    """Every term checked against the published coefficients, computed by hand.

    A wrong coefficient in a logit does not look wrong in the output: it shifts a
    probability by a few points and every value stays inside [0, 1]. The only way
    to catch it is to check the terms, not the total.
    """
    result = compute_ohlson_o_score(items=CAT_2024, prior_items=CAT_2023, settings=settings)
    assert result.confidence is ResultConfidence.COMPLETE

    components = result.components
    assert components["size"]["value"] == pytest.approx(math.log(87764), abs=1e-6)
    assert components["tlta"]["value"] == pytest.approx(68270 / 87764, abs=1e-6)
    assert components["wcta"]["value"] == pytest.approx((45682 - 32272) / 87764, abs=1e-6)
    assert components["clca"]["value"] == pytest.approx(32272 / 45682, abs=1e-6)
    assert components["oeneg"]["value"] == 0.0, "liabilities do not exceed assets"
    assert components["nita"]["value"] == pytest.approx(10792 / 87764, abs=1e-6)
    assert components["futl"]["value"] == pytest.approx((10792 + 2153) / 68270, abs=1e-6)
    assert components["intwo"]["value"] == 0.0, "profitable in both years"
    assert components["chin"]["value"] == pytest.approx(
        (10792 - 10335) / (abs(10792) + abs(10335)), abs=1e-6
    )

    expected = settings.ohlson_intercept + sum(
        c["coefficient"] * c["value"] for c in components.values()
    )
    assert result.o_score == pytest.approx(expected, abs=1e-4)
    assert result.o_score == pytest.approx(-2.0767, abs=1e-4)
    assert result.probability == pytest.approx(0.1114, abs=1e-4)


def test_the_probability_transform_is_the_published_one_and_does_not_overflow():
    """``e^O/(1+e^O)`` overflows for O around -750 if written literally."""
    assert logistic(0.0) == 0.5
    assert logistic(2.0) == pytest.approx(math.exp(2) / (1 + math.exp(2)), abs=1e-12)
    assert logistic(-2.0) == pytest.approx(math.exp(-2) / (1 + math.exp(-2)), abs=1e-12)
    assert logistic(-900.0) == pytest.approx(0.0, abs=1e-12)
    assert logistic(900.0) == pytest.approx(1.0, abs=1e-12)


def test_a_distressed_balance_sheet_scores_a_high_probability(settings, vi_items):
    """Vodafone Idea: liabilities exceed assets outright, so OENEG fires."""
    result = compute_ohlson_o_score(
        items=vi_items, prior_items={"net_income": -312387.0}, settings=settings
    )
    assert result.components["oeneg"]["value"] == 1.0
    assert result.components["intwo"]["value"] == 1.0, "loss-making in both years"
    assert result.probability > settings.ohlson_distress_probability


# --- Honesty about the model --------------------------------------------------


def test_the_size_substitution_is_recorded_on_every_result(settings):
    """The deviation from the 1980 paper must travel with the number, not sit in a doc."""
    result = compute_ohlson_o_score(items=CAT_2024, prior_items=CAT_2023, settings=settings)
    note = result.calculation_basis["size_substitution"]
    assert note == SIZE_SUBSTITUTION_NOTE
    assert "GNP price-level index" in note
    assert "ln(total_assets)" in note


def test_a_financial_issuer_is_refused_by_ohlson_too(settings):
    """Consistency with the Altman module, and for the same reason.

    TLTA carries the largest positive coefficient in the model. For a bank, a
    TLTA near 1 is the business model.
    """
    result = compute_ohlson_o_score(
        items=CAT_2024,
        prior_items=CAT_2023,
        settings=settings,
        sector_class=SectorClass.FINANCIAL,
    )
    assert result.o_score is None
    assert result.probability is None
    assert result.confidence is ResultConfidence.UNUSABLE
    assert "excluded" in result.calculation_basis["refusal"]


def test_a_missing_prior_year_omits_both_year_on_year_terms(settings):
    """INTWO and CHIN are never substituted from the current year."""
    result = compute_ohlson_o_score(items=CAT_2024, prior_items=None, settings=settings)
    assert result.confidence is ResultConfidence.PARTIAL
    assert "intwo" not in result.components
    assert "chin" not in result.components
    assert "neither is substituted from the current year" in omitted_reason(result, "chin")


def test_an_omitted_binary_term_is_reported_as_a_probability_range(settings):
    """A partial logit cannot be read directionally, so the bound is given instead.

    Where the missing term can only be 0 or 1, the reported probability has two
    possible values and both are stated - which is strictly more information than
    an omission notice.
    """
    result = compute_ohlson_o_score(items=CAT_2024, prior_items=None, settings=settings)
    bounds = result.probability_bounds
    assert bounds is not None
    assert bounds["terms"] == ["intwo"]
    assert bounds["probability_low"] <= result.probability <= bounds["probability_high"]
    assert bounds["o_score_swing"] == pytest.approx(abs(settings.ohlson_intwo), abs=1e-9)
    assert "non-linear" in result.calculation_basis["partial_score_warning"]


def test_no_line_items_is_unusable_not_a_confident_fifty_percent(settings):
    """``logistic(intercept)`` is 0.21, which is a plausible-looking lie."""
    result = compute_ohlson_o_score(items={}, prior_items=None, settings=settings)
    assert result.o_score is None
    assert result.probability is None
    assert result.confidence is ResultConfidence.UNUSABLE


# --- The consensus verdict: the actual subject of this item --------------------


def test_agreement_on_safety_is_low_risk(settings):
    verdict, reason = consensus_verdict(zone=Zone.SAFE, ohlson_probability=0.05, settings=settings)
    assert verdict is ConsensusVerdict.LOW_RISK
    assert "concur" in reason


def test_agreement_on_distress_is_high_risk(settings):
    verdict, reason = consensus_verdict(
        zone=Zone.DISTRESS, ohlson_probability=0.91, settings=settings
    )
    assert verdict is ConsensusVerdict.HIGH_RISK
    assert "concur" in reason


def test_disagreement_is_surfaced_not_resolved(settings):
    """The load-bearing test for this whole roadmap item.

    Altman says safe, Ohlson says four-in-five chance of distress. A tool that
    averaged these, or picked the one it liked, would be destroying the most
    useful output in the analysis.
    """
    verdict, reason = consensus_verdict(zone=Zone.SAFE, ohlson_probability=0.80, settings=settings)
    assert verdict is ConsensusVerdict.MIXED_SIGNAL
    assert "not a bug to resolve by picking a favourite" in reason


def test_a_safe_zone_with_a_middling_probability_is_still_mixed(settings):
    """LOW_RISK requires Ohlson comfortably below its own cutoff, not merely below it."""
    verdict, _ = consensus_verdict(zone=Zone.SAFE, ohlson_probability=0.40, settings=settings)
    assert verdict is ConsensusVerdict.MIXED_SIGNAL
    assert settings.ohlson_distress_probability > 0.40


def test_the_grey_zone_can_never_reach_agreement(settings):
    for probability in (0.01, 0.5, 0.99):
        verdict, _ = consensus_verdict(
            zone=Zone.GREY, ohlson_probability=probability, settings=settings
        )
        assert verdict is ConsensusVerdict.MIXED_SIGNAL


def test_one_silent_model_is_indeterminate_not_a_verdict(settings):
    """A bank gets no Altman zone, so "consensus" would mean one model alone."""
    verdict, reason = consensus_verdict(
        zone=Zone.NOT_APPLICABLE, ohlson_probability=0.4, settings=settings
    )
    assert verdict is ConsensusVerdict.INDETERMINATE
    assert "single model wearing the word" in reason

    verdict, _ = consensus_verdict(zone=Zone.SAFE, ohlson_probability=None, settings=settings)
    assert verdict is ConsensusVerdict.INDETERMINATE


# --- The variant sweep --------------------------------------------------------


def test_the_suite_runs_every_altman_variant_and_marks_the_applicable_one(settings):
    """Showing what the wrong variant would have said is the cheapest way to make
    the project's central argument concrete."""
    suite = compute_risk_suite(
        items=CAT_2024,
        prior_items=CAT_2023,
        sector_class=SectorClass.PUBLIC_MANUFACTURER,
        settings=settings,
    )
    assert set(suite.variants) == {m.value for m in AltmanModel}
    applicable = [k for k, v in suite.variants.items() if v["applicable"]]
    assert applicable == ["Z_1968"]
    assert suite.variants["Z_1968"]["score"] == pytest.approx(3.9203, abs=1e-4)
    assert suite.variants["Z_1968"]["x4_equity_basis"] == "MARKET_VALUE"
    assert suite.variants["Z_PRIME"]["x4_equity_basis"] == "BOOK_VALUE"


def test_caterpillar_resolves_to_low_risk_on_real_filing_data(settings):
    suite = compute_risk_suite(
        items=CAT_2024,
        prior_items=CAT_2023,
        sector_class=SectorClass.PUBLIC_MANUFACTURER,
        settings=settings,
    )
    assert suite.altman.zone is Zone.SAFE
    assert suite.ohlson.probability < settings.consensus_low_risk_probability
    assert suite.consensus is ConsensusVerdict.LOW_RISK


def test_the_variant_sweep_shows_the_wrong_model_reaching_a_different_zone(settings):
    """Caterpillar is SAFE under the 1968 model it belongs to and GREY under Z'.

    Same balance sheet, same day, different published coefficients - which is the
    entire reason selection is by sector class rather than by the caller.
    """
    suite = compute_risk_suite(
        items=CAT_2024,
        prior_items=CAT_2023,
        sector_class=SectorClass.PUBLIC_MANUFACTURER,
        settings=settings,
    )
    assert suite.variants["Z_1968"]["zone"] == "SAFE"
    assert suite.variants["Z_PRIME"]["zone"] == "GREY"
