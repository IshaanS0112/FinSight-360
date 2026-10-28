"""DCF-lite: the arithmetic, and the three places the model has no meaning.

# roadmap: v2-06-dcf-valuation

V1 declined to build this because rushing a DCF produces exactly the invented
number the project exists to avoid. The tests that justify building it now are
the refusals, not the valuation.
"""

from __future__ import annotations

import pytest

from app.enums import ResultConfidence
from app.services.dcf_valuation import DcfAssumptions, compute_dcf, compute_wacc

# Caterpillar FY2024, with the cash balance and year-end share price the DCF
# bridge needs. Illustrative where the sample filing does not carry a figure.
CAT = {
    "revenue": 64809.0,
    "ebit": 13072.0,
    "depreciation_amortization": 2153.0,
    "capital_expenditure": 3215.0,
    "current_assets": 45682.0,
    "current_liabilities": 32272.0,
    "total_debt": 38409.0,
    "cash_and_equivalents": 6890.0,
    "shares_outstanding": 477.9,
    "share_price": 363.0,
    "market_value_equity": 177528.0,
    "interest_expense": 512.0,
}


def assumptions(settings, **overrides) -> DcfAssumptions:
    return DcfAssumptions.defaults(settings, **overrides)


def omitted_reason(result, key: str) -> str:
    for entry in result.omitted:
        if entry["input"] == key:
            return entry["reason"]
    raise AssertionError(f"{key} was not omitted")


# --- The arithmetic -----------------------------------------------------------


def test_capm_and_the_capital_structure_produce_the_published_wacc_formula(settings):
    wacc, detail = compute_wacc(CAT, assumptions(settings, beta=1.1))
    re = settings.dcf_risk_free_rate + 1.1 * settings.dcf_equity_risk_premium
    rd = 512.0 / 38409.0
    equity, debt = 177528.0, 38409.0
    total = equity + debt
    expected = (equity / total) * re + (debt / total) * rd * (1 - settings.dcf_tax_rate)

    assert wacc == pytest.approx(expected, abs=1e-9)
    # The detail block is rounded for display; the WACC above is not.
    assert detail["cost_of_equity"] == pytest.approx(re, abs=1e-6)
    assert detail["cost_of_debt_pretax"] == pytest.approx(rd, abs=1e-6)
    assert detail["equity_basis"] == "MARKET_VALUE"


def test_wacc_weights_use_market_equity_and_warn_when_they_cannot(settings):
    """Book weights for a company trading at nine times book would understate Re's share."""
    # Market value is preferred, then shares x year-end price, then book. Strip
    # the first two so the fallback of last resort is what gets exercised.
    dropped = {"market_value_equity", "shares_outstanding", "share_price"}
    without_market = {k: v for k, v in CAT.items() if k not in dropped}
    without_market["shareholder_equity"] = 19494.0
    _, detail = compute_wacc(without_market, assumptions(settings))
    assert detail["equity_basis"] == "BOOK_VALUE"
    assert "overweights debt" in detail["equity_basis_warning"]


def test_the_projection_discounts_every_year_and_the_terminal_value(settings):
    result = compute_dcf(
        items=CAT, assumptions=assumptions(settings, revenue_growth=0.03), settings=settings
    )
    assert result.confidence is ResultConfidence.COMPLETE
    assert len(result.fcff_projection) == settings.dcf_projection_years

    first = result.fcff_projection[0]
    assert first["revenue"] == pytest.approx(64809.0 * 1.03, abs=1e-2)
    assert first["nopat"] == pytest.approx(first["ebit"] * (1 - settings.dcf_tax_rate), abs=1e-2)
    assert first["fcff"] == pytest.approx(
        first["nopat"]
        + first["depreciation_amortization"]
        - first["capital_expenditure"]
        - first["change_in_nwc"],
        abs=1e-2,
    )
    assert first["discount_factor"] == pytest.approx(1 / (1 + result.wacc), abs=1e-6)

    discounted_flows = sum(y["present_value"] for y in result.fcff_projection)
    discounted_terminal = result.terminal_value / (1 + result.wacc) ** settings.dcf_projection_years
    assert result.enterprise_value == pytest.approx(discounted_flows + discounted_terminal, abs=1.0)


def test_the_equity_bridge_and_the_implied_price(settings):
    result = compute_dcf(items=CAT, assumptions=assumptions(settings), settings=settings)
    assert result.equity_value == pytest.approx(
        result.enterprise_value - (38409.0 - 6890.0), abs=1e-2
    )
    assert result.implied_share_price == pytest.approx(result.equity_value / 477.9, abs=1e-3)
    assert result.upside_downside_pct == pytest.approx(
        100 * (result.implied_share_price - 363.0) / 363.0, abs=1e-2
    )


