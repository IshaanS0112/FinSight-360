"""Portfolio Lab orchestration: universe in, every optimiser side by side out.

The credit overlay is what this module adds beyond the libraries it borrows from:
a holding whose own company FinSight has scored HIGH_RISK can be excluded, and a
MIXED_SIGNAL one capped, before any optimiser runs.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import CompanyListing, PortfolioRun, Security
from app.schemas.market import PortfolioRequest
from app.services import portfolio_optimizer as opt
from app.services.market_data import align, simple_returns
from app.services.market_pipeline import price_series_from, up_to

MIXED_SIGNAL_CAP = 0.10


class PortfolioError(ValueError):
    """A request the optimiser cannot honestly answer. The message says why."""


def build_universe(db: Session, request: PortfolioRequest, settings: Settings):
    """Aligned monthly returns for the requested tickers, or a refusal."""
    securities = [db.get(Security, t) for t in request.tickers]
    missing = [t for t, s in zip(request.tickers, securities, strict=True) if s is None]
    if missing:
        raise PortfolioError(f"No price history for {missing}. POST /market/securities first.")

    currencies = {s.currency for s in securities}
    if len(currencies) > 1:
        raise PortfolioError(
            f"The universe mixes currencies {sorted(currencies)}. Adding rupee returns to "
            "dollar returns ignores exchange-rate risk entirely, so the optimiser refuses."
        )

    series = {}
    for s in securities:
        prices = [
            p
            for p in price_series_from(s)
            if request.start_date is None or p.date >= request.start_date
        ]
        series[s.ticker] = simple_returns(up_to(prices, request.end_date or "9999-12-31"))
    dates, matrix = align(series)
    if len(dates) < settings.portfolio_min_observations:
        raise PortfolioError(
            f"{len(dates)} overlapping monthly returns; {settings.portfolio_min_observations} "
            "are required for a covariance matrix worth optimising against."
        )

    benchmark = _benchmark_returns(db, request, settings, dates)
    last_prices = np.array([price_series_from(s)[-1].close for s in securities])
    return opt.Universe(request.tickers, dates, matrix, benchmark), currencies.pop(), last_prices


def _benchmark_returns(db, request, settings, dates) -> np.ndarray | None:
    ticker = request.benchmark_ticker or settings.market_benchmark_ticker
    bench = db.get(Security, ticker)
    if bench is None:
        return None
    lookup = dict(simple_returns(price_series_from(bench)))
    if not all(d in lookup for d in dates):
        return None
    return np.array([lookup[d] for d in dates])


def credit_views(db: Session, tickers: list[str]) -> dict[str, dict[str, Any]]:
    """FinSight's own verdict on any holding that is a company it has analysed."""
    views = {}
    listings = db.scalars(select(CompanyListing).where(CompanyListing.ticker.in_(tickers))).all()
    for listing in listings:
        company = listing.company
        risk = company.bankruptcy_risks[-1] if company.bankruptcy_risks else None
        market = company.market_risks[-1] if company.market_risks else None
        views[listing.ticker] = {
            "company": company.name,
            "consensus": risk.consensus_verdict if risk else None,
            "merton_pd": market.merton_probability_of_default if market else None,
        }
    return views


def weight_caps(request: PortfolioRequest, views: dict) -> tuple[np.ndarray, list[dict]]:
    """Per-asset upper bounds from max_weight and the credit overlay."""
    caps, constrained = [], []
    for ticker in request.tickers:
        cap, view = request.max_weight, views.get(ticker, {})
        verdict = view.get("consensus")
        if request.credit_overlay != "none" and verdict == "HIGH_RISK":
            cap = 0.0
            constrained.append(
                {"ticker": ticker, "cap": 0.0, "reason": f"{view['company']} is HIGH_RISK"}
            )
        elif request.credit_overlay == "cap_mixed" and verdict == "MIXED_SIGNAL":
            cap = min(cap, MIXED_SIGNAL_CAP)
            constrained.append(
                {"ticker": ticker, "cap": cap, "reason": f"{view['company']} is MIXED_SIGNAL"}
            )
        caps.append(cap)
    caps = np.array(caps)
    if caps.sum() < 1 - 1e-9:
        raise PortfolioError(
            f"The weight caps sum to {caps.sum():.0%}, so no portfolio can be fully invested. "
            "Raise max_weight, add assets, or relax the credit overlay."
        )
    return caps, constrained


