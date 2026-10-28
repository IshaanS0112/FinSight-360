"""HTTP contract for the V2 stages, against a real SQLite-backed app.

# roadmap: v2-03-bankruptcy-suite
# roadmap: v2-04-earnings-quality

Separate from ``test_api_integration.py`` so the V1 contract file stays a fixed
regression guard. Anything asserted there must keep its exact meaning; anything
asserted here is new surface.
"""

from __future__ import annotations

import pytest


def _upload(client, company_id: str, statement: dict, fiscal_year: int) -> None:
    response = client.post(
        f"/companies/{company_id}/financial-statements",
        json={**statement, "fiscal_year": fiscal_year},
    )
    assert response.status_code == 201, response.text


@pytest.fixture
def two_year_caterpillar(client, load_company, caterpillar) -> str:
    """Caterpillar with FY2024 as shipped, plus the FY2023 comparatives.

    The FY2023 figures and the FY2024 supplements are the SEC's own XBRL
    extraction of the 10-K, the same source the FY2024 sample filing was
    cross-verified against.
    """
    company_id = load_company(caterpillar)
    _upload(
        client,
        company_id,
        {
            "statement_type": "BALANCE_SHEET",
            "line_items": {
                "accounts_receivable": 9282,
                "accounts_payable": 7675,
                "ppe_net": 13361,
                "long_term_debt": 27351,
                "shares_outstanding": 477.9,
            },
        },
        2024,
    )
    _upload(
        client,
        company_id,
        {
            "statement_type": "INCOME_STATEMENT",
            "line_items": {
                "pretax_income": 13373,
                "sga_expense": 6667,
                "income_continuing_ops": 10788,
            },
        },
        2024,
    )
    _upload(
        client,
        company_id,
        {"statement_type": "CASH_FLOW", "line_items": {"depreciation_amortization": 2153}},
        2024,
    )
    _upload(
        client,
        company_id,
        {
            "statement_type": "BALANCE_SHEET",
            "line_items": {
                "total_assets": 87476,
                "current_assets": 46949,
                "current_liabilities": 34728,
                "total_liabilities": 67973,
                "inventory": 16565,
                "shareholder_equity": 19503,
                "retained_earnings": 51250,
                "total_debt": 37878,
                "accounts_receivable": 9310,
                "accounts_payable": 7906,
                "ppe_net": 12680,
                "long_term_debt": 24472,
                "shares_outstanding": 499.4,
            },
        },
        2023,
    )
    _upload(
        client,
        company_id,
        {
            "statement_type": "INCOME_STATEMENT",
            "line_items": {
                "revenue": 67060,
                "cogs": 42767,
                "ebit": 12966,
                "net_income": 10335,
                "pretax_income": 13050,
                "sga_expense": 6371,
                "income_continuing_ops": 10332,
            },
        },
        2023,
    )
    _upload(
        client,
        company_id,
        {
            "statement_type": "CASH_FLOW",
            "line_items": {
                "operating_cash_flow": 12885,
                "capital_expenditure": 3092,
                "depreciation_amortization": 2144,
            },
        },
        2023,
    )
    return company_id


# --- The risk suite over HTTP --------------------------------------------------


def test_the_suite_returns_ohlson_and_a_consensus_alongside_altman(client, two_year_caterpillar):
    body = client.post(f"/companies/{two_year_caterpillar}/compute-bankruptcy-risk", json={}).json()

    assert body["model"] == "Z_1968"
    assert body["altman_z_score"] == pytest.approx(3.9203, abs=1e-4)
    assert body["ohlson_o_score"] == pytest.approx(-2.0767, abs=1e-4)
    assert body["ohlson_probability"] == pytest.approx(0.1114, abs=1e-4)
    assert body["consensus_verdict"] == "LOW_RISK"
    assert body["zscore_variant"] == "Z_1968"
    assert set(body["variant_scores"]) == {"Z_1968", "Z_PRIME", "Z_DOUBLE_PRIME"}


def test_the_v1_altman_contract_is_unchanged_by_the_suite(client, two_year_caterpillar):
    """Every V1 key keeps its exact meaning and position in calculation_basis."""
    body = client.post(f"/companies/{two_year_caterpillar}/compute-bankruptcy-risk", json={}).json()
    basis = body["calculation_basis"]
    assert basis["citation"].startswith("Altman, E. I. (1968)")
    assert basis["cutoffs"] == {"safe_above": 2.99, "distress_below": 1.81}
    assert basis["x4_equity_basis"] == "MARKET_VALUE"
    # And the new material is namespaced under its own keys rather than mixed in.
    assert "size_substitution" in basis["ohlson"]
    assert "consensus_reason" in basis["consensus"]


def test_a_single_year_company_still_gets_a_score_with_the_gap_named(
    client, load_company, caterpillar
):
    """One year is enough for Altman and for seven of Ohlson's nine terms."""
    company_id = load_company(caterpillar)
    body = client.post(f"/companies/{company_id}/compute-bankruptcy-risk", json={}).json()
    assert body["altman_z_score"] == pytest.approx(3.9203, abs=1e-4)
    assert body["ohlson_o_score"] is not None
    assert {entry["term"] for entry in body["ohlson_omitted"]} == {"intwo", "chin", "futl"}


