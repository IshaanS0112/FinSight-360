"""Market orchestration: price history in, Merton DD, beta and risk metrics out.

Every statistic is computed on prices up to the company's fiscal year end, never
after it. A FY2024 analysis must not see a FY2025 price.
"""

from __future__ import annotations

import calendar
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.enums import ResultConfidence
from app.models import Company, MarketPrice, MarketRisk, Security
from app.services import line_items as li
from app.services.analysis_pipeline import latest_fiscal_year, merged_line_items
from app.services.market_data import (
    BetaResult,
    PricePoint,
    annualised_volatility,
    estimate_beta,
    price_at,
    risk_metrics,
    simple_returns,
    window,
)
from app.services.merton_model import (
    MertonInputs,
    MertonResult,
    compute_merton,
    default_point,
    market_view,
)


def price_series_from(security: Security) -> list[PricePoint]:
    return [PricePoint(p.price_date, p.close, p.adj_close) for p in security.prices]


def price_series(db: Session, ticker: str) -> list[PricePoint]:
    rows = db.scalars(
        select(MarketPrice).where(MarketPrice.ticker == ticker).order_by(MarketPrice.price_date)
    ).all()
    return [PricePoint(r.price_date, r.close, r.adj_close) for r in rows]


def fiscal_year_end(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}-{calendar.monthrange(year, month)[1]:02d}"


def up_to(prices: list[PricePoint], end: str, months: int | None = None) -> list[PricePoint]:
    """Prices on or before end; with months, the last months+1 of them (months returns)."""
    picked = [p for p in prices if p.date <= end]
    return picked[-(months + 1) :] if months else picked


def compute_beta(
    db: Session, settings: Settings, ticker: str, benchmark: str, end: str
) -> BetaResult:
    """Regression beta over the configured window, or a reason it cannot be estimated."""
    security, bench = db.get(Security, ticker), db.get(Security, benchmark)
    if bench is None:
        return BetaResult(beta=None, reason=f"benchmark {benchmark} has no price history")
    if security is not None and security.currency != bench.currency:
        return BetaResult(
            beta=None,
            reason=(
                f"{ticker} trades in {security.currency} and {benchmark} in {bench.currency}. "
                "A beta across currencies mixes market risk with exchange-rate risk."
            ),
        )
    months = settings.market_beta_window_months
    asset = simple_returns(up_to(price_series(db, ticker), end, months))
    market = simple_returns(up_to(price_series(db, benchmark), end, months))
    return estimate_beta(
        asset, market, settings.market_risk_free_rate, settings.market_min_observations
    )


def _equity_value(
    items: dict[str, float], fye_price: PricePoint | None
) -> tuple[float | None, str]:
    shares = li.get(items, "shares_outstanding")
    if shares is not None and fye_price is not None:
        return shares * fye_price.close, "SHARES_X_FISCAL_YEAR_END_CLOSE"
    reported = li.get(items, "market_value_equity")
    if reported is not None:
        return reported, "REPORTED_MARKET_VALUE_EQUITY"
    return None, "UNAVAILABLE"


def _merton_inputs(
    items: dict[str, float], prices: list[PricePoint], fye: str, rate: float, settings: Settings
) -> tuple[MertonInputs | None, str, dict[str, Any]]:
    """Assemble Merton inputs, or the reason they cannot be assembled."""
    equity, equity_basis = _equity_value(items, price_at(prices, fye))
    point, point_basis = default_point(li.get(items, "total_debt"), li.get(items, "long_term_debt"))
    vol_returns = [
        r for _, r in window(simple_returns(prices), fye, settings.merton_volatility_months)
    ]
    prior = [r for _, r in window(simple_returns(prices), fye, 12)]
    detail = {
        "equity_value_basis": equity_basis,
        "default_point_basis": point_basis,
        "volatility_window_months": len(vol_returns),
    }
    if equity is None or equity <= 0:
        return (
            None,
            "No market value of equity: neither shares x close nor a reported figure.",
            detail,
        )
    if point is None or point <= 0:
        return None, "No debt figure, so there is no default point to measure distance to.", detail
    if len(vol_returns) < settings.merton_min_volatility_months:
        return (
            None,
            f"{len(vol_returns)} monthly returns before the fiscal year end; too few.",
            detail,
        )

    growth = 1.0
    for r in prior:
        growth *= 1.0 + r
    inputs = MertonInputs(
        equity_value=equity,
        equity_volatility=annualised_volatility(vol_returns),
        default_point=point,
        risk_free_rate=rate,
        horizon_years=settings.merton_horizon_years,
        prior_year_equity_return=growth - 1.0 if len(prior) == 12 else None,
    )
    reported = li.get(items, "market_value_equity")
    if reported and equity_basis == "SHARES_X_FISCAL_YEAR_END_CLOSE":
        detail["reported_market_value_equity"] = reported
        detail["gap_vs_reported_pct"] = round(100.0 * (equity - reported) / reported, 2)
    return inputs, "", detail


