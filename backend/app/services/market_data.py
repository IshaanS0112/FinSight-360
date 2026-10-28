"""Price series to returns, volatility, beta and risk metrics.

Returns always use adjusted close (dividends are part of the return); market
capitalisation uses the split-adjusted close. Every metric refuses below a
minimum number of observations rather than reporting a statistic of three
data points.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from statistics import NormalDist
from typing import Any

import numpy as np

PERIODS_PER_YEAR = 12
_NORMAL = NormalDist()


@dataclass(frozen=True)
class PricePoint:
    date: str
    close: float
    adj_close: float


@dataclass
class BetaResult:
    beta: float | None
    adjusted_beta: float | None = None
    alpha_annual: float | None = None
    r_squared: float | None = None
    std_error: float | None = None
    observations: int = 0
    reason: str = ""


@dataclass
class RiskMetrics:
    observations: int
    metrics: dict[str, float] = field(default_factory=dict)
    reason: str = ""


def simple_returns(prices: list[PricePoint]) -> list[tuple[str, float]]:
    """Period returns from adjusted close, labelled by the period-end date."""
    ordered = sorted(prices, key=lambda p: p.date)
    return [
        (b.date, b.adj_close / a.adj_close - 1.0)
        for a, b in zip(ordered, ordered[1:], strict=False)
        if a.adj_close > 0
    ]


def window(returns: list[tuple[str, float]], end_date: str | None, months: int | None):
    """The returns up to and including end_date, last `months` of them."""
    picked = [r for r in returns if end_date is None or r[0] <= end_date]
    return picked[-months:] if months else picked


def align(series: dict[str, list[tuple[str, float]]]) -> tuple[list[str], np.ndarray]:
    """Inner-join several return series on date. Returns (dates, T x N matrix)."""
    common = set.intersection(*({d for d, _ in rows} for rows in series.values()))
    dates = sorted(common)
    lookup = {name: dict(rows) for name, rows in series.items()}
    matrix = np.array([[lookup[name][d] for name in series] for d in dates])
    return dates, matrix


def annualised_volatility(returns: list[float]) -> float:
    return float(np.std(returns, ddof=1) * math.sqrt(PERIODS_PER_YEAR))


def annualised_return(returns: list[float]) -> float:
    """Geometric (compound) annual return."""
    growth = float(np.prod([1.0 + r for r in returns]))
    return growth ** (PERIODS_PER_YEAR / len(returns)) - 1.0


def estimate_beta(
    asset: list[tuple[str, float]],
    benchmark: list[tuple[str, float]],
    risk_free_annual: float,
    minimum: int,
) -> BetaResult:
    """OLS beta of excess asset returns on excess benchmark returns.

    adjusted_beta is Blume's 0.67 * beta + 0.33, the usual forward-looking form.
    """
    dates, matrix = align({"asset": asset, "benchmark": benchmark})
    if len(dates) < minimum:
        return BetaResult(
            beta=None,
            observations=len(dates),
            reason=f"{len(dates)} overlapping observations; {minimum} are required",
        )

    rf = risk_free_annual / PERIODS_PER_YEAR
    y, x = matrix[:, 0] - rf, matrix[:, 1] - rf
    x_var = float(np.var(x, ddof=1))
    if x_var < 1e-12:
        return BetaResult(beta=None, observations=len(dates), reason="benchmark has no variance")

    beta = float(np.cov(y, x, ddof=1)[0, 1] / x_var)
    alpha = float(np.mean(y) - beta * np.mean(x))
    residuals = y - (alpha + beta * x)
    ss_res = float(np.sum(residuals**2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    n = len(dates)
    std_error = math.sqrt(ss_res / (n - 2) / (x_var * (n - 1))) if n > 2 else None

    return BetaResult(
        beta=round(beta, 4),
        adjusted_beta=round(0.67 * beta + 0.33, 4),
        alpha_annual=round(alpha * PERIODS_PER_YEAR, 6),
        r_squared=round(1 - ss_res / ss_tot, 4) if ss_tot > 0 else None,
        std_error=round(std_error, 4) if std_error is not None else None,
        observations=n,
    )


def max_drawdown(prices: list[PricePoint]) -> float:
    """Largest peak-to-trough fall in adjusted close, as a positive fraction."""
    peak, worst = -math.inf, 0.0
    for point in sorted(prices, key=lambda p: p.date):
        peak = max(peak, point.adj_close)
        worst = max(worst, 1.0 - point.adj_close / peak)
    return worst


def risk_metrics(
    prices: list[PricePoint],
    *,
    risk_free_annual: float,
    confidence: float,
    minimum: int,
) -> RiskMetrics:
    """Return, volatility, Sharpe, Sortino, drawdown, VaR and expected shortfall.

    VaR and expected shortfall are one-month losses, reported as positive
    fractions. Historical VaR reads the empirical tail; parametric VaR assumes
    normal returns. Both are reported because they disagree whenever returns
    have fat tails, and that disagreement is worth seeing.
    """
    returns = [r for _, r in simple_returns(prices)]
    if len(returns) < minimum:
        return RiskMetrics(
            observations=len(returns),
            reason=f"{len(returns)} monthly returns; {minimum} are required",
        )

    arr = np.array(returns)
    rf_period = risk_free_annual / PERIODS_PER_YEAR
    ann_return = annualised_return(returns)
    ann_vol = annualised_volatility(returns)

    downside = np.minimum(arr - rf_period, 0.0)
    downside_dev = math.sqrt(float(np.mean(downside**2))) * math.sqrt(PERIODS_PER_YEAR)

    tail = 1.0 - confidence
    historical_var = -float(np.quantile(arr, tail))
    parametric_var = -(float(np.mean(arr)) + _NORMAL.inv_cdf(tail) * float(np.std(arr, ddof=1)))
    tail_losses = arr[arr <= -historical_var]
    expected_shortfall = -float(np.mean(tail_losses)) if tail_losses.size else historical_var

    return RiskMetrics(
        observations=len(returns),
        metrics={
            "annualised_return": round(ann_return, 6),
            "annualised_volatility": round(ann_vol, 6),
            "sharpe_ratio": round((ann_return - risk_free_annual) / ann_vol, 4)
            if ann_vol > 0
            else None,
            "sortino_ratio": round((ann_return - risk_free_annual) / downside_dev, 4)
            if downside_dev > 0
            else None,
            "max_drawdown": round(max_drawdown(prices), 6),
            "historical_var": round(historical_var, 6),
            "parametric_var": round(parametric_var, 6),
            "expected_shortfall": round(expected_shortfall, 6),
            "best_month": round(float(arr.max()), 6),
            "worst_month": round(float(arr.min()), 6),
        },
    )


def price_at(prices: list[PricePoint], date: str) -> PricePoint | None:
    """The last observation on or before date."""
    eligible = [p for p in prices if p.date <= date]
    return max(eligible, key=lambda p: p.date) if eligible else None


def describe_series(prices: list[PricePoint]) -> dict[str, Any]:
    ordered = sorted(prices, key=lambda p: p.date)
    return {
        "observations": len(ordered),
        "first_date": ordered[0].date if ordered else None,
        "last_date": ordered[-1].date if ordered else None,
    }
