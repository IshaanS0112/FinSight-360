"""Piotroski F-Score and Beneish M-Score.

# roadmap: v2-04-earnings-quality

Two models, two opposite refusal policies, and the difference between them is
the most interesting thing in the module. Piotroski reports a partial score
without a band; Beneish reports nothing at all. Both behaviours are tested here
because both are deliberate.
"""

from __future__ import annotations

import pytest

from app.enums import EarningsQualityBand, ResultConfidence
from app.services.earnings_quality import (
    M_SCORE_DEFINITIONS,
    compute_beneish_m_score,
    compute_piotroski_f_score,
)

# Caterpillar Inc., FY2024 and FY2023, from the SEC XBRL extraction of the 10-K.
CAT_2024 = {
    "total_assets": 87764.0,
    "current_assets": 45682.0,
    "current_liabilities": 32272.0,
    "total_liabilities": 68270.0,
    "net_income": 10792.0,
    "revenue": 64809.0,
    "cogs": 40199.0,
    "operating_cash_flow": 12035.0,
    "long_term_debt": 27351.0,
    "shares_outstanding": 477.9,
    "accounts_receivable": 9282.0,
    "ppe_net": 13361.0,
    "depreciation_amortization": 2153.0,
    "sga_expense": 6667.0,
    "income_continuing_ops": 10788.0,
}
CAT_2023 = {
    "total_assets": 87476.0,
    "current_assets": 46949.0,
    "current_liabilities": 34728.0,
    "total_liabilities": 67973.0,
    "net_income": 10335.0,
    "revenue": 67060.0,
    "cogs": 42767.0,
    "operating_cash_flow": 12885.0,
    "long_term_debt": 24472.0,
    "shares_outstanding": 499.4,
    "accounts_receivable": 9310.0,
    "ppe_net": 12680.0,
    "depreciation_amortization": 2144.0,
    "sga_expense": 6371.0,
    "income_continuing_ops": 10332.0,
}


def status_of(result, test: str) -> str:
    return result.components[test]["status"]


# --- Piotroski ----------------------------------------------------------------


def test_caterpillar_scores_seven_of_nine_with_the_two_failures_named():
    """A real two-year filing, every test evaluated, and the misses are explicable.

    Long-term debt rose from 24,472 to 27,351 and revenue fell from 67,060 to
    64,809 against a flat asset base. Those are the two failing tests, and they
    are exactly the two a reader of the 10-K would predict.
    """
    result = compute_piotroski_f_score(CAT_2024, CAT_2023)
    assert result.confidence is ResultConfidence.COMPLETE
    assert result.tests_evaluated == 9
    assert result.score == 7
    assert result.band is EarningsQualityBand.MIXED
    assert status_of(result, "leverage_falling") == "FAIL"
    assert status_of(result, "turnover_rising") == "FAIL"
    assert status_of(result, "accruals") == "PASS", "operating cash flow exceeds net income"


def test_a_single_fiscal_year_evaluates_only_the_level_tests():
    """Six of the nine tests compare year t to year t-1 and simply cannot run.

    They are reported as NOT_EVALUATED with a reason each, not as failures. A
    company does not have weak fundamentals because you uploaded one year.
    """
    result = compute_piotroski_f_score(CAT_2024, None)
    assert result.confidence is ResultConfidence.PARTIAL
    assert result.tests_evaluated == 3
    evaluated = {k for k, v in result.components.items() if v["status"] != "NOT_EVALUATED"}
    assert evaluated == {"roa_positive", "cfo_positive", "accruals"}
    assert result.score == 3


def test_a_partial_score_is_reported_without_a_band():
    """The sharpest Piotroski judgement in the module.

    Piotroski's 8-9 / 5-7 / 0-4 reading is calibrated on all nine tests. Scoring
    3-out-of-3 against a nine-point band would report a strong company as weak.
    """
    result = compute_piotroski_f_score(CAT_2024, None)
    assert result.score == 3
    assert result.band is None
    assert "calibrated on the full nine" in result.calculation_basis["band_withheld_reason"]


def test_the_roa_denominator_deviation_travels_with_the_result():
    """Piotroski's paper uses beginning-of-year assets; this uses ending."""
    result = compute_piotroski_f_score(CAT_2024, CAT_2023)
    note = result.calculation_basis["roa_basis"]
    assert "BEGINNING-of-year" in note
    assert "documented deviation" in note


def test_a_share_issue_fails_the_dilution_test():
    result = compute_piotroski_f_score({**CAT_2024, "shares_outstanding": 520.0}, CAT_2023)
    assert status_of(result, "no_dilution") == "FAIL"


def test_no_evaluable_test_at_all_is_unusable_not_zero():
    """An F-Score of 0 means nine failed tests. It must not mean nine missing ones."""
    result = compute_piotroski_f_score({}, None)
    assert result.confidence is ResultConfidence.UNUSABLE
    assert result.score is None
    assert result.band is None


# --- Beneish ------------------------------------------------------------------