def run_market_risk(
    company: Company, db: Session, settings: Settings, risk_free_rate: float | None = None
) -> tuple[MarketRisk, MertonResult]:
    """Merton, beta and risk metrics at the latest fiscal year end, stored append-only."""
    listing = company.listing
    year = latest_fiscal_year(company)
    fye = fiscal_year_end(year, listing.fiscal_year_end_month)
    security = db.get(Security, listing.ticker)
    prices = price_series(db, listing.ticker)
    rate = (
        risk_free_rate
        if risk_free_rate is not None
        else settings.merton_risk_free_rates.get(security.currency, 0.045)
    )

    inputs, refusal, detail = _merton_inputs(
        merged_line_items(company, year), prices, fye, rate, settings
    )
    merton = compute_merton(inputs, refusal)

    benchmark = listing.benchmark_ticker or settings.market_benchmark_ticker
    beta = compute_beta(db, settings, listing.ticker, benchmark, fye)
    metrics = risk_metrics(
        up_to(prices, fye, settings.market_beta_window_months),
        risk_free_annual=settings.market_risk_free_rate,
        confidence=settings.market_var_confidence,
        minimum=settings.market_min_observations,
    )

    consensus = company.bankruptcy_risks[-1].consensus_verdict if company.bankruptcy_risks else None
    view, view_reason = market_view(
        consensus, merton.probability_of_default, settings.merton_low_pd, settings.merton_high_pd
    )

    parts = [merton.distance_to_default is not None, beta.beta is not None, bool(metrics.metrics)]
    confidence = (
        ResultConfidence.COMPLETE
        if all(parts)
        else ResultConfidence.UNUSABLE
        if not any(parts)
        else ResultConfidence.PARTIAL
    )

    row = MarketRisk(
        company_id=company.id,
        fiscal_year=year,
        ticker=listing.ticker,
        merton_distance_to_default=merton.distance_to_default,
        merton_probability_of_default=merton.probability_of_default,
        naive_distance_to_default=merton.naive_distance_to_default,
        naive_probability_of_default=merton.naive_probability_of_default,
        asset_value=merton.asset_value,
        asset_volatility=merton.asset_volatility,
        beta=beta.beta,
        adjusted_beta=beta.adjusted_beta,
        market_view=view,
        risk_metrics={**metrics.metrics, "observations": metrics.observations},
        confidence=confidence.value,
        calculation_basis={
            "fiscal_year_end": fye,
            "no_look_ahead": "Every statistic uses prices on or before the fiscal year end.",
            "currency": security.currency,
            "merton": {**merton.calculation_basis, **detail},
            "merton_confidence": merton.confidence.value,
            "beta": {
                "benchmark": benchmark,
                "window_months": settings.market_beta_window_months,
                "observations": beta.observations,
                "r_squared": beta.r_squared,
                "std_error": beta.std_error,
                "alpha_annual": beta.alpha_annual,
                "adjustment": "Blume: 0.67 * beta + 0.33",
                "reason": beta.reason or None,
            },
            "risk_metrics": {
                "risk_free_rate": settings.market_risk_free_rate,
                "var_confidence": settings.market_var_confidence,
                "horizon": "one month",
                "reason": metrics.reason or None,
            },
            "market_view": {
                "against_consensus": consensus,
                "reason": view_reason,
                "bands": {
                    "low_pd_below": settings.merton_low_pd,
                    "high_pd_above": settings.merton_high_pd,
                },
            },
        },
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row, merton


def dcf_beta(
    company: Company, db: Session, settings: Settings
) -> tuple[float | None, dict[str, Any]]:
    """Blume-adjusted regression beta for the DCF, or None to keep the declared default."""
    listing = company.listing
    year = latest_fiscal_year(company)
    if listing is None or year is None:
        return None, {}
    fye = fiscal_year_end(year, listing.fiscal_year_end_month)
    benchmark = listing.benchmark_ticker or settings.market_benchmark_ticker
    result = compute_beta(db, settings, listing.ticker, benchmark, fye)
    if result.adjusted_beta is None:
        return None, {"reason": result.reason}
    return result.adjusted_beta, {
        "source": "REGRESSION",
        "raw_beta": result.beta,
        "adjusted_beta": result.adjusted_beta,
        "benchmark": benchmark,
        "observations": result.observations,
        "r_squared": result.r_squared,
        "std_error": result.std_error,
        "window_end": fye,
    }
