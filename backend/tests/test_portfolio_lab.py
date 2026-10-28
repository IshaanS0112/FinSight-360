"""Portfolio Lab: estimators, optimisers, HRP, risk decomposition, credit overlay.

# roadmap: v3-03-portfolio-lab

Each optimiser is checked against a property it must satisfy or an analytical
answer, not against its own output.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from app.schemas.market import PortfolioRequest
from app.services import portfolio_optimizer as opt
from app.services.portfolio_pipeline import PortfolioError, weight_caps
from tests.conftest import BACKEND_ROOT

MARKET_FILE = BACKEND_ROOT.parent / "data" / "market_data" / "prices_monthly.json"
USD_UNIVERSE = ["CAT", "DE", "AGCO", "PCAR", "INFY", "ACN", "CTSH", "WIT", "EPAM"]


def estimates(mu, cov) -> opt.Estimates:
    return opt.Estimates(mu=np.array(mu, dtype=float), cov=np.array(cov, dtype=float))


@pytest.fixture
def loaded(client):
    market = json.loads(MARKET_FILE.read_text())["securities"]
    for ticker, s in market.items():
        client.post(
            "/market/securities",
            json={
                "ticker": ticker,
                "name": s["name"],
                "currency": s["currency"],
                "exchange": s["exchange"],
                "sector": s["sector"],
                "source": "Yahoo Finance chart API",
                "prices": s["prices"],
            },
        )
    return client


# --- Estimators -----------------------------------------------------------------


def test_mean_historical_is_the_compounded_annual_return():
    r = np.array([[0.01, 0.02]] * 24)
    universe = opt.Universe(["A", "B"], [str(i) for i in range(24)], r)
    mu, _ = opt.expected_returns(universe, "mean_historical", 0.0, 24)
    assert mu == pytest.approx([1.01**12 - 1, 1.02**12 - 1])


def test_capm_puts_the_benchmark_itself_on_the_market_return():
    rng = np.random.default_rng(1)
    market = rng.normal(0.008, 0.04, 60)
    universe = opt.Universe(["M"], [str(i) for i in range(60)], market[:, None], benchmark=market)
    mu, detail = opt.expected_returns(universe, "capm", 0.02, 24)
    assert mu[0] == pytest.approx(detail["market_return"], abs=1e-6)


def test_ledoit_wolf_shrinks_toward_constant_variance_and_preserves_the_trace():
    rng = np.random.default_rng(7)
    r = rng.normal(0, 0.05, size=(60, 6))
    shrunk, shrinkage = opt.ledoit_wolf(r)
    x = r - r.mean(axis=0)
    sample = np.einsum("ti,tj->ij", x, x) / len(r)
    assert 0 <= shrinkage <= 1
    assert np.trace(shrunk) == pytest.approx(np.trace(sample))


def test_ledoit_wolf_is_invertible_where_the_sample_covariance_is_not():
    """With fewer observations than assets the sample matrix is singular."""
    rng = np.random.default_rng(3)
    r = rng.normal(0, 0.05, size=(8, 12))
    x = r - r.mean(axis=0)
    assert np.linalg.matrix_rank(np.einsum("ti,tj->ij", x, x)) < 12
    shrunk, _ = opt.ledoit_wolf(r)
    assert np.linalg.matrix_rank(shrunk) == 12


def test_a_non_positive_semidefinite_matrix_is_repaired_and_flagged():
    bad = np.array([[1.0, 2.0], [2.0, 1.0]])
    fixed, was_fixed = opt.make_psd(bad)
    assert was_fixed
    assert np.linalg.eigvalsh(fixed).min() >= -1e-12


# --- Optimisers -----------------------------------------------------------------


def test_min_volatility_of_two_uncorrelated_assets_is_inverse_variance():
    est = estimates([0.1, 0.1], [[0.04, 0.0], [0.0, 0.16]])
    w = opt.min_volatility(est, np.array([1.0, 1.0]))
    assert w == pytest.approx([0.8, 0.2], abs=1e-5)


def test_max_sharpe_beats_every_other_long_only_portfolio_in_sample():
    rng = np.random.default_rng(11)
    r = rng.normal(0.01, 0.05, size=(72, 5)) + rng.normal(0, 0.003, 5)
    universe = opt.Universe(list("ABCDE"), [str(i) for i in range(72)], r)
    est = opt.estimate(universe, "mean_historical", "sample", 0.02, 24)
    caps = np.ones(5)
    best = opt.performance(opt.max_sharpe(est, caps, 0.02), est, 0.02)["sharpe_ratio"]
    for w in (opt.min_volatility(est, caps), np.full(5, 0.2), opt.hrp(r, est.cov)[0]):
        assert best >= opt.performance(w, est, 0.02)["sharpe_ratio"] - 1e-6


def test_weight_caps_are_respected():
    est = estimates([0.30, 0.05, 0.04], np.diag([0.04, 0.04, 0.04]))
    w = opt.max_sharpe(est, np.array([0.4, 1.0, 1.0]), 0.0)
    assert w[0] <= 0.4 + 1e-9
    assert w.sum() == pytest.approx(1.0)


def test_efficient_return_hits_its_target():
    est = estimates([0.05, 0.10, 0.15], np.diag([0.01, 0.04, 0.09]))
    w = opt.efficient_return(est, np.ones(3), 0.12)
    assert float(w @ est.mu) == pytest.approx(0.12, abs=1e-6)


def test_hrp_of_two_assets_is_inverse_variance():
    rng = np.random.default_rng(5)
    r = rng.normal(0, [0.02, 0.06], size=(120, 2))
    cov = np.cov(r, rowvar=False)
    w, _ = opt.hrp(r, cov)
    inverse = 1 / np.diag(cov)
    assert w == pytest.approx(inverse / inverse.sum(), abs=1e-9)


def test_frontier_volatility_rises_with_return():
    est = estimates(
        [0.05, 0.10, 0.15], [[0.01, 0.002, 0.0], [0.002, 0.04, 0.01], [0.0, 0.01, 0.09]]
    )
    curve = opt.frontier(est, np.ones(3), 10)
    vols = [p["volatility"] for p in curve]
    assert all(b >= a - 1e-6 for a, b in zip(vols, vols[1:], strict=False))


def test_component_var_sums_to_portfolio_var():
    """Euler allocation: the parts must add back up to the whole, exactly."""
    cov = np.array([[0.0025, 0.0010, 0.0], [0.0010, 0.0040, 0.0005], [0.0, 0.0005, 0.0016]])
    w = np.array([0.5, 0.3, 0.2])
    result = opt.component_var(w, cov, ["A", "B", "C"], 0.95)
    total = sum(c["component_var"] for c in result["components"])
    assert total == pytest.approx(result["portfolio_var"], abs=1e-6)
    assert sum(c["share_of_risk"] for c in result["components"]) == pytest.approx(1.0, abs=1e-5)


def test_discrete_allocation_never_overspends_and_leaves_less_than_one_share():
    w = np.array([0.5, 0.3, 0.2])
    prices = np.array([123.45, 67.8, 250.0])
    result = opt.discrete_allocation(w, prices, ["A", "B", "C"], 10_000)
    spent = sum(result["shares"].get(t, 0) * p for t, p in zip("ABC", prices, strict=True))
    assert spent <= 10_000
    assert result["leftover_cash"] < prices.min()


def test_random_portfolios_are_reproducible_from_the_seed():
    est = estimates([0.1, 0.2], [[0.04, 0.0], [0.0, 0.09]])
    assert opt.random_portfolios(est, 50, 9) == opt.random_portfolios(est, 50, 9)


# --- Credit overlay -------------------------------------------------------------


def test_the_credit_overlay_excludes_high_risk_and_caps_mixed_signal():
    request = PortfolioRequest(tickers=["A", "B", "C", "D"], credit_overlay="cap_mixed")
    views = {
        "A": {"company": "Alpha", "consensus": "HIGH_RISK"},
        "B": {"company": "Beta", "consensus": "MIXED_SIGNAL"},
        "C": {"company": "Gamma", "consensus": "LOW_RISK"},
    }
    caps, constrained = weight_caps(request, views)
    assert caps.tolist() == [0.0, 0.10, 1.0, 1.0]
    assert {c["ticker"] for c in constrained} == {"A", "B"}


def test_caps_that_cannot_reach_full_investment_are_refused():
    request = PortfolioRequest(tickers=["A", "B", "C"], max_weight=0.2)
    with pytest.raises(PortfolioError, match="sum to 60%"):
        weight_caps(request, {})


# --- Over HTTP ------------------------------------------------------------------


def test_every_optimiser_runs_side_by_side_on_the_sourced_universe(loaded):
    response = loaded.post(
        "/portfolio/optimize", json={"tickers": USD_UNIVERSE, "budget": 100000, "max_weight": 0.35}
    )
    assert response.status_code == 201
    results = response.json()["results"]
    assert set(results["portfolios"]) == {
        "min_volatility",
        "max_sharpe",
        "hrp",
        "equal_weight",
        "inverse_volatility",
    }
    for name, p in results["portfolios"].items():
        # Each weight is rounded to 6 dp, so nine of them can drift by 4.5e-6.
        assert sum(p["weights"].values()) == pytest.approx(1.0, abs=1e-5), name
    assert len(results["frontier"]) > 10
    assert results["allocation"]["leftover_cash"] < 1000
    assert results["universe"]["observations"] == 71


def test_hrp_separates_the_two_sectors_in_the_sourced_universe(loaded):
    """Machinery and IT services should land in different branches of the tree."""
    results = loaded.post("/portfolio/optimize", json={"tickers": USD_UNIVERSE}).json()["results"]
    order = [USD_UNIVERSE[i] for i in results["portfolios"]["hrp"]["tree"]["order"]]
    machinery = {"CAT", "DE", "AGCO", "PCAR"}
    first_four = set(order[:4])
    assert first_four == machinery or first_four.isdisjoint(machinery)


def test_a_mixed_currency_universe_is_refused(loaded):
    response = loaded.post("/portfolio/optimize", json={"tickers": ["CAT", "IDEA.NS"]})
    assert response.status_code == 422
    assert "exchange-rate risk" in response.json()["detail"]


def test_too_short_a_history_is_refused(loaded):
    response = loaded.post(
        "/portfolio/optimize", json={"tickers": ["CAT", "DE"], "start_date": "2023-01-01"}
    )
    assert response.status_code == 422
    assert "overlapping monthly returns" in response.json()["detail"]


def test_an_unreachable_risk_free_rate_refuses_only_the_tangency_portfolio(loaded):
    body = loaded.post(
        "/portfolio/optimize", json={"tickers": ["CAT", "DE", "ACN"], "risk_free_rate": 0.45}
    ).json()["results"]
    assert "does not exist" in body["portfolios"]["max_sharpe"]["refusal"]
    assert "weights" in body["portfolios"]["min_volatility"]
    assert body["risk_decomposition"]["portfolio"] == "min_volatility"


def test_runs_are_stored_and_retrievable(loaded):
    created = loaded.post(
        "/portfolio/optimize", json={"tickers": ["CAT", "DE"], "name": "pair"}
    ).json()
    assert loaded.get(f"/portfolio/runs/{created['id']}").json()["name"] == "pair"
    assert loaded.get("/portfolio/runs").json()[0]["id"] == created["id"]
    assert loaded.get("/portfolio/runs/00000000-0000-0000-0000-000000000999").status_code == 404
