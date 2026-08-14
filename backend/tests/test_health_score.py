"""Health score: the composite this project defines, and its guard rails."""

from __future__ import annotations

import pytest

from app.enums import ResultConfidence
from app.services.health_score import compute_health_score, score_ratio_against_benchmark
from app.services.ratio_engine import compute_ratios


def build(items, settings, reference_table, industry, peers=None):
    table, provenance = reference_table
    return compute_health_score(
        ratios=compute_ratios(items),
        industry=industry,
        peer_ratios=peers or [],
        reference_table=table,
        reference_provenance=provenance,
        settings=settings,
    )


# --- The normalisation -------------------------------------------------------


def test_exactly_at_benchmark_scores_fifty(settings):
    score = score_ratio_against_benchmark(
        value=1.5,
        benchmark=1.5,
        higher_is_better=True,
        full_credit_ratio=settings.health_full_credit_ratio,
    )
    assert score == 50.0


def test_twice_the_benchmark_scores_one_hundred(settings):
    score = score_ratio_against_benchmark(
        value=3.0,
        benchmark=1.5,
        higher_is_better=True,
        full_credit_ratio=settings.health_full_credit_ratio,
    )
    assert score == 100.0


def test_saturation_means_an_outlier_cannot_inflate_the_composite(settings):
    """The cap is the point. A quick ratio of 30 must not score above 100."""
    modest = score_ratio_against_benchmark(
        value=3.0, benchmark=1.5, higher_is_better=True, full_credit_ratio=1.0
    )
    absurd = score_ratio_against_benchmark(
        value=45.0, benchmark=1.5, higher_is_better=True, full_credit_ratio=1.0
    )
    assert modest == absurd == 100.0


def test_lower_is_better_inverts_the_direction(settings):
    """Low leverage must score well, not badly."""
    low_debt = score_ratio_against_benchmark(
        value=0.4, benchmark=1.0, higher_is_better=False, full_credit_ratio=1.0
    )
    high_debt = score_ratio_against_benchmark(
        value=1.6, benchmark=1.0, higher_is_better=False, full_credit_ratio=1.0
    )
    assert low_debt > 50.0 > high_debt


def test_score_never_leaves_the_zero_hundred_range(settings):
    for value in (-500.0, -1.0, 0.0, 1.0, 1e9):
        score = score_ratio_against_benchmark(
            value=value, benchmark=1.0, higher_is_better=True, full_credit_ratio=1.0
        )
        assert 0.0 <= score <= 100.0


# --- The composite -----------------------------------------------------------


def test_weights_sum_to_one_and_match_the_spec(settings):
    assert settings.health_weights == {
        "profitability": 0.35,
        "liquidity": 0.25,
        "leverage": 0.20,
        "efficiency": 0.20,
    }
    assert sum(settings.health_weights.values()) == pytest.approx(1.0)


def test_unnormalised_weights_are_rejected_at_construction():
    from app.config import Settings

    with pytest.raises(ValueError, match="must sum to 1.0"):
        Settings(_env_file=None, health_w_profitability=0.9)


def test_healthy_company_scores_above_a_distressed_one(
    cat_items, vi_items, settings, reference_table
):
    healthy = build(cat_items, settings, reference_table, "industrial machinery")
    distressed = build(vi_items, settings, reference_table, "telecom")
    assert healthy.overall_score > distressed.overall_score
    assert distressed.overall_score < 50.0, "behind benchmark on every scoreable ratio"


def test_infosys_scores_well_against_its_own_industry_band(infy_items, settings, reference_table):
    result = build(infy_items, settings, reference_table, "it services")
    assert result.confidence is ResultConfidence.COMPLETE
    assert result.overall_score > 50.0
    assert set(result.component_scores) == {"profitability", "liquidity", "leverage", "efficiency"}


def test_dropped_component_renormalises_rather_than_scoring_zero(settings, reference_table):
    """A company that discloses no income statement is not thereby unhealthy."""
    items = {
        "total_assets": 1000.0,
        "current_assets": 300.0,
        "current_liabilities": 200.0,
        "inventory": 50.0,
    }
    result = build(items, settings, reference_table, "_default")
    assert result.confidence is ResultConfidence.PARTIAL
    assert result.component_scores["liquidity"] is not None
    assert result.component_scores["profitability"] is None
    basis = result.calculation_basis
    assert set(basis["components_dropped"]) == {"profitability", "leverage", "efficiency"}
    assert sum(basis["weights_effective"].values()) == pytest.approx(1.0)
    # Liquidity carried the whole composite, so the composite equals it.
    assert result.overall_score == pytest.approx(result.component_scores["liquidity"], abs=0.01)
    assert "unhealthy for not" in basis["renormalisation_note"]


def test_no_scoreable_ratio_is_unusable_not_zero(settings, reference_table):
    result = build({}, settings, reference_table, "_default")
    assert result.overall_score is None
    assert result.confidence is ResultConfidence.UNUSABLE


# --- Benchmark provenance ----------------------------------------------------


def test_placeholder_provenance_is_stated_in_every_result(cat_items, settings, reference_table):
    """The reference bands are placeholders and the result says so out loud."""
    result = build(cat_items, settings, reference_table, "industrial machinery")
    provenance = result.calculation_basis["benchmark_provenance"]
    assert "ILLUSTRATIVE PLACEHOLDER" in provenance
    assert result.calculation_basis["benchmark_bases_used"] == ["REFERENCE_TABLE"]


def test_enough_peers_switches_the_basis_to_the_peer_median(cat_items, settings, reference_table):
    peers = [
        {"current_ratio": 1.0, "roa": 4.0, "asset_turnover": 0.5, "net_margin": 5.0},
        {"current_ratio": 1.2, "roa": 5.0, "asset_turnover": 0.6, "net_margin": 6.0},
        {"current_ratio": 1.4, "roa": 6.0, "asset_turnover": 0.7, "net_margin": 7.0},
    ]
    result = build(cat_items, settings, reference_table, "industrial machinery", peers=peers)
    bases = result.calculation_basis["benchmark_bases_used"]
    assert "PEER_SET" in bases
    detail = result.calculation_basis["component_detail"]["liquidity"]["ratios"]["current_ratio"]
    assert detail["benchmark_basis"] == "PEER_SET"
    assert detail["benchmark"] == pytest.approx(1.2), "median of three peers, not the mean"


def test_too_few_peers_falls_back_to_the_reference_table(cat_items, settings, reference_table):
    peers = [{"current_ratio": 9.0}, {"current_ratio": 9.0}]  # below benchmark_min_peers
    result = build(cat_items, settings, reference_table, "industrial machinery", peers=peers)
    detail = result.calculation_basis["component_detail"]["liquidity"]["ratios"]["current_ratio"]
    assert detail["benchmark_basis"] == "REFERENCE_TABLE"


def test_peer_percentile_is_withheld_rather_than_faked(cat_items, settings, reference_table):
    """Three peers cannot produce an industry percentile, so none is reported."""
    result = build(cat_items, settings, reference_table, "industrial machinery")
    assert result.peer_percentile is None