def _portfolio(weights: np.ndarray | None, est, rf, tickers, refusal: str) -> dict[str, Any]:
    if weights is None:
        return {"refusal": refusal}
    return {
        "weights": {t: round(float(w), 6) for t, w in zip(tickers, weights, strict=True)},
        **opt.performance(weights, est, rf),
    }


def run_portfolio(db: Session, settings: Settings, request: PortfolioRequest) -> PortfolioRun:
    universe, currency, last_prices = build_universe(db, request, settings)
    rf = (
        request.risk_free_rate
        if request.risk_free_rate is not None
        else settings.market_risk_free_rate
    )
    est = opt.estimate(
        universe,
        request.expected_returns,
        request.risk_model,
        rf,
        settings.portfolio_ema_span_months,
    )
    views = credit_views(db, request.tickers)
    caps, constrained = weight_caps(request, views)
    t = request.tickers

    sharpe_refusal = (
        "No asset's expected return exceeds the risk-free rate, so the tangency portfolio "
        "does not exist."
        if float(est.mu.max()) <= rf
        else "The optimiser did not converge."
    )
    hrp_weights, tree = opt.hrp(universe.returns, est.cov)
    portfolios = {
        "min_volatility": _portfolio(opt.min_volatility(est, caps), est, rf, t, "did not converge"),
        "max_sharpe": _portfolio(
            opt.max_sharpe(est, caps, rf) if float(est.mu.max()) > rf else None,
            est,
            rf,
            t,
            sharpe_refusal,
        ),
        "hrp": {**_portfolio(hrp_weights, est, rf, t, ""), "tree": tree},
        "equal_weight": _portfolio(np.full(len(t), 1 / len(t)), est, rf, t, ""),
        "inverse_volatility": _portfolio(_inverse_vol(est), est, rf, t, ""),
    }
    if request.target_return is not None:
        portfolios["efficient_return"] = _portfolio(
            opt.efficient_return(est, caps, request.target_return),
            est,
            rf,
            t,
            f"A {request.target_return:.1%} return is not reachable long-only within the caps.",
        )

    headline = "max_sharpe" if "weights" in portfolios["max_sharpe"] else "min_volatility"
    w = np.array([portfolios[headline]["weights"][x] for x in t])
    monthly_cov = est.cov / opt.PERIODS
    results = {
        "universe": {
            "tickers": t,
            "currency": currency,
            "start": universe.dates[0],
            "end": universe.dates[-1],
            "observations": len(universe.dates),
        },
        "assets": [
            {
                "ticker": x,
                "expected_return": round(float(est.mu[i]), 6),
                "volatility": round(float(np.sqrt(est.cov[i, i])), 6),
                "credit_view": views.get(x),
            }
            for i, x in enumerate(t)
        ],
        "correlation": np.corrcoef(universe.returns, rowvar=False).round(4).tolist(),
        "portfolios": portfolios,
        "frontier": opt.frontier(est, caps, settings.portfolio_frontier_points),
        "random_portfolios": opt.random_portfolios(
            est, settings.portfolio_random_portfolios, settings.portfolio_seed
        ),
        "risk_decomposition": {
            "portfolio": headline,
            **opt.component_var(w, monthly_cov, t, settings.market_var_confidence),
        },
        "allocation": opt.discrete_allocation(w, last_prices, t, request.budget)
        if request.budget
        else None,
        "credit_overlay": {
            "mode": request.credit_overlay,
            "constrained": constrained,
            "linked": sorted(views),
            "unlinked": [x for x in t if x not in views],
        },
    }
    row = PortfolioRun(
        name=request.name,
        tickers=t,
        config=request.model_dump(),
        results=results,
        calculation_basis=_basis(est, rf, headline),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _inverse_vol(est) -> np.ndarray:
    inverse = 1 / np.sqrt(np.diag(est.cov))
    return inverse / inverse.sum()


def _basis(est, rf: float, headline: str) -> dict[str, Any]:
    return {
        "estimation": est.detail,
        "risk_free_rate": rf,
        "constraints": "long-only, fully invested, per-asset caps",
        "headline_portfolio": headline,
        "citations": opt.CITATIONS,
        "inspired_by": ["PyPortfolio/PyPortfolioOpt", "letianzj/QuantResearch"],
        "hrp_note": "HRP takes no weight cap by construction; the caps apply to the mean-variance optimisers.",
        "interpretation_limit": (
            "Every figure is in-sample: the optimiser is fitted to the same history it is "
            "scored on, which flatters every Sharpe ratio here. The universe was chosen in "
            "2026 and every member still trades, so it has never seen a failure. Treat the "
            "weights as a description of the past, not a forecast."
        ),
    }
