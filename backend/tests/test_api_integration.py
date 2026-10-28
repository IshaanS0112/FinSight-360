"""HTTP contract, end to end, against a real SQLite-backed app."""

from __future__ import annotations

import pytest


def test_health_and_methodology_are_public(client):
    assert client.get("/health").json() == {"status": "ok"}

    methodology = client.get("/methodology").json()
    assert methodology["models"]["altman"]["variants"]["Z_1968"]["coefficients"]["x3"] == 3.3
    assert methodology["models"]["health_score"]["weights"]["profitability"] == 0.35
    assert "ILLUSTRATIVE PLACEHOLDER" in methodology["benchmark_provenance"]
    assert "Narration only" in methodology["llm_role"]


def test_methodology_admits_the_health_score_is_not_an_established_model(client):
    methodology = client.get("/methodology").json()
    assert "PROJECT-DEFINED" in methodology["models"]["health_score"]["status"]


# --- The full demo flow ------------------------------------------------------


def test_full_analysis_flow_for_caterpillar(client, load_company, caterpillar):
    company_id = load_company(caterpillar)

    ratios = client.post(f"/companies/{company_id}/compute-ratios")
    assert ratios.status_code == 200
    assert ratios.json()["liquidity_ratios"]["current_ratio"] == pytest.approx(1.4155, abs=1e-4)

    risk = client.post(f"/companies/{company_id}/compute-bankruptcy-risk", json={})
    assert risk.status_code == 200
    body = risk.json()
    assert body["model"] == "Z_1968"
    assert body["zone"] == "SAFE"
    assert body["altman_z_score"] == pytest.approx(3.9203, abs=1e-4)
    assert body["calculation_basis"]["citation"].startswith("Altman, E. I. (1968)")

    health = client.post(f"/companies/{company_id}/compute-health-score")
    assert health.status_code == 200
    assert health.json()["overall_score"] > 50

    insights = client.post(f"/companies/{company_id}/generate-insights")
    assert insights.status_code == 200
    report = insights.json()
    assert report["generated_by"] == "template_fallback"
    assert report["structured_context"]["bankruptcy_risk"]["zone"] == "SAFE"

    for path, key in (
        ("ratio-analysis", "liquidity_ratios"),
        ("bankruptcy-risk", "zone"),
        ("health-score", "overall_score"),
        ("insights-report", "ai_narrative"),
    ):
        response = client.get(f"/companies/{company_id}/{path}")
        assert response.status_code == 200, path
        assert key in response.json()


def test_run_full_analysis_shortcut_matches_the_staged_path(client, load_company, infosys):
    company_id = load_company(infosys)
    report = client.post(f"/companies/{company_id}/run-full-analysis")
    assert report.status_code == 200
    risk = report.json()["structured_context"]["bankruptcy_risk"]
    assert risk["model"] == "Z_DOUBLE_PRIME"
    assert risk["zone"] == "SAFE"


def test_distressed_company_reports_partial_confidence_over_http(
    client, load_company, vodafone_idea
):
    company_id = load_company(vodafone_idea)
    body = client.post(f"/companies/{company_id}/run-full-analysis").json()
    risk = body["structured_context"]["bankruptcy_risk"]
    assert risk["zone"] == "DISTRESS"
    assert risk["confidence"] == "PARTIAL"
    assert [c["component"] for c in risk["omitted_components"]] == ["x3"]
    ratios = body["structured_context"]["ratios"]
    assert "roe" not in ratios["profitability"], "withheld at negative equity"


# --- Preconditions and ordering ----------------------------------------------


def test_analysis_before_any_statement_is_a_conflict_not_a_crash(client, caterpillar):
    company_id = client.post("/companies", json=caterpillar["company"]).json()["id"]
    response = client.post(f"/companies/{company_id}/compute-ratios")
    assert response.status_code == 409
    assert "No financial statements" in response.json()["detail"]


def test_health_score_before_ratios_says_which_stage_is_missing(client, load_company, caterpillar):
    company_id = load_company(caterpillar)
    response = client.post(f"/companies/{company_id}/compute-health-score")
    assert response.status_code == 409
    assert "/compute-ratios first" in response.json()["detail"]


def test_insights_before_the_other_stages_is_refused(client, load_company, caterpillar):
    company_id = load_company(caterpillar)
    client.post(f"/companies/{company_id}/compute-ratios")
    response = client.post(f"/companies/{company_id}/generate-insights")
    assert response.status_code == 409
    assert "compute-bankruptcy-risk" in response.json()["detail"]


def test_unrun_stage_returns_404_not_an_empty_object(client, load_company, caterpillar):
    company_id = load_company(caterpillar)
    assert client.get(f"/companies/{company_id}/bankruptcy-risk").status_code == 404


def test_unknown_company_is_404(client):
    missing = "00000000-0000-0000-0000-000000000999"
    assert client.get(f"/companies/{missing}").status_code == 404


# --- Input validation --------------------------------------------------------


def test_unknown_line_item_key_is_rejected(client, load_company, caterpillar):
    company_id = load_company(caterpillar)
    response = client.post(
        f"/companies/{company_id}/financial-statements",
        json={"statement_type": "BALANCE_SHEET", "line_items": {"total_asets": 100}},
    )
    assert response.status_code == 422
    assert "not a recognised line item" in response.text


def test_line_item_on_the_wrong_statement_is_rejected(client, load_company, caterpillar):
    company_id = load_company(caterpillar)
    response = client.post(
        f"/companies/{company_id}/financial-statements",
        json={"statement_type": "INCOME_STATEMENT", "line_items": {"total_assets": 100}},
    )
    assert response.status_code == 422
    assert "do not belong to a" in response.text


