"""DuPont, the cash conversion cycle, and multi-year trend.

# roadmap: v2-02-ratio-extensions

DuPont is an algebraic identity, so the interesting tests are not "does the
arithmetic work" but "does it refuse where ROE itself is meaningless" and "does
the product actually reconcile to ROE".
"""

from __future__ import annotations

import pytest

from app.services.ratio_extensions import (
    compute_cash_conversion_cycle,
    compute_dupont,
    compute_extensions,
    compute_trend,
)


def omitted_reason(entries, key: str) -> str:
    for entry in entries:
        if entry["metric"] == key:
            return entry["reason"]
    raise AssertionError(f"{key} was computed, expected it to be omitted")


CAT_2024 = {
    "total_assets": 87764.0,
    "shareholder_equity": 19494.0,
    "revenue": 64809.0,
    "net_income": 10792.0,
    "ebit": 13072.0,
    "pretax_income": 13373.0,
    "cogs": 40199.0,
    "inventory": 16827.0,
    "accounts_receivable": 9282.0,
    "accounts_payable": 7675.0,
}
CAT_2023 = {
    "total_assets": 87476.0,
    "shareholder_equity": 19503.0,
    "revenue": 67060.0,
    "net_income": 10335.0,
    "ebit": 12966.0,
    "pretax_income": 13050.0,
    "cogs": 42767.0,
    "inventory": 16565.0,
    "accounts_receivable": 9310.0,
    "accounts_payable": 7906.0,
}


# --- DuPont -------------------------------------------------------------------


def test_three_step_dupont_reconciles_to_roe():
    """Net margin x asset turnover x equity multiplier must equal ROE exactly.

    It is an identity, so a residual means a term came from a different period
    than the rest - the only way this decomposition can actually be wrong.
    """
    result, _ = compute_dupont(CAT_2024)
    three = result["three_step"]
    assert three["reconciles"] is True
    assert three["product_roe_pct"] == pytest.approx(result["roe"], abs=1e-3)
    assert three["terms"]["equity_multiplier"]["value"] == pytest.approx(87764 / 19494, abs=1e-4)


def test_five_step_dupont_reconciles_and_separates_financing_from_operations():
    result, _ = compute_dupont(CAT_2024)
    five = result["five_step"]
    assert five["reconciles"] is True
    assert five["product_roe_pct"] == pytest.approx(result["roe"], abs=1e-3)
    assert five["terms"]["tax_burden"]["value"] == pytest.approx(10792 / 13373, abs=1e-4)
    # Caterpillar's pretax profit exceeds operating profit, so the interest burden
    # is above 1.0 - non-operating income more than covers financing cost.
    assert five["terms"]["interest_burden"]["value"] == pytest.approx(13373 / 13072, abs=1e-4)


def test_negative_equity_withholds_the_whole_decomposition(vi_items):
    """The same refusal the ratio engine makes for ROE, for the same reason.

    Vodafone Idea's equity multiplier is 1,849,977 / -1,041,668 = -1.78. Every
    term still multiplies out, and the product is a positive ROE for a company
    whose liabilities exceed its assets.
    """
    result, omitted = compute_dupont(vi_items)
    assert result == {}
    reason = omitted_reason(omitted, "dupont")
    assert "negative" in reason
    naive_multiplier = vi_items["total_assets"] / vi_items["shareholder_equity"]
    assert naive_multiplier < 0, "the trap this refusal exists to prevent"


def test_five_step_is_omitted_when_pretax_income_is_missing_but_three_step_survives():
    """A missing term drops one form, not both. No partial products are reported."""
    items = {k: v for k, v in CAT_2024.items() if k != "pretax_income"}
    result, omitted = compute_dupont(items)
    assert "three_step" in result
    assert "five_step" not in result
    assert "tax_burden" in omitted_reason(omitted, "dupont_five_step")


# --- Cash conversion cycle ----------------------------------------------------


def test_cycle_uses_average_balances_when_a_prior_year_exists():
    cycle, _ = compute_cash_conversion_cycle(CAT_2024, CAT_2023)
    assert cycle["basis"] == "AVERAGE_BALANCE"
    assert cycle["dio"]["balance_used"] == pytest.approx((16827 + 16565) / 2, abs=1e-4)
    assert cycle["dio"]["days"] == pytest.approx(365 * ((16827 + 16565) / 2) / 40199, abs=1e-3)
    assert cycle["ccc"]["days"] == pytest.approx(
        cycle["dio"]["days"] + cycle["dso"]["days"] - cycle["dpo"]["days"], abs=1e-3
    )


def test_cycle_falls_back_to_ending_balances_and_says_so():
    """V1's turnover ratios used ending balances and said so. Same discipline here."""
    cycle, _ = compute_cash_conversion_cycle(CAT_2024, None)
    assert cycle["dio"]["balance_basis"] == "ENDING_BALANCE"
    assert cycle["dio"]["balance_used"] == 16827.0


def test_a_services_company_still_gets_dso_without_inventory():
    """A missing day count drops itself and the total, not the whole block."""
    items = {"revenue": 18562.0, "accounts_receivable": 3620.0}
    cycle, omitted = compute_cash_conversion_cycle(items, None)
    assert cycle["dso"]["days"] == pytest.approx(365 * 3620 / 18562, abs=1e-3)
    assert "ccc" not in cycle
    assert "dio" in omitted_reason(omitted, "ccc")


# --- Trend --------------------------------------------------------------------


def test_trend_needs_two_years():
    trend, notes = compute_trend({2024: {"roa": 12.3}})
    assert trend == {}
    assert "fewer than two" in notes[0]


def test_trend_reports_change_and_cagr_for_a_positive_series():
    trend, _ = compute_trend({2022: {"roa": 8.0}, 2024: {"roa": 12.5}})
    entry = trend["ratios"]["roa"]
    assert entry["direction"] == "up"
    assert entry["change"] == pytest.approx(4.5, abs=1e-6)
    assert entry["cagr_pct"] == pytest.approx(100 * ((12.5 / 8.0) ** 0.5 - 1), abs=1e-3)


def test_cagr_is_refused_across_a_sign_change():
    """A compound growth rate from -4% to +2% is not a real number.

    The formula returns either a complex value or a confidently wrong one
    depending on the exponent, which is worse than reporting nothing.
    """
    trend, _ = compute_trend({2023: {"net_margin": -4.0}, 2024: {"net_margin": 2.0}})
    entry = trend["ratios"]["net_margin"]
    assert "cagr_pct" not in entry
    assert "sign change" in entry["cagr_omitted"]
    assert entry["change"] == pytest.approx(6.0, abs=1e-6)


def test_extensions_record_whether_a_prior_year_was_available():
    result = compute_extensions(
        items=CAT_2024, prior_items=CAT_2023, history={2023: {}, 2024: {}}, fiscal_year=2024
    )
    assert result.calculation_basis["prior_year_available"] is True
    assert result.calculation_basis["cycle_balance_basis"] == "AVERAGE_BALANCE"
