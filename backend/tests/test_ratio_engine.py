"""Ratio engine: arithmetic, and refusal to produce a misleading number."""

from __future__ import annotations

import pytest

from app.enums import ResultConfidence
from app.services.ratio_engine import FORMULAS, compute_ratios


def omitted_reason(result, key: str) -> str:
    for entry in result.omitted:
        if entry["ratio"] == key:
            return entry["reason"]
    raise AssertionError(f"{key} was computed, expected it to be omitted")


# --- Arithmetic against hand-computed values ---------------------------------

def test_caterpillar_ratios_match_hand_computation(cat_items):
    r = compute_ratios(cat_items)
    assert r.confidence is ResultConfidence.COMPLETE
    assert r.omitted == []

    assert r.liquidity["current_ratio"] == pytest.approx(45682 / 32272, abs=1e-4)
    assert r.liquidity["quick_ratio"] == pytest.approx((45682 - 16827) / 32272, abs=1e-4)
    assert r.profitability["roe"] == pytest.approx(100 * 10792 / 19494, abs=1e-4)
    assert r.profitability["roa"] == pytest.approx(100 * 10792 / 87764, abs=1e-4)
    assert r.profitability["net_margin"] == pytest.approx(100 * 10792 / 64809, abs=1e-4)
    assert r.leverage["debt_to_equity"] == pytest.approx(38409 / 19494, abs=1e-4)
    assert r.leverage["interest_coverage"] == pytest.approx(13072 / 512, abs=1e-4)
    assert r.efficiency["asset_turnover"] == pytest.approx(64809 / 87764, abs=1e-4)
    assert r.efficiency["inventory_turnover"] == pytest.approx(40199 / 16827, abs=1e-4)


def test_gross_margin_reproduces_the_published_figure(cat_items):
    """Independent check against a figure published by the data provider.

    S&P/Fiscal.ai publish Caterpillar's FY2024 gross margin as 37.97%. Gross
    margin is one of the few ratios where every provider agrees on the definition,
    so an exact match here is evidence the arithmetic and the transcription are
    both right - and it is the kind of check worth having, because the ratios that
    disagree (see test_definitional_differences_are_recorded) can only be argued
    about once the undisputed ones tie out.
    """
    r = compute_ratios(cat_items)
    assert r.profitability["gross_margin"] == pytest.approx(37.97, abs=0.005)


def test_infosys_ratios_are_all_computable(infy_items):
    r = compute_ratios(infy_items)
    assert r.confidence is ResultConfidence.COMPLETE
    assert r.profitability["gross_margin"] == pytest.approx(29.45, abs=0.01)
    assert r.profitability["net_margin"] == pytest.approx(17.06, abs=0.01)
    # Debt-free by comparison: coverage of ~68x against a 5x reference band.
    assert r.leverage["interest_coverage"] > 50


def test_definitional_differences_are_recorded(cat_items):
    """The basis for each contested definition is in the result, not only in docs."""
    r = compute_ratios(cat_items)
    basis = r.calculation_basis
    assert basis["turnover_basis"] == "ENDING_BALANCE"
    assert basis["quick_ratio_definition"] == FORMULAS["quick_ratio"]
    assert set(basis["formulas"]) == set(r.all_ratios)


# --- Refusals ----------------------------------------------------------------

def test_negative_equity_withholds_roe_and_debt_to_equity(vi_items):
    """The single most important refusal in the engine.

    Vodafone Idea FY2024: net loss of -312,387 against equity of -1,041,668.
    Naively, ROE = 100 * -312387 / -1041668 = +29.99%, which reads as strong
    performance for a company whose liabilities exceed its assets. Both ratios are
    withheld with a reason instead.
    """
    r = compute_ratios(vi_items)
    assert "roe" not in r.profitability
    assert "debt_to_equity" not in r.leverage
    assert "undefined" in omitted_reason(r, "roe")
    assert "negative" in omitted_reason(r, "debt_to_equity")

    naive_roe = 100 * vi_items["net_income"] / vi_items["shareholder_equity"]
    assert naive_roe > 0, "the trap this test exists to prevent"


def test_missing_inventory_omits_quick_ratio_rather_than_assuming_zero():
    items = {"current_assets": 100.0, "current_liabilities": 50.0}
    r = compute_ratios(items)
    assert r.liquidity["current_ratio"] == 2.0
    assert "quick_ratio" not in r.liquidity
    assert "not assumed to be zero" in omitted_reason(r, "quick_ratio")


def test_missing_ebit_omits_interest_coverage(vi_items):
    r = compute_ratios(vi_items)
    assert "interest_coverage" not in r.leverage
    assert "ebit" in omitted_reason(r, "interest_coverage")


def test_zero_interest_expense_is_a_finding_not_infinity():
    items = {"total_assets": 100.0, "ebit": 20.0, "interest_expense": 0.0}
    r = compute_ratios(items)
    assert "interest_coverage" not in r.leverage
    assert "unbounded" in omitted_reason(r, "interest_coverage")


def test_interest_expense_sign_does_not_change_coverage():
    """Filings present interest expense with either sign; coverage uses magnitude."""
    positive = compute_ratios({"total_assets": 1.0, "ebit": 100.0, "interest_expense": 10.0})
    negative = compute_ratios({"total_assets": 1.0, "ebit": 100.0, "interest_expense": -10.0})
    assert positive.leverage["interest_coverage"] == negative.leverage["interest_coverage"] == 10.0


def test_boolean_line_item_is_not_read_as_a_number():
    """``isinstance(True, int)`` is True in Python, so this is a real hazard."""
    r = compute_ratios({"current_assets": True, "current_liabilities": 50.0})
    assert "current_ratio" not in r.liquidity


def test_empty_input_is_unusable_not_a_pile_of_zeros():
    r = compute_ratios({})
    assert r.all_ratios == {}
    assert r.confidence is ResultConfidence.UNUSABLE
    assert len(r.omitted) == 10
