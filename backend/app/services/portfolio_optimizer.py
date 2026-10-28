"""Portfolio Lab: mean-variance optimisation, HRP, and where the risk comes from.

Inspired by PyPortfolio/PyPortfolioOpt (expected-return estimators, Ledoit-Wolf
shrinkage, efficient frontier, HRP, discrete allocation) and letianzj/
QuantResearch (random-portfolio cloud, component VaR). Implemented from the
published methods:

    Markowitz (1952)        mean-variance optimisation
    Ledoit & Wolf (2004)    shrinkage toward a constant-variance target
    Lopez de Prado (2016)   hierarchical risk parity

Long-only throughout. Every estimate is in-sample: the optimiser is fitted to the
same history it is scored on, which flatters every Sharpe ratio it reports.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from statistics import NormalDist
from typing import Any

import numpy as np
from scipy.cluster.hierarchy import leaves_list, linkage
from scipy.optimize import minimize
from scipy.spatial.distance import squareform

PERIODS = 12
_NORMAL = NormalDist()

CITATIONS = {
    "markowitz": "Markowitz, H. (1952). Portfolio Selection. Journal of Finance, 7(1), 77-91.",
    "ledoit_wolf": (
        "Ledoit, O. and Wolf, M. (2004). A Well-Conditioned Estimator for "
        "Large-Dimensional Covariance Matrices. Journal of Multivariate Analysis, 88(2)."
    ),
    "hrp": (
        "Lopez de Prado, M. (2016). Building Diversified Portfolios that Outperform "
        "Out of Sample. Journal of Portfolio Management, 42(4), 59-69."
    ),
}


@dataclass
class Universe:
    tickers: list[str]
    dates: list[str]
    returns: np.ndarray  # T x N monthly simple returns
    benchmark: np.ndarray | None = None


@dataclass
class Estimates:
    mu: np.ndarray  # annual expected returns
    cov: np.ndarray  # annual covariance
    detail: dict[str, Any] = field(default_factory=dict)


# --- Estimation ---------------------------------------------------------------


def expected_returns(
    universe: Universe, method: str, rf: float, span: int
) -> tuple[np.ndarray, dict]:
    """Annualised expected returns: compounded historical, EMA-weighted, or CAPM."""
    r = universe.returns
    if method == "ema_historical":
        alpha = 2.0 / (span + 1.0)
        weights = (1 - alpha) ** np.arange(len(r))[::-1]
        mean = (weights[:, None] * r).sum(axis=0) / weights.sum()
        return (1 + mean) ** PERIODS - 1, {"method": "ema_historical", "span_months": span}
    if method == "capm":
        if universe.benchmark is None:
            raise ValueError("CAPM expected returns need a benchmark series")
        m = universe.benchmark
        market = float(np.prod(1 + m) ** (PERIODS / len(m)) - 1)
        betas = np.array(
            [np.cov(r[:, i], m, ddof=1)[0, 1] / np.var(m, ddof=1) for i in range(r.shape[1])]
        )
        return rf + betas * (market - rf), {"method": "capm", "market_return": round(market, 6)}
    growth = np.prod(1 + r, axis=0) ** (PERIODS / len(r)) - 1
    return growth, {"method": "mean_historical", "compounding": "geometric"}


def ledoit_wolf(r: np.ndarray) -> tuple[np.ndarray, float]:
    """Shrink the sample covariance toward mu * I. Returns (monthly covariance, shrinkage)."""
    t, n = r.shape
    x = r - r.mean(axis=0)
    # einsum rather than x.T @ x: Apple's Accelerate BLAS raises spurious
    # floating-point warnings on matrix products whose results are correct.
    sample = np.einsum("ti,tj->ij", x, x) / t
    mu = np.trace(sample) / n
    target = mu * np.eye(n)
    delta = np.sum((sample - target) ** 2) / n
    x2 = x**2
    beta = np.sum(np.einsum("ti,tj->ij", x2, x2) / t - sample**2) / (n * t)
    shrinkage = 0.0 if delta == 0 else min(beta, delta) / delta
    return (1 - shrinkage) * sample + shrinkage * target, float(shrinkage)


def make_psd(cov: np.ndarray) -> tuple[np.ndarray, bool]:
    """Clip negative eigenvalues to zero, the spectral fix. Returns (matrix, was_fixed)."""
    values, vectors = np.linalg.eigh(cov)
    if values.min() >= -1e-12:
        return cov, False
    fixed = vectors @ np.diag(np.clip(values, 0, None)) @ vectors.T
    return (fixed + fixed.T) / 2, True


def estimate(universe: Universe, method: str, risk_model: str, rf: float, span: int) -> Estimates:
    mu, mu_detail = expected_returns(universe, method, rf, span)
    if risk_model == "ledoit_wolf":
        monthly, shrinkage = ledoit_wolf(universe.returns)
    else:
        monthly, shrinkage = np.cov(universe.returns, rowvar=False, ddof=1), None
    cov, fixed = make_psd(monthly * PERIODS)
    return Estimates(
        mu=mu,
        cov=cov,
        detail={**mu_detail, "risk_model": risk_model, "shrinkage": shrinkage, "psd_fixed": fixed},
    )


# --- Portfolio arithmetic -----------------------------------------------------


def performance(w: np.ndarray, est: Estimates, rf: float) -> dict[str, float]:
    ret = float(w @ est.mu)
    vol = float(math.sqrt(max(w @ est.cov @ w, 0.0)))
    return {
        "expected_return": round(ret, 6),
        "volatility": round(vol, 6),
        "sharpe_ratio": round((ret - rf) / vol, 4) if vol > 0 else None,
        "effective_holdings": round(1.0 / float(np.sum(w**2)), 3),
    }


def _solve(objective, n: int, caps: np.ndarray, extra: list | None = None) -> np.ndarray | None:
    """Long-only SLSQP: weights in [0, cap], summing to one."""
    start = np.minimum(np.full(n, 1.0 / n), caps)
    start = start / start.sum() if start.sum() > 0 else start
    result = minimize(
        objective,
        start,
        method="SLSQP",
        bounds=[(0.0, float(c)) for c in caps],
        constraints=[{"type": "eq", "fun": lambda w: w.sum() - 1.0}, *(extra or [])],
        options={"maxiter": 500, "ftol": 1e-12},
    )
    if not result.success:
        return None
    w = np.clip(result.x, 0, None)
    return w / w.sum()


def min_volatility(est: Estimates, caps: np.ndarray) -> np.ndarray | None:
    return _solve(lambda w: w @ est.cov @ w, len(caps), caps)


def max_sharpe(est: Estimates, caps: np.ndarray, rf: float) -> np.ndarray | None:
    def negative_sharpe(w):
        vol = math.sqrt(max(w @ est.cov @ w, 1e-16))
        return -(w @ est.mu - rf) / vol

    return _solve(negative_sharpe, len(caps), caps)


def efficient_return(est: Estimates, caps: np.ndarray, target: float) -> np.ndarray | None:
    constraint = {"type": "eq", "fun": lambda w: w @ est.mu - target}
    return _solve(lambda w: w @ est.cov @ w, len(caps), caps, [constraint])


def hrp(returns: np.ndarray, cov: np.ndarray) -> tuple[np.ndarray, dict]:
    """Lopez de Prado's hierarchical risk parity. Takes no weight cap, by construction."""
    corr = np.corrcoef(returns, rowvar=False)
    distance = np.sqrt(np.clip((1 - corr) / 2, 0, 1))
    np.fill_diagonal(distance, 0.0)
    links = linkage(squareform(distance, checks=False), method="single")
    order = [int(i) for i in leaves_list(links)]

    weights = np.ones(len(order))
    clusters = [order]
    while clusters:
        clusters = [
            c[s]
            for c in clusters
            if len(c) > 1
            for s in (slice(0, len(c) // 2), slice(len(c) // 2, None))
        ]
        for left, right in zip(clusters[::2], clusters[1::2], strict=True):
            var_left, var_right = _cluster_variance(cov, left), _cluster_variance(cov, right)
            alpha = 1 - var_left / (var_left + var_right)
            weights[left] *= alpha
            weights[right] *= 1 - alpha
    return weights, {"order": order, "linkage": links.round(6).tolist()}


def _cluster_variance(cov: np.ndarray, items: list[int]) -> float:
    sub = cov[np.ix_(items, items)]
    inverse = 1 / np.diag(sub)
    w = inverse / inverse.sum()
    return float(w @ sub @ w)


def frontier(est: Estimates, caps: np.ndarray, points: int) -> list[dict[str, float]]:
    """Minimum-volatility portfolios across the feasible range of target returns."""
    floor = min_volatility(est, caps)
    if floor is None:
        return []
    low = float(floor @ est.mu)
    high = float(_max_feasible_return(est.mu, caps))
    curve = []
    for target in np.linspace(low, high, points):
        w = efficient_return(est, caps, float(target))
        if w is not None:
            ret, vol = float(w @ est.mu), float(math.sqrt(max(w @ est.cov @ w, 0)))
            curve.append({"expected_return": round(ret, 6), "volatility": round(vol, 6)})
    return curve


def _max_feasible_return(mu: np.ndarray, caps: np.ndarray) -> float:
    """Greedy: fill the highest-return assets to their caps until fully invested."""
    remaining, total = 1.0, 0.0
    for i in np.argsort(mu)[::-1]:
        take = min(caps[i], remaining)
        total += take * mu[i]
        remaining -= take
        if remaining <= 1e-12:
            break
    return total - 1e-6


def random_portfolios(est: Estimates, count: int, seed: int) -> list[dict[str, float]]:
    """The random-weight cloud the frontier is drawn against (Dirichlet weights)."""
    rng = np.random.default_rng(seed)
    weights = rng.dirichlet(np.ones(len(est.mu)), size=count)
    rets = np.einsum("pi,i->p", weights, est.mu)
    vols = np.sqrt(np.einsum("ij,jk,ik->i", weights, est.cov, weights))
    return [
        {"expected_return": round(float(r), 5), "volatility": round(float(v), 5)}
        for r, v in zip(rets, vols, strict=True)
    ]


def component_var(
    w: np.ndarray, monthly_cov: np.ndarray, tickers: list[str], confidence: float
) -> dict:
    """Parametric one-month VaR and each holding's additive share of it."""
    z = _NORMAL.inv_cdf(confidence)
    sigma = math.sqrt(max(w @ monthly_cov @ w, 1e-18))
    marginal = z * (monthly_cov @ w) / sigma
    component = w * marginal
    total = z * sigma
    return {
        "confidence": confidence,
        "horizon": "one month",
        "portfolio_var": round(total, 6),
        "components": [
            {
                "ticker": t,
                "weight": round(float(w[i]), 6),
                "marginal_var": round(float(marginal[i]), 6),
                "component_var": round(float(component[i]), 6),
                "share_of_risk": round(float(component[i] / total), 6),
            }
            for i, t in enumerate(tickers)
        ],
        "identity": "component VaRs sum to portfolio VaR exactly (Euler allocation)",
    }


def discrete_allocation(
    w: np.ndarray, prices: np.ndarray, tickers: list[str], budget: float
) -> dict:
    """Whole shares for a cash budget: floor, then greedily buy the most underweight."""
    shares = np.floor(w * budget / prices)
    cash = budget - float(shares @ prices)
    while True:
        held = shares * prices / budget
        affordable = [i for i in range(len(prices)) if prices[i] <= cash and w[i] > 0]
        if not affordable:
            break
        i = max(affordable, key=lambda k: w[k] - held[k])
        shares[i] += 1
        cash -= prices[i]
    realised = shares * prices / max(budget - cash, 1e-12)
    return {
        "budget": budget,
        "shares": {t: int(shares[i]) for i, t in enumerate(tickers) if shares[i] > 0},
        "leftover_cash": round(cash, 2),
        "realised_weights": {t: round(float(realised[i]), 6) for i, t in enumerate(tickers)},
        "tracking_rmse": round(float(np.sqrt(np.mean((realised - w) ** 2))), 6),
    }
