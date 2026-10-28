"""Read-only summary endpoints the V3 frontend is built on.

# roadmap: v3-05-frontend

The index page and the Portfolio Lab history each need a few headline figures
per row. These endpoints return exactly those, in one request, and must agree
with the full records they summarise.
"""

from __future__ import annotations

import json

from tests.conftest import BACKEND_ROOT

MARKET_FILE = BACKEND_ROOT.parent / "data" / "market_data" / "prices_monthly.json"


def load_market(client, *tickers):
    securities = json.loads(MARKET_FILE.read_text())["securities"]
    for ticker in tickers:
        s = securities[ticker]
        body = {
            "ticker": ticker,
            "name": s["name"],
            "currency": s["currency"],
            "exchange": s["exchange"],
            "sector": s["sector"],
            "source": "Yahoo Finance chart API, monthly",
            "prices": s["prices"],
        }
        assert client.post("/market/securities", json=body).status_code == 201


def test_the_index_summary_carries_each_stage_headline(client, load_company, caterpillar):
    load_market(client, "CAT", "SPY")
    company_id = load_company(caterpillar)
    client.put(f"/companies/{company_id}/listing", json={"ticker": "CAT"})
    client.post(f"/companies/{company_id}/run-full-analysis")
    client.post(f"/companies/{company_id}/compute-market-risk")

    row = client.get("/companies/summary").json()[0]
    risk = client.get(f"/companies/{company_id}/bankruptcy-risk").json()
    health = client.get(f"/companies/{company_id}/health-score").json()
    market = client.get(f"/companies/{company_id}/market-risk").json()

    assert row["id"] == company_id
    assert row["ticker"] == "CAT"
    assert row["consensus_verdict"] == risk["consensus_verdict"] == "LOW_RISK"
    assert row["altman_model"] == risk["model"]
    assert row["altman_zone"] == risk["zone"]
    assert row["health_score"] == health["overall_score"]
    assert row["market_view"] == market["market_view"]
    assert row["merton_probability_of_default"] == market["merton_probability_of_default"]


def test_a_company_with_no_analysis_is_listed_with_nulls(client, load_company, infosys):
    load_company(infosys)
    response = client.get("/companies/summary")
    assert response.status_code == 200
    row = response.json()[0]
    assert row["name"] == "Infosys Limited"
    for field in ("ticker", "consensus_verdict", "altman_zone", "health_score", "market_view"):
        assert row[field] is None


def test_the_summary_route_is_not_parsed_as_a_company_id(client):
    assert client.get("/companies/summary").status_code == 200
    assert client.get("/companies/summary").json() == []


def test_run_summaries_match_the_headline_portfolio_without_the_cloud(client):
    load_market(client, "CAT", "DE", "INFY", "ACN")
    created = client.post(
        "/portfolio/optimize", json={"tickers": ["CAT", "DE", "INFY", "ACN"], "name": "four"}
    ).json()
    headline = created["calculation_basis"]["headline_portfolio"]
    figures = created["results"]["portfolios"][headline]

    response = client.get("/portfolio/runs/summary")
    row = response.json()[0]
    assert row["id"] == created["id"]
    assert row["name"] == "four"
    assert row["headline_portfolio"] == headline
    assert row["expected_return"] == figures["expected_return"]
    assert row["volatility"] == figures["volatility"]
    assert row["sharpe_ratio"] == figures["sharpe_ratio"]
    assert "results" not in row
    assert len(response.content) < len(json.dumps(created)) / 20


def test_run_summaries_respect_the_limit(client):
    load_market(client, "CAT", "DE")
    for name in ("first", "second"):
        client.post("/portfolio/optimize", json={"tickers": ["CAT", "DE"], "name": name})
    rows = client.get("/portfolio/runs/summary", params={"limit": 1}).json()
    assert [row["name"] for row in rows] == ["second"]


def test_the_template_narrative_prints_no_raw_python_structures(
    client, load_company, vodafone_idea
):
    """The fallback text is shown verbatim in the UI, so a dict repr is a visible defect."""
    company_id = load_company(vodafone_idea)
    report = client.post(f"/companies/{company_id}/run-full-analysis").json()
    summary = report["ai_narrative"]["executive_summary"]
    assert "{" not in summary and "None" not in summary
    assert "leverage not scored" in summary
