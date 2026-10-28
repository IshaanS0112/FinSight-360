"""Market data, regression beta, risk metrics and the Merton model.

# roadmap: v3-01-market-data
# roadmap: v3-02-merton

Values are checked against independent numpy computations on the sourced
price file, not against the functions under test.
"""

from __future__ import annotations

import json
import math
from statistics import NormalDist

import numpy as np
import pytest

from app.enums import ResultConfidence
from app.services.market_data import (
    PricePoint,
    align,
    estimate_beta,
    max_drawdown,
    risk_metrics,
    simple_returns,
)
from app.services.merton_model import (
    MertonInputs,
    compute_merton,
    default_point,
    market_view,
    naive_distance_to_default,
    solve_asset_value,
)
from tests.conftest import BACKEND_ROOT

MARKET_FILE = BACKEND_ROOT.parent / "data" / "market_data" / "prices_monthly.json"
N = NormalDist()


@pytest.fixture(scope="module")
def market():
    return json.loads(MARKET_FILE.read_text())["securities"]


@pytest.fixture(scope="module")
def prices(market):
    return {t: [PricePoint(**p) for p in s["prices"]] for t, s in market.items()}


def load_market(client, market, *tickers):
    for ticker in tickers:
        s = market[ticker]
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


# --- The sourced file -----------------------------------------------------------


def test_the_price_file_is_complete_and_dated(market):
    assert len(market) == 11
    for ticker, s in market.items():
        assert len(s["prices"]) == 72, ticker
        assert s["prices"][0]["date"] == "2019-01-31"
        assert s["prices"][-1]["date"] == "2024-12-31"


def test_caterpillar_year_end_close_matches_the_published_close(market):
    """$362.76 is Caterpillar's actual 31 December 2024 close."""
    last = market["CAT"]["prices"][-1]
    assert last["close"] == pytest.approx(362.76, abs=0.01)


# --- Returns, alignment, metrics -------------------------------------------------


def test_returns_use_adjusted_close_not_raw_close():
    """Dividends are part of the return; a raw-close return would understate it."""
    series = [PricePoint("2024-01-31", 100.0, 90.0), PricePoint("2024-02-29", 100.0, 99.0)]
    assert simple_returns(series) == [("2024-02-29", pytest.approx(0.10))]


def test_alignment_is_an_inner_join_on_dates():
    dates, matrix = align(
        {"a": [("2024-01", 0.1), ("2024-02", 0.2)], "b": [("2024-02", 0.3), ("2024-03", 0.4)]}
    )
    assert dates == ["2024-02"]
    assert matrix.tolist() == [[0.2, 0.3]]


def test_risk_metrics_match_an_independent_computation(prices):
    adj = np.array([p.adj_close for p in prices["CAT"]])
    rets = adj[1:] / adj[:-1] - 1
    m = risk_metrics(prices["CAT"], risk_free_annual=0.024, confidence=0.95, minimum=24).metrics

    assert m["annualised_volatility"] == pytest.approx(
        np.std(rets, ddof=1) * math.sqrt(12), abs=1e-6
    )
    expected_cagr = (adj[-1] / adj[0]) ** (12 / len(rets)) - 1
    assert m["annualised_return"] == pytest.approx(expected_cagr, abs=1e-6)
    peak = np.maximum.accumulate(adj)
    assert m["max_drawdown"] == pytest.approx(np.max(1 - adj / peak), abs=1e-6)
    assert m["historical_var"] == pytest.approx(-np.quantile(rets, 0.05), abs=1e-6)


def test_expected_shortfall_is_never_smaller_than_var(prices):
    """By definition the average tail loss is at least the loss at the tail's edge."""
    for ticker in ("CAT", "INFY", "IDEA.NS", "SPY"):
        m = risk_metrics(
            prices[ticker], risk_free_annual=0.024, confidence=0.95, minimum=24
        ).metrics
        assert m["expected_shortfall"] >= m["historical_var"] - 1e-12, ticker


def test_too_few_observations_is_a_refusal_not_a_statistic(prices):
    m = risk_metrics(prices["CAT"][:10], risk_free_annual=0.024, confidence=0.95, minimum=24)
    assert m.metrics == {}
    assert "24 are required" in m.reason


def test_max_drawdown_on_a_known_path():
    path = [PricePoint(f"2024-0{i}-28", 1, v) for i, v in enumerate([100, 120, 60, 90, 130], 1)]
    assert max_drawdown(path) == pytest.approx(0.5)


# --- Beta -----------------------------------------------------------------------