def test_a_bank_is_refused_by_both_models(client, caterpillar):
    payload = {
        **caterpillar["company"],
        "name": "A Commercial Bank Ltd",
        "industry": "banking",
        "sector_class": "FINANCIAL",
    }
    company_id = client.post("/companies", json=payload).json()["id"]
    client.post(f"/companies/{company_id}/financial-statements", json=caterpillar["statements"][0])
    body = client.post(f"/companies/{company_id}/compute-bankruptcy-risk", json={}).json()
    assert body["altman_z_score"] is None
    assert body["ohlson_o_score"] is None
    assert body["consensus_verdict"] == "INDETERMINATE"


def test_the_distressed_company_reaches_high_risk_consensus(client, load_company, vodafone_idea):
    """Vodafone Idea: Altman DISTRESS and Ohlson well past its own cutoff.

    Both models are PARTIAL - Altman is missing EBIT, Ohlson is missing funds
    from operations and both year-on-year terms - and they still agree, which is
    the useful shape of a partial result.
    """
    company_id = load_company(vodafone_idea)
    body = client.post(f"/companies/{company_id}/compute-bankruptcy-risk", json={}).json()
    assert body["zone"] == "DISTRESS"
    assert body["ohlson_probability"] > 0.5
    assert body["consensus_verdict"] == "HIGH_RISK"


# --- Earnings quality over HTTP ------------------------------------------------


def test_earnings_quality_returns_both_scores(client, two_year_caterpillar):
    body = client.post(f"/companies/{two_year_caterpillar}/compute-earnings-quality").json()
    assert body["fiscal_year"] == 2024
    assert body["prior_fiscal_year"] == 2023
    assert body["piotroski_f_score"] == 7
    assert body["f_score_band"] == "MIXED"
    assert body["beneish_m_score"] == pytest.approx(-2.571, abs=1e-3)
    assert body["manipulation_flag"] is False
    assert body["confidence"] == "COMPLETE"


def test_one_year_of_data_is_an_explained_partial_not_a_refusal(client, load_company, caterpillar):
    """A 409 saying "upload more data" hides which tests the gap actually costs."""
    company_id = load_company(caterpillar)
    response = client.post(f"/companies/{company_id}/compute-earnings-quality")
    assert response.status_code == 200
    body = response.json()
    assert body["prior_fiscal_year"] is None
    assert body["f_score_band"] is None, "no band without all nine tests"
    assert body["beneish_m_score"] is None
    assert body["manipulation_flag"] is None
    not_evaluated = {
        key
        for key, entry in body["f_score_components"].items()
        if entry["status"] == "NOT_EVALUATED"
    }
    assert "roa_improving" in not_evaluated
    assert {entry["model"] for entry in body["omitted"]} == {"piotroski", "beneish"}


def test_unrun_earnings_quality_is_a_404(client, load_company, caterpillar):
    company_id = load_company(caterpillar)
    assert client.get(f"/companies/{company_id}/earnings-quality").status_code == 404


def test_full_analysis_now_runs_the_earnings_quality_stage(client, two_year_caterpillar):
    assert client.post(f"/companies/{two_year_caterpillar}/run-full-analysis").status_code == 200
    stored = client.get(f"/companies/{two_year_caterpillar}/earnings-quality").json()
    assert stored["piotroski_f_score"] == 7


# --- Methodology ----------------------------------------------------------------


def test_methodology_publishes_the_new_coefficients_and_the_size_substitution(client):
    """The honesty claim is only checkable if the parameters are visible."""
    body = client.get("/methodology").json()["models"]
    assert body["ohlson"]["coefficients"]["tlta"] == 6.03
    assert body["ohlson"]["coefficients"]["intercept"] == -1.32
    assert "GNP price-level index" in body["ohlson"]["size_substitution"]
    assert body["beneish"]["coefficients"]["tata"] == 4.679
    assert body["beneish"]["thresholds"] == {
        "beneish_1999": -1.78,
        "stricter_commonly_cited": -2.22,
    }
    assert len(body["piotroski"]["tests"]) == 9
    assert "MIXED_SIGNAL" in body["consensus_verdict"]["mixed_signal_is_an_output"]


# --- The multi-year ratio surface ------------------------------------------------


def test_two_years_produce_dupont_a_cycle_and_a_trend(client, two_year_caterpillar):
    body = client.post(f"/companies/{two_year_caterpillar}/compute-ratios").json()
    assert body["fiscal_year"] == 2024
    assert body["calculation_basis"]["fiscal_years_on_file"] == [2023, 2024]

    assert body["dupont"]["three_step"]["reconciles"] is True
    assert body["dupont"]["five_step"]["reconciles"] is True
    assert body["cash_conversion_cycle"]["basis"] == "AVERAGE_BALANCE"
    assert body["cash_conversion_cycle"]["ccc"]["days"] > 0

    trend = body["trend"]
    assert trend["years"] == [2023, 2024]
    assert trend["ratios"]["net_margin"]["direction"] == "up"
    assert trend["ratios"]["asset_turnover"]["direction"] == "down"
