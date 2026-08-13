"""Weighted financial health score.

    health = 0.35·profitability + 0.25·liquidity + 0.20·leverage + 0.20·efficiency

Unlike the ratio engine and the Altman models, this is **not** an established
model. It is a composite this project defines, and saying so plainly is more
useful than dressing it up: the weights are a judgement, the normalisation is a
judgement, and both are declared in ``config.py`` and echoed in every result's
``calculation_basis`` so a reader can disagree with the specific numbers instead
of having to guess at them.

How a component score is built:

1. Each ratio in the component is compared to its benchmark - the peer median if
   enough peers are loaded, otherwise the configured reference band.
2. The comparison is a *relative* distance, so it works across ratios with
   completely different scales (a current ratio of 1.4 and an ROE of 18%).
3. 50 means "exactly at benchmark". Above-benchmark earns up to 100, below-
   benchmark down to 0, and the mapping saturates at
   ``health_full_credit_ratio`` (default 1.0, i.e. twice the benchmark scores
   100). The cap is the important part: without it a single freak ratio - a quick
   ratio of 30 because the company just raised equity - would drag the composite
   up and the 0-100 range would stop meaning anything.
4. ``higher_is_better=False`` ratios (debt-to-equity) invert the direction, so
   low leverage scores well.
5. A component with no computable ratios is dropped from the composite and the
   remaining weights are renormalised - with the renormalisation recorded. The
   alternative, scoring a missing component as 0, would report a company as
   unhealthy for not disclosing a line item.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.config import Settings
from app.enums import BenchmarkBasis, RatioCategory, ResultConfidence
from app.services.benchmarks import (
    RULES_BY_CATEGORY,
    resolve_benchmark,
)
from app.services.ratio_engine import PERCENT_RATIOS, RatioResult

_EPS = 1e-9


@dataclass
class HealthScoreResult:
    overall_score: float | None
    component_scores: dict[str, float | None] = field(default_factory=dict)
    peer_percentile: float | None = None
    confidence: ResultConfidence = ResultConfidence.COMPLETE
    calculation_basis: dict[str, Any] = field(default_factory=dict)


def score_ratio_against_benchmark(
    *,
    value: float,
    benchmark: float,
    higher_is_better: bool,
    full_credit_ratio: float,
) -> float:
    """Map one ratio onto 0-100, where 50 is exactly at benchmark.

    Relative rather than absolute distance, so the same function works for a
    current ratio and a percentage margin.
    """
    denominator = abs(benchmark) if abs(benchmark) > _EPS else _EPS
    relative = (value - benchmark) / denominator
    if not higher_is_better:
        relative = -relative
    # Saturate at +/- full_credit_ratio, then map [-1, 1] -> [0, 100].
    clamped = max(-1.0, min(1.0, relative / full_credit_ratio))
    return round(50.0 + 50.0 * clamped, 2)


def compute_health_score(
    *,
    ratios: RatioResult,
    industry: str | None,
    peer_ratios: list[dict[str, float]],
    reference_table: dict[str, dict[str, float]],
    reference_provenance: str,
    settings: Settings,
) -> HealthScoreResult:
    """Weighted composite over the four ratio categories."""
    computed = ratios.all_ratios
    component_scores: dict[str, float | None] = {}
    detail: dict[str, Any] = {}
    bases_used: set[str] = set()

    for category in RatioCategory:
        rules = RULES_BY_CATEGORY[category]
        scored: list[float] = []
        per_ratio: dict[str, Any] = {}

        for rule in rules:
            value = computed.get(rule.key)
            if value is None:
                per_ratio[rule.key] = {"status": "NOT_COMPUTED"}
                continue

            benchmark, basis = resolve_benchmark(
                ratio_key=rule.key,
                industry=industry,
                peer_ratios=peer_ratios,
                table=reference_table,
                minimum_peers=settings.benchmark_min_peers,
            )
            if benchmark is None:
                per_ratio[rule.key] = {
                    "status": "NO_BENCHMARK",
                    "value": value,
                    "benchmark_basis": basis.value,
                }
                continue

            score = score_ratio_against_benchmark(
                value=value,
                benchmark=benchmark,
                higher_is_better=rule.higher_is_better,
                full_credit_ratio=settings.health_full_credit_ratio,
            )
            scored.append(score)
            bases_used.add(basis.value)
            per_ratio[rule.key] = {
                "status": "SCORED",
                "value": value,
                "benchmark": benchmark,
                "benchmark_basis": basis.value,
                "higher_is_better": rule.higher_is_better,
                "unit": "percent" if rule.key in PERCENT_RATIOS else "ratio",
                "score": score,
            }

        if len(scored) >= settings.health_min_metrics_per_component:
            component_scores[category.value.lower()] = round(sum(scored) / len(scored), 2)
        else:
            component_scores[category.value.lower()] = None

        detail[category.value.lower()] = {
            "ratios": per_ratio,
            "ratios_scored": len(scored),
            "minimum_required": settings.health_min_metrics_per_component,
        }

    weights = {k: v for k, v in settings.health_weights.items()}
    available = {k: v for k, v in component_scores.items() if v is not None}

    if not available:
        return HealthScoreResult(
            overall_score=None,
            component_scores=component_scores,
            confidence=ResultConfidence.UNUSABLE,
            calculation_basis={
                "reason": (
                    "No component could be scored: no ratio had both a computed value "
                    "and a benchmark to compare it against."
                ),
                "weights_declared": weights,
                "component_detail": detail,
                "benchmark_provenance": reference_provenance,
            },
        )

    weight_total = sum(weights[k] for k in available)
    effective_weights = {k: round(weights[k] / weight_total, 6) for k in available}
    overall = round(sum(available[k] * effective_weights[k] for k in available), 2)

    dropped = [k for k, v in component_scores.items() if v is None]
    confidence = ResultConfidence.COMPLETE if not dropped else ResultConfidence.PARTIAL

    return HealthScoreResult(
        overall_score=overall,
        component_scores=component_scores,
        peer_percentile=_peer_percentile(overall, peer_ratios),
        confidence=confidence,
        calculation_basis={
            "definition": (
                "Project-defined composite, not an established model. 50 on a component "
                "means exactly at benchmark."
            ),
            "weights_declared": weights,
            "weights_effective": effective_weights,
            "components_dropped": dropped,
            "renormalisation_note": (
                f"Components {dropped} had too few scoreable ratios and were dropped; the "
                "remaining weights were renormalised to sum to 1.0. Scoring a missing "
                "component as zero would report a company as unhealthy for not "
                "disclosing a line item."
                if dropped
                else None
            ),
            "normalisation": (
                "score = 50 + 50*clamp((value-benchmark)/|benchmark| / full_credit_ratio, -1, 1), "
                "direction inverted for lower-is-better ratios"
            ),
            "full_credit_ratio": settings.health_full_credit_ratio,
            "benchmark_bases_used": sorted(bases_used),
            "benchmark_provenance": reference_provenance,
            "component_detail": detail,
        },
    )


def _peer_percentile(score: float, peer_ratios: list[dict[str, float]]) -> float | None:
    """Withheld by design.

    A percentile needs a distribution. With the handful of peers this system is
    scoped to hold, any number here would be a percentile of three or four
    companies presented as if it were an industry position - which is exactly the
    kind of claim the project spec says not to make. The field stays ``None``
    until a real reference population is loaded, and ``calculation_basis``
    records why.
    """
    return None