def test_caterpillar_m_score_matches_a_hand_computation(settings):
    result = compute_beneish_m_score(CAT_2024, CAT_2023, settings)
    assert result.confidence is ResultConfidence.COMPLETE

    coefficients = settings.beneish_coefficients()
    expected = coefficients["intercept"] + sum(
        coefficients[key] * result.components[key]["ratio"] for key in M_SCORE_DEFINITIONS
    )
    assert result.m_score == pytest.approx(expected, abs=1e-4)
    assert result.m_score == pytest.approx(-2.571, abs=1e-3)

    # DSRI just above 1: receivables essentially flat while sales fell 3.4%.
    assert result.components["dsri"]["ratio"] == pytest.approx(
        (9282 / 64809) / (9310 / 67060), abs=1e-6
    )
    # TATA, the heaviest term, is negative: cash flow exceeds reported income.
    assert result.components["tata"]["ratio"] < 0


def test_both_thresholds_are_reported_and_neither_is_promoted(settings):
    """-1.78 is Beneish's own cutoff; -2.22 is widely cited as a stricter one.

    Silently picking either would be taking a side in a live disagreement.
    """
    result = compute_beneish_m_score(CAT_2024, CAT_2023, settings)
    thresholds = result.calculation_basis["thresholds"]
    assert thresholds["beneish_1999"] == -1.78
    assert thresholds["stricter_commonly_cited"] == -2.22
    assert result.manipulation_flag is False
    assert result.strict_manipulation_flag is False


def test_a_manipulation_signature_crosses_the_threshold(settings):
    """Receivables running ahead of sales, margin falling, income outrunning cash.

    Constructed rather than sourced: naming a real company as a manipulator on
    the strength of a screening model would be exactly the overreach the model's
    own literature warns against.
    """
    prior = {
        "total_assets": 1000.0,
        "current_assets": 400.0,
        "current_liabilities": 200.0,
        "revenue": 1000.0,
        "cogs": 600.0,
        "accounts_receivable": 100.0,
        "ppe_net": 300.0,
        "depreciation_amortization": 30.0,
        "sga_expense": 100.0,
        "long_term_debt": 200.0,
        "operating_cash_flow": 120.0,
        "income_continuing_ops": 100.0,
    }
    current = {
        "total_assets": 1600.0,
        "current_assets": 500.0,
        "current_liabilities": 300.0,
        "revenue": 1500.0,
        "cogs": 1050.0,  # gross margin 40% -> 30%
        "accounts_receivable": 330.0,  # receivables up 230% on sales up 50%
        "ppe_net": 400.0,
        "depreciation_amortization": 20.0,  # depreciation rate cut
        "sga_expense": 130.0,
        "long_term_debt": 400.0,
        "operating_cash_flow": 40.0,  # income 190 against cash of 40
        "income_continuing_ops": 190.0,
    }
    result = compute_beneish_m_score(current, prior, settings)
    assert result.m_score > settings.beneish_threshold
    assert result.manipulation_flag is True
    assert result.components["dsri"]["ratio"] > 1.5
    assert result.components["tata"]["ratio"] > 0.05


def test_a_flag_is_labelled_a_screen_not_a_finding(settings):
    result = compute_beneish_m_score(CAT_2024, CAT_2023, settings)
    limit = result.calculation_basis["interpretation_limit"]
    assert "not a conclusion" in limit
    assert "aggressive accounting" in limit


def test_one_fiscal_year_withholds_the_m_score_entirely(settings):
    result = compute_beneish_m_score(CAT_2024, None, settings)
    assert result.m_score is None
    assert result.manipulation_flag is None
    assert result.confidence is ResultConfidence.UNUSABLE
    assert {entry["component"] for entry in result.omitted} == set(M_SCORE_DEFINITIONS)


def test_a_single_missing_component_withholds_the_whole_score(settings):
    """The opposite of how the Altman module handles a missing term, on purpose.

    Each Beneish index sits near 1.0 by construction, so DSRI contributes ~0.920
    to M for a company whose receivables did not move. Dropping the term removes
    0.920 from a score compared against a threshold of -1.78 - a fifth of the way
    across the entire decision range.
    """
    without_receivables = {k: v for k, v in CAT_2024.items() if k != "accounts_receivable"}
    result = compute_beneish_m_score(without_receivables, CAT_2023, settings)
    assert result.m_score is None
    assert result.confidence is ResultConfidence.UNUSABLE
    assert [entry["component"] for entry in result.omitted] == ["dsri"]

    refusal = result.calculation_basis["refusal"]
    assert "not a conservative estimate" in refusal
    assert "Substituting the neutral value 1.0 is worse" in refusal
    # And the seven terms that did compute are still shown, so the reader can see
    # how close the refusal was to being unnecessary.
    assert set(result.components) == set(M_SCORE_DEFINITIONS) - {"dsri"}


# --- The two together ----------------------------------------------------------


def test_the_two_models_answer_different_questions(settings):
    """Caterpillar is mixed on fundamentals and clean on earnings quality.

    That combination is the whole argument for running both: a mediocre F-Score
    on trustworthy numbers is a different finding from a mediocre F-Score on
    numbers that may be managed.
    """
    piotroski = compute_piotroski_f_score(CAT_2024, CAT_2023)
    beneish = compute_beneish_m_score(CAT_2024, CAT_2023, settings)
    assert piotroski.band is EarningsQualityBand.MIXED
    assert beneish.manipulation_flag is False
