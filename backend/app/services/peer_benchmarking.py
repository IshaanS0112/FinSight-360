"""Standing against a sourced peer set, as real statistics.

    company_z  = (value - peer_mean) / peer_stdev      [sample stdev, n-1]
    percentile = Phi(company_z) * 100

Phi(z) is only a percentile if the peer ratios are normally distributed, which a
handful of companies cannot establish. Every result therefore also carries the
empirical rank ("3rd of 6"), flags |z| > 2 as tail extrapolation, and returns
INTERPRETATION_LIMIT alongside the number.

z is negated for lower-is-better ratios so a higher percentile always means a
better position.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import NormalDist, mean, stdev
from typing import Any

from app.config import Settings
from app.enums import RatioCategory
from app.services.benchmarks import RATIO_RULES, RULES_BY_CATEGORY, RatioRule

_NORMAL = NormalDist()
_EPS = 1e-9

# Past this, Phi(z) reads a tail a handful of peers cannot establish. The
# percentile is still returned, but flagged.
_EXTRAPOLATION_Z = 2.0

INTERPRETATION_LIMIT = (
    "These percentiles are a position against the specific, named peer companies "
    "attached to this analysis - not an industry percentile. Phi(z) converts a "
    "z-score into a percentile only if the peer ratios are normally distributed, "
    "and a handful of companies cannot establish that. Read peer_rank first: "
    "'3rd of 6' assumes nothing about the shape of the distribution, and it is the "
    "honest headline. The percentile is useful for comparing across ratios on one "
    "scale, which is what the radar chart needs, and for little else."
)


@dataclass
class RatioBenchmark:
    ratio: str
    value: float
    peer_count: int
    peer_mean: float | None = None
    peer_stdev: float | None = None
    z_score: float | None = None
    percentile: float | None = None
    rank: int | None = None
    higher_is_better: bool = True
    status: str = "SCORED"
    reason: str = ""


@dataclass
class PeerBenchmarkResult:
    ratios: dict[str, dict[str, Any]] = field(default_factory=dict)
    category_percentiles: dict[str, float | None] = field(default_factory=dict)
    industry_percentile: float | None = None
    peer_count: int = 0
    omitted: list[dict[str, str]] = field(default_factory=list)
    calculation_basis: dict[str, Any] = field(default_factory=dict)


def _peer_values(peer_ratios: list[dict[str, float]], key: str) -> list[float]:
    return [
        float(row[key])
        for row in peer_ratios
        if isinstance(row, dict)
        and isinstance(row.get(key), int | float)
        and not isinstance(row.get(key), bool)
    ]


def benchmark_one_ratio(
    *, rule: RatioRule, value: float, peer_values: list[float], minimum_peers: int
) -> RatioBenchmark:
    """z-score, percentile and empirical rank for one ratio against one peer set."""
    count = len(peer_values)
    if count < minimum_peers:
        return RatioBenchmark(
            ratio=rule.key,
            value=value,
            peer_count=count,
            higher_is_better=rule.higher_is_better,
            status="TOO_FEW_PEERS",
            reason=(
                f"{count} peer(s) reported this ratio; {minimum_peers} are required. A "
                "mean and a standard deviation over fewer than that describe the sample, "
                "not a population."
            ),
        )

    peer_mean = mean(peer_values)
    peer_stdev = stdev(peer_values) if count > 1 else 0.0

    # Rank assumes no distribution, so it survives where the z-score cannot.
    better = sum(
        1 for peer in peer_values if (peer > value if rule.higher_is_better else peer < value)
    )
    rank = better + 1

    if peer_stdev < _EPS:
        return RatioBenchmark(
            ratio=rule.key,
            value=value,
            peer_count=count,
            peer_mean=round(peer_mean, 6),
            peer_stdev=0.0,
            rank=rank,
            higher_is_better=rule.higher_is_better,
            status="ZERO_VARIANCE",
            reason=(
                "Every peer reports the same value for this ratio, so the standard "
                "deviation is zero and the z-score is undefined rather than infinite."
            ),
        )

    z_score = (value - peer_mean) / peer_stdev
    if not rule.higher_is_better:
        # Invert, so a higher percentile always means a better position.
        z_score = -z_score

    return RatioBenchmark(
        ratio=rule.key,
        value=value,
        peer_count=count,
        peer_mean=round(peer_mean, 6),
        peer_stdev=round(peer_stdev, 6),
        z_score=round(z_score, 6),
        percentile=round(100.0 * _NORMAL.cdf(z_score), 2),
        rank=rank,
        higher_is_better=rule.higher_is_better,
    )


def compute_peer_benchmark(
    *,
    company_ratios: dict[str, float],
    peer_ratios: list[dict[str, float]],
    settings: Settings,
) -> PeerBenchmarkResult:
    """Per-ratio, per-category and overall standing against the peer set."""
    result = PeerBenchmarkResult(peer_count=len(peer_ratios))
    omitted: list[dict[str, str]] = []

    for rule in RATIO_RULES:
        value = company_ratios.get(rule.key)
        if value is None:
            omitted.append(
                {
                    "ratio": rule.key,
                    "reason": "the subject company's ratio was not computed; see omitted_ratios",
                }
            )
            continue
        benchmark = benchmark_one_ratio(
            rule=rule,
            value=float(value),
            peer_values=_peer_values(peer_ratios, rule.key),
            minimum_peers=settings.benchmark_min_peers,
        )
        if benchmark.status != "SCORED":
            omitted.append({"ratio": rule.key, "reason": benchmark.reason})
        entry = {
            "value": benchmark.value,
            "peer_count": benchmark.peer_count,
            "status": benchmark.status,
            "higher_is_better": benchmark.higher_is_better,
        }
        if benchmark.rank is not None:
            entry["peer_rank"] = f"{benchmark.rank} of {benchmark.peer_count + 1}"
            entry["rank"] = benchmark.rank
        if benchmark.status == "SCORED":
            entry |= {
                "peer_mean": benchmark.peer_mean,
                "peer_stdev": benchmark.peer_stdev,
                "z_score": benchmark.z_score,
                "percentile": benchmark.percentile,
            }
            if abs(benchmark.z_score or 0.0) > _EXTRAPOLATION_Z:
                entry["extrapolated"] = True
                entry["extrapolation_note"] = (
                    f"|z| = {abs(benchmark.z_score):.2f}. Phi is being read "
                    f"{_EXTRAPOLATION_Z:.0f}+ standard deviations out, in a tail that "
                    f"{benchmark.peer_count} peers cannot establish. Use peer_rank."
                )
        elif benchmark.reason:
            entry["reason"] = benchmark.reason
        result.ratios[rule.key] = entry

    weights = settings.health_weights
    weighted_sum = 0.0
    weight_total = 0.0
    for category in RatioCategory:
        scored = [
            result.ratios[rule.key]["percentile"]
            for rule in RULES_BY_CATEGORY[category]
            if rule.key in result.ratios and result.ratios[rule.key]["status"] == "SCORED"
        ]
        key = category.value.lower()
        if scored:
            result.category_percentiles[key] = round(mean(scored), 2)
            weighted_sum += result.category_percentiles[key] * weights[key]
            weight_total += weights[key]
        else:
            result.category_percentiles[key] = None

    if weight_total > _EPS:
        # Renormalised over scored categories: no peer data means unknown, not bad.
        result.industry_percentile = round(weighted_sum / weight_total, 2)

    result.omitted = omitted
    result.calculation_basis = {
        "method": "percentile = Phi(z) * 100, z = (company_value - peer_mean) / peer_stdev",
        "standard_deviation": "sample (n-1 denominator)",
        "direction_normalisation": (
            "z is negated for lower-is-better ratios so a higher percentile always "
            "means a better position, on every ratio."
        ),
        "category_percentile": "unweighted mean of the scored ratios in the category",
        "industry_percentile": (
            "weighted mean of the category percentiles using the health-score weights, "
            "renormalised over the categories that scored"
        ),
        "weights": weights,
        "weights_effective_total": round(weight_total, 6),
        "peer_count": len(peer_ratios),
        "minimum_peers": settings.benchmark_min_peers,
        "interpretation_limit": INTERPRETATION_LIMIT,
        "why_a_z_score_rather_than_a_rank": (
            "A rank answers 'how many peers beat this company' and nothing else. A "
            "z-score also carries by how much, which is what makes two different "
            "ratios comparable on one axis - a company can be 2nd of 6 on margin by a "
            "hair and 2nd of 6 on liquidity by a mile, and only the standardised "
            "figure distinguishes those. Both are returned."
        ),
    }
    return result