def test_beta_matches_an_independent_regression(prices):
    asset, market = simple_returns(prices["CAT"]), simple_returns(prices["SPY"])
    y = np.array([r for _, r in asset]) - 0.002
    x = np.array([r for _, r in market]) - 0.002
    slope = np.polyfit(x, y, 1)[0]

    result = estimate_beta(asset, market, 0.024, 24)
    assert result.beta == pytest.approx(slope, abs=1e-4)
    assert result.adjusted_beta == pytest.approx(0.67 * result.beta + 0.33, abs=1e-4)
    assert 0 < result.r_squared < 1


def test_beta_refuses_with_too_little_overlap(prices):
    result = estimate_beta(
        simple_returns(prices["CAT"][:12]), simple_returns(prices["SPY"]), 0.0, 24
    )
    assert result.beta is None
    assert "overlapping observations" in result.reason


# --- Merton ---------------------------------------------------------------------


def test_the_kmv_default_point_is_short_term_plus_half_long_term():
    point, basis = default_point(total_debt=38409.0, long_term_debt=27351.0)
    assert point == pytest.approx((38409 - 27351) + 0.5 * 27351)
    assert basis == "KMV_SHORT_PLUS_HALF_LONG"


def test_without_a_debt_split_the_default_point_falls_back_conservatively():
    """All debt treated as due: overstates the default point, so overstates PD."""
    point, basis = default_point(total_debt=2438090.0, long_term_debt=None)
    assert point == 2438090.0
    assert basis == "TOTAL_DEBT_NO_SPLIT"


def test_the_solver_satisfies_both_merton_equations():
    """Round trip: the solved V and sigma_V must reproduce observed E and sigma_E."""
    inputs = MertonInputs(1000.0, 0.40, 800.0, 0.04, 1.0)
    v, sv, ok, _ = solve_asset_value(inputs)
    assert ok
    d1 = (math.log(v / 800) + (0.04 + 0.5 * sv**2)) / sv
    d2 = d1 - sv
    equity = v * N.cdf(d1) - 800 * math.exp(-0.04) * N.cdf(d2)
    assert equity == pytest.approx(1000.0, rel=1e-6)
    assert N.cdf(d1) * sv * v == pytest.approx(0.40 * 1000.0, rel=1e-6)


def test_more_leverage_means_a_shorter_distance_to_default():
    low = compute_merton(MertonInputs(1000.0, 0.35, 300.0, 0.04, 1.0))
    high = compute_merton(MertonInputs(1000.0, 0.35, 3000.0, 0.04, 1.0))
    assert high.distance_to_default < low.distance_to_default
    assert high.probability_of_default > low.probability_of_default


def test_the_naive_model_matches_its_published_formula():
    inputs = MertonInputs(1000.0, 0.40, 500.0, 0.04, 1.0, prior_year_equity_return=0.10)
    dd, pd = naive_distance_to_default(inputs)
    sigma_v = 1000 / 1500 * 0.40 + 500 / 1500 * (0.05 + 0.25 * 0.40)
    expected = (math.log(1500 / 500) + (0.10 - 0.5 * sigma_v**2)) / sigma_v
    assert dd == pytest.approx(expected, abs=1e-9)
    assert pd == pytest.approx(N.cdf(-expected), abs=1e-12)


def test_no_inputs_is_a_refusal_with_its_reason():
    result = compute_merton(None, "No debt figure.")
    assert result.distance_to_default is None
    assert result.confidence is ResultConfidence.UNUSABLE
    assert result.calculation_basis["refusal"] == "No debt figure."


@pytest.mark.parametrize(
    ("consensus", "pd", "view"),
    [
        ("LOW_RISK", 0.0001, "CONFIRMS"),
        ("HIGH_RISK", 0.20, "CONFIRMS"),
        ("LOW_RISK", 0.20, "CONTRADICTS"),
        ("HIGH_RISK", 0.0001, "CONTRADICTS"),
        ("MIXED_SIGNAL", 0.02, "PARTIAL"),
        ("INDETERMINATE", 0.02, "UNAVAILABLE"),
        (None, 0.02, "UNAVAILABLE"),
    ],
)
def test_the_market_view_against_the_accounting_consensus(consensus, pd, view):
    assert market_view(consensus, pd, 0.005, 0.05)[0] == view


# --- Over HTTP ------------------------------------------------------------------


def test_securities_load_and_list_with_coverage(client, market):
    load_market(client, market, "CAT", "SPY")
    listed = {s["ticker"]: s for s in client.get("/market/securities").json()}
    assert listed["CAT"]["observations"] == 72
    assert listed["CAT"]["last_date"] == "2024-12-31"