def test_a_higher_discount_rate_lowers_the_value(settings):
    """The most basic sanity property a DCF can have."""
    cheap = compute_dcf(
        items=CAT, assumptions=assumptions(settings, wacc_override=0.07), settings=settings
    )
    dear = compute_dcf(
        items=CAT, assumptions=assumptions(settings, wacc_override=0.12), settings=settings
    )
    assert cheap.enterprise_value > dear.enterprise_value


# --- The refusals -------------------------------------------------------------


def test_terminal_growth_approaching_wacc_is_refused_not_reported(settings):
    """Gordon divides by (WACC - g). The naive implementation returns a number here.

    At g just under WACC the value diverges to infinity; past it the value goes
    negative while still looking like a price per share.
    """
    result = compute_dcf(
        items=CAT,
        assumptions=assumptions(settings, wacc_override=0.08, terminal_growth=0.0799),
        settings=settings,
    )
    assert result.enterprise_value is None
    assert result.implied_share_price is None
    assert result.confidence is ResultConfidence.UNUSABLE
    assert "diverges to infinity" in result.calculation_basis["refusal"]


def test_terminal_growth_above_wacc_is_refused_rather_than_returning_a_negative_price(settings):
    result = compute_dcf(
        items=CAT,
        assumptions=assumptions(settings, wacc_override=0.06, terminal_growth=0.09),
        settings=settings,
    )
    assert result.confidence is ResultConfidence.UNUSABLE
    assert result.equity_value is None


def test_negative_base_ebit_is_computed_but_flagged_unusable(settings):
    """A DCF of a loss-making company is an arithmetic consequence, not a valuation."""
    loss_making = {**CAT, "ebit": -4000.0}
    result = compute_dcf(items=loss_making, assumptions=assumptions(settings), settings=settings)
    assert result.implied_share_price is not None
    assert result.implied_share_price < 0
    assert result.confidence is ResultConfidence.UNUSABLE
    assert "arithmetic consequence" in result.calculation_basis["negative_ebit_warning"]


def test_a_missing_driver_refuses_rather_than_defaulting_to_zero(settings):
    """Zero capital expenditure is a claim about the business, not a missing value."""
    without_capex = {k: v for k, v in CAT.items() if k != "capital_expenditure"}
    result = compute_dcf(items=without_capex, assumptions=assumptions(settings), settings=settings)
    assert result.enterprise_value is None
    assert result.confidence is ResultConfidence.UNUSABLE
    assert "not assumed to be zero" in omitted_reason(result, "capital_expenditure")


def test_no_share_count_withholds_the_price_but_keeps_the_enterprise_value(settings):
    without_shares = {k: v for k, v in CAT.items() if k != "shares_outstanding"}
    result = compute_dcf(items=without_shares, assumptions=assumptions(settings), settings=settings)
    assert result.enterprise_value is not None
    assert result.equity_value is not None
    assert result.implied_share_price is None
    assert result.confidence is ResultConfidence.PARTIAL
    assert "guessed share count" in omitted_reason(result, "shares_outstanding")


def test_negative_equity_makes_the_capital_structure_meaningless(settings, vi_items):
    """Vodafone Idea's E/V weight would be negative, which is not a capital structure."""
    items = {k: v for k, v in vi_items.items() if k != "market_value_equity"}
    wacc, detail = compute_wacc(items, assumptions(settings))
    assert wacc is None
    assert "not a capital structure" in detail["reason"]


# --- Honesty about the assumptions ---------------------------------------------


def test_every_assumption_is_stored_with_the_result(settings):
    """A DCF is a function of its assumptions and almost nothing else."""
    result = compute_dcf(
        items=CAT,
        assumptions=assumptions(settings, beta=1.3, revenue_growth=0.06),
        settings=settings,
    )
    assert result.assumptions["beta"] == 1.3
    assert result.assumptions["revenue_growth"] == 0.06
    assert result.assumptions["terminal_growth"] == settings.dcf_terminal_growth
    assert result.assumptions["projection_years"] == settings.dcf_projection_years


def test_beta_is_labelled_an_input_rather_than_a_measurement(settings):
    """A declared beta says so, and says how to get a measured one instead."""
    result = compute_dcf(items=CAT, assumptions=assumptions(settings), settings=settings)
    note = result.calculation_basis["beta_note"]
    assert "not a measurement" in note
    assert "regression beta" in note
    assert result.calculation_basis["beta_source"] == {"source": "DECLARED"}