def test_negative_total_assets_is_rejected(client, caterpillar):
    company_id = client.post("/companies", json=caterpillar["company"]).json()["id"]
    response = client.post(
        f"/companies/{company_id}/financial-statements",
        json={"statement_type": "BALANCE_SHEET", "line_items": {"total_assets": -100}},
    )
    assert response.status_code == 422
    assert "cannot be negative" in response.text


def test_negative_retained_earnings_is_accepted(client, caterpillar):
    """The distressed case must be representable, or the tool cannot do its job."""
    company_id = client.post("/companies", json=caterpillar["company"]).json()["id"]
    response = client.post(
        f"/companies/{company_id}/financial-statements",
        json={
            "statement_type": "BALANCE_SHEET",
            "line_items": {
                "total_assets": 1000,
                "total_liabilities": 1400,
                "shareholder_equity": -400,
                "retained_earnings": -900,
            },
        },
    )
    assert response.status_code == 201


def test_unbalanced_balance_sheet_is_rejected_with_the_residual(client, caterpillar):
    """Assets = liabilities + equity, or the upload does not land.

    Every ratio and every Altman component is scaled by total assets, so a single
    mistyped digit there would move the whole analysis by one consistent wrong
    factor and nothing downstream would look odd.
    """
    company_id = client.post("/companies", json=caterpillar["company"]).json()["id"]
    response = client.post(
        f"/companies/{company_id}/financial-statements",
        json={
            "statement_type": "BALANCE_SHEET",
            "line_items": {
                "total_assets": 87764,
                "total_liabilities": 68270,
                "shareholder_equity": 1949,  # a dropped digit: should be 19,494
            },
        },
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "does not balance" in detail
    assert "transcription error" in detail


def test_rounding_within_tolerance_still_balances(client, caterpillar):
    company_id = client.post("/companies", json=caterpillar["company"]).json()["id"]
    response = client.post(
        f"/companies/{company_id}/financial-statements",
        json={
            "statement_type": "BALANCE_SHEET",
            "line_items": {
                "total_assets": 87764,
                "total_liabilities": 68270,
                "shareholder_equity": 19497,  # 3m out on 87,764m: well inside 0.5%
            },
        },
    )
    assert response.status_code == 201


def test_missing_data_source_is_rejected(client):
    response = client.post(
        "/companies",
        json={"name": "No Provenance Ltd", "sector_class": "NON_MANUFACTURER"},
    )
    assert response.status_code == 422


def test_unknown_currency_is_rejected(client, caterpillar):
    payload = {**caterpillar["company"], "currency": "XYZ"}
    assert client.post("/companies", json=payload).status_code == 422


# --- Model overrides over HTTP ------------------------------------------------


def test_model_override_is_honoured_and_recorded(client, load_company, caterpillar):
    company_id = load_company(caterpillar)
    response = client.post(
        f"/companies/{company_id}/compute-bankruptcy-risk",
        json={"model": "Z_DOUBLE_PRIME"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["model"] == "Z_DOUBLE_PRIME"
    assert "explicitly overridden" in body["calculation_basis"]["model_selection"]


def test_emerging_market_constant_on_the_wrong_model_is_a_422(client, load_company, caterpillar):
    company_id = load_company(caterpillar)
    response = client.post(
        f"/companies/{company_id}/compute-bankruptcy-risk",
        json={"emerging_market_adjustment": True},
    )
    assert response.status_code == 422
    assert "only for Z''" in response.json()["detail"]


def test_financial_sector_company_gets_no_score_over_http(client, caterpillar):
    payload = {
        **caterpillar["company"],
        "name": "A Commercial Bank Ltd",
        "industry": "banking",
        "sector_class": "FINANCIAL",
    }
    company_id = client.post("/companies", json=payload).json()["id"]
    client.post(
        f"/companies/{company_id}/financial-statements",
        json=caterpillar["statements"][0],
    )
    body = client.post(f"/companies/{company_id}/compute-bankruptcy-risk", json={}).json()
    assert body["altman_z_score"] is None
    assert body["zone"] == "NOT_APPLICABLE"
    assert "excluded financial-sector issuers" in body["calculation_basis"]["model_selection"]


# --- Peer benchmarks ---------------------------------------------------------


def test_three_peers_in_one_industry_switch_the_benchmark_basis(client, caterpillar):
    """Loads four same-industry companies so the peer median has enough members."""
    ids = []
    for index in range(4):
        payload = {**caterpillar["company"], "name": f"Machinery Co {index}"}
        company_id = client.post("/companies", json=payload).json()["id"]
        for statement in caterpillar["statements"]:
            client.post(f"/companies/{company_id}/financial-statements", json=statement)
        client.post(f"/companies/{company_id}/compute-ratios")
        ids.append(company_id)

    health = client.post(f"/companies/{ids[0]}/compute-health-score").json()
    assert "PEER_SET" in health["calculation_basis"]["benchmark_bases_used"]


def test_line_items_endpoint_shows_the_engine_input(client, load_company, caterpillar):
    company_id = load_company(caterpillar)
    body = client.get(f"/companies/{company_id}/line-items").json()
    assert body["units"] == "MILLIONS"
    assert body["line_items"]["total_assets"] == 87764
    assert "operating_cash_flow" in body["line_items"], "merged across all three statements"


def test_deleting_a_company_cascades(client, load_company, caterpillar):
    company_id = load_company(caterpillar)
    client.post(f"/companies/{company_id}/run-full-analysis")
    assert client.delete(f"/companies/{company_id}").status_code == 204
    assert client.get(f"/companies/{company_id}").status_code == 404