def test_posting_a_security_again_replaces_its_history(client, market):
    load_market(client, market, "CAT")
    body = client.get("/market/securities/CAT").json()
    trimmed = {**body, "source": "test", "prices": body["prices"][:30]}
    client.post("/market/securities", json=trimmed)
    assert client.get("/market/securities/CAT").json()["observations"] == 30


def test_a_listing_needs_a_price_history(client, load_company, caterpillar):
    company_id = load_company(caterpillar)
    response = client.put(f"/companies/{company_id}/listing", json={"ticker": "NOPE"})
    assert response.status_code == 422
    assert "POST /market/securities first" in response.json()["detail"]


def test_market_risk_without_a_listing_is_a_conflict(client, load_company, caterpillar):
    company_id = load_company(caterpillar)
    response = client.post(f"/companies/{company_id}/compute-market-risk")
    assert response.status_code == 409


def test_caterpillar_market_risk_confirms_the_accounting_view(
    client, load_company, caterpillar, market
):
    load_market(client, market, "CAT", "SPY")
    company_id = load_company(caterpillar)
    client.post(
        f"/companies/{company_id}/financial-statements",
        json={
            "statement_type": "BALANCE_SHEET",
            "line_items": {"shares_outstanding": 477.9, "long_term_debt": 27351},
        },
    )
    client.put(
        f"/companies/{company_id}/listing", json={"ticker": "CAT", "fiscal_year_end_month": 12}
    )
    client.post(f"/companies/{company_id}/compute-bankruptcy-risk", json={})

    body = client.post(f"/companies/{company_id}/compute-market-risk").json()
    assert body["merton_distance_to_default"] == pytest.approx(6.36, abs=0.05)
    assert body["merton_probability_of_default"] < 1e-6
    assert body["market_view"] == "CONFIRMS"
    assert body["adjusted_beta"] == pytest.approx(0.67 * body["beta"] + 0.33, abs=1e-4)
    basis = body["calculation_basis"]
    assert basis["fiscal_year_end"] == "2024-12-31"
    assert basis["merton"]["equity_value_basis"] == "SHARES_X_FISCAL_YEAR_END_CLOSE"
    assert basis["merton"]["gap_vs_reported_pct"] == pytest.approx(-2.35, abs=0.05)


def test_market_statistics_never_look_past_the_fiscal_year_end(
    client, load_company, infosys, market
):
    """Infosys reports to March. A FY2024 analysis must not see April 2024 prices."""
    load_market(client, market, "INFY", "SPY")
    company_id = load_company(infosys)
    client.put(
        f"/companies/{company_id}/listing", json={"ticker": "INFY", "fiscal_year_end_month": 3}
    )
    body = client.post(f"/companies/{company_id}/compute-market-risk").json()
    assert body["calculation_basis"]["fiscal_year_end"] == "2024-03-31"
    assert body["calculation_basis"]["beta"]["observations"] <= 60


def test_a_cross_currency_beta_is_refused(client, load_company, vodafone_idea, market):
    load_market(client, market, "IDEA.NS", "SPY")
    company_id = load_company(vodafone_idea)
    client.put(
        f"/companies/{company_id}/listing", json={"ticker": "IDEA.NS", "fiscal_year_end_month": 3}
    )
    body = client.post(f"/companies/{company_id}/compute-market-risk").json()
    assert body["beta"] is None
    assert "exchange-rate risk" in body["calculation_basis"]["beta"]["reason"]
    assert body["merton_probability_of_default"] > 0.05, "the market agrees it is distressed"


def test_the_dcf_uses_a_regression_beta_when_a_listing_exists(
    client, load_company, caterpillar, market
):
    load_market(client, market, "CAT", "SPY")
    company_id = load_company(caterpillar)
    client.post(
        f"/companies/{company_id}/financial-statements",
        json={"statement_type": "CASH_FLOW", "line_items": {"depreciation_amortization": 2153}},
    )
    client.put(f"/companies/{company_id}/listing", json={"ticker": "CAT"})

    measured = client.post(f"/companies/{company_id}/compute-valuation", json={}).json()
    assert measured["calculation_basis"]["beta_source"]["source"] == "REGRESSION"
    assert measured["assumptions"]["beta"] != 1.0

    declared = client.post(f"/companies/{company_id}/compute-valuation", json={"beta": 0.9}).json()
    assert declared["assumptions"]["beta"] == 0.9
    assert declared["calculation_basis"]["beta_source"]["source"] == "REQUEST"