def test_a_regression_beta_is_labelled_with_its_evidence(settings):
    # roadmap: v3-01-market-data
    source = {
        "source": "REGRESSION",
        "raw_beta": 1.195,
        "adjusted_beta": 1.1307,
        "benchmark": "SPY",
        "observations": 60,
        "r_squared": 0.43,
        "window_end": "2024-12-31",
    }
    result = compute_dcf(
        items=CAT,
        assumptions=assumptions(settings, beta=1.1307),
        settings=settings,
        beta_source=source,
    )
    note = result.calculation_basis["beta_note"]
    assert "measured" in note
    assert "SPY" in note and "60 months" in note and "2024-12-31" in note
    assert result.calculation_basis["beta_source"]["source"] == "REGRESSION"


def test_the_terminal_value_share_is_reported_as_a_diagnostic(settings):
    """The single most useful number for judging whether a DCF means anything."""
    result = compute_dcf(items=CAT, assumptions=assumptions(settings), settings=settings)
    share = result.calculation_basis["terminal_value_share_of_ev"]
    assert 0 < share < 1
    assert (
        "perpetuity assumption with a five-year schedule"
        in (result.calculation_basis["terminal_value_note"])
    )


def test_the_flat_driver_simplification_is_stated(settings):
    result = compute_dcf(items=CAT, assumptions=assumptions(settings), settings=settings)
    assert "DCF-lite" in result.calculation_basis["driver_note"]
    assert "capex cycle" in result.calculation_basis["driver_note"]


# --- Over HTTP -------------------------------------------------------------------


def test_valuation_over_http_stores_the_assumptions(client, load_company, caterpillar):
    company_id = load_company(caterpillar)
    for statement in (
        {
            "statement_type": "BALANCE_SHEET",
            "line_items": {
                "cash_and_equivalents": 6890,
                "shares_outstanding": 477.9,
                "share_price": 363,
            },
        },
        {"statement_type": "CASH_FLOW", "line_items": {"depreciation_amortization": 2153}},
    ):
        response = client.post(f"/companies/{company_id}/financial-statements", json=statement)
        assert response.status_code == 201, response.text

    response = client.post(
        f"/companies/{company_id}/compute-valuation", json={"revenue_growth": 0.04, "beta": 1.1}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["base_fiscal_year"] == 2024
    assert body["assumptions"]["revenue_growth"] == 0.04
    assert body["assumptions"]["beta"] == 1.1
    assert body["implied_share_price"] is not None
    assert len(body["fcff_projection"]) == 5

    assert client.get(f"/companies/{company_id}/valuation").json()["id"] == body["id"]


def test_an_impossible_terminal_growth_returns_a_reason_not_an_error_code(
    client, load_company, caterpillar
):
    """An analyst dragging the slider past WACC should see why the number vanished."""
    company_id = load_company(caterpillar)
    client.post(
        f"/companies/{company_id}/financial-statements",
        json={"statement_type": "CASH_FLOW", "line_items": {"depreciation_amortization": 2153}},
    )
    response = client.post(
        f"/companies/{company_id}/compute-valuation",
        json={"wacc_override": 0.07, "terminal_growth": 0.09},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["enterprise_value"] is None
    assert body["confidence"] == "UNUSABLE"
    assert "Gordon terminal value" in body["calculation_basis"]["refusal"]


def test_an_out_of_range_assumption_is_rejected_at_the_schema(client, load_company, caterpillar):
    company_id = load_company(caterpillar)
    response = client.post(f"/companies/{company_id}/compute-valuation", json={"tax_rate": 1.5})
    assert response.status_code == 422


def test_unrun_valuation_is_a_404(client, load_company, caterpillar):
    company_id = load_company(caterpillar)
    assert client.get(f"/companies/{company_id}/valuation").status_code == 404


def test_the_shipped_caterpillar_filing_alone_cannot_be_valued(client, load_company, caterpillar):
    """The V1 sample filing carries no depreciation line, so FCFF cannot be formed.

    The endpoint says which input is missing rather than returning a value built
    on a depreciation figure of zero.
    """
    company_id = load_company(caterpillar)
    body = client.post(f"/companies/{company_id}/compute-valuation").json()
    assert body["confidence"] == "UNUSABLE"
    assert body["enterprise_value"] is None
    missing = {entry["input"] for entry in body["calculation_basis"]["omitted"]}
    assert "depreciation_amortization" in missing
