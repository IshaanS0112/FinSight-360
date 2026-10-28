"""Peer benchmarking: z-scores, percentiles, and what they are not.

# roadmap: v2-05-peer-benchmarking

V1 refused to populate ``peer_percentile`` at all. V2 populates it, so the tests
that matter most here are the ones guarding against the overclaim that refusal
was protecting against.
"""

from __future__ import annotations

from statistics import NormalDist

import pytest

from app.services.benchmarks import RULE_BY_KEY
from app.services.peer_benchmarking import benchmark_one_ratio, compute_peer_benchmark

COMPANY = {
    "current_ratio": 1.4155,
    "quick_ratio": 0.8941,
    "roe": 55.36,
    "roa": 12.30,
    "net_margin": 16.65,
    "gross_margin": 37.97,
    "debt_to_equity": 1.9703,
    "interest_coverage": 25.53,
    "asset_turnover": 0.7384,
    "inventory_turnover": 2.3890,
}


def peer(**overrides) -> dict[str, float]:
    base = {
        "current_ratio": 1.4,
        "quick_ratio": 0.9,
        "roe": 20.0,
        "roa": 7.0,
        "net_margin": 10.0,
        "gross_margin": 30.0,
        "debt_to_equity": 1.5,
        "interest_coverage": 8.0,
        "asset_turnover": 0.8,
        "inventory_turnover": 3.0,
    }
    return {**base, **overrides}


PEERS = [
    peer(current_ratio=1.2, roe=18.0, debt_to_equity=2.4),
    peer(current_ratio=1.6, roe=22.0, debt_to_equity=1.1),
    peer(current_ratio=1.5, roe=25.0, debt_to_equity=0.9),
    peer(current_ratio=1.3, roe=15.0, debt_to_equity=1.8),
]


# --- The statistics -----------------------------------------------------------


def test_percentile_is_the_normal_cdf_of_the_z_score():
    result = benchmark_one_ratio(
        rule=RULE_BY_KEY["current_ratio"],
        value=1.6,
        peer_values=[1.2, 1.4, 1.5, 1.3],
        minimum_peers=3,
    )
    assert result.peer_mean == pytest.approx(1.35, abs=1e-9)
    # Sample standard deviation, n-1 denominator.
    assert result.peer_stdev == pytest.approx(0.1290994, abs=1e-6)
    assert result.z_score == pytest.approx((1.6 - 1.35) / 0.1290994, abs=1e-5)
    assert result.percentile == pytest.approx(100 * NormalDist().cdf(result.z_score), abs=1e-2)


def test_a_lower_is_better_ratio_has_its_axis_inverted():
    """Without this, conservative leverage would read as a bottom-decile weakness."""
    low_leverage = benchmark_one_ratio(
        rule=RULE_BY_KEY["debt_to_equity"],
        value=0.5,
        peer_values=[1.5, 2.0, 2.5, 3.0],
        minimum_peers=3,
    )
    assert low_leverage.z_score > 0
    assert low_leverage.percentile > 50
    assert low_leverage.rank == 1, "least levered of the five"


def test_rank_is_computed_even_where_the_z_score_cannot_be():
    """An identical peer set has zero variance, so only the rank survives."""
    result = benchmark_one_ratio(
        rule=RULE_BY_KEY["roa"], value=9.0, peer_values=[7.0, 7.0, 7.0], minimum_peers=3
    )
    assert result.status == "ZERO_VARIANCE"
    assert result.z_score is None
    assert result.percentile is None
    assert result.rank == 1
    assert "undefined rather than infinite" in result.reason


def test_too_few_peers_yields_no_statistic_rather_than_a_confident_one():
    result = benchmark_one_ratio(
        rule=RULE_BY_KEY["roe"], value=20.0, peer_values=[18.0], minimum_peers=3
    )
    assert result.status == "TOO_FEW_PEERS"
    assert result.percentile is None
    assert "describe the sample, not a population" in result.reason


# --- The overclaim guards ------------------------------------------------------


def test_every_result_carries_the_interpretation_limit(settings):
    """V1 left this field null rather than make a claim it could not support.

    V2 populates it, which means the qualifier has to travel with the number
    rather than live in a README nobody reads next to the dashboard.
    """
    result = compute_peer_benchmark(company_ratios=COMPANY, peer_ratios=PEERS, settings=settings)
    limit = result.calculation_basis["interpretation_limit"]
    assert "not an industry percentile" in limit
    assert "Read peer_rank first" in limit


def test_an_extreme_z_score_is_flagged_as_tail_extrapolation(settings):
    """Caterpillar's ROE of 55% against peers clustered near 20 is 4+ sigma out.

    Phi returns a percentile of essentially 100, which is a real number and a
    meaningless one: four peers cannot establish a fourth-standard-deviation tail.
    """
    result = compute_peer_benchmark(company_ratios=COMPANY, peer_ratios=PEERS, settings=settings)
    roe = result.ratios["roe"]
    assert roe["status"] == "SCORED"
    assert roe["extrapolated"] is True
    assert "peers cannot establish" in roe["extrapolation_note"]
    assert roe["peer_rank"] == "1 of 5"


def test_a_ratio_the_company_did_not_report_is_omitted_not_zeroed(settings):
    result = compute_peer_benchmark(
        company_ratios={k: v for k, v in COMPANY.items() if k != "roe"},
        peer_ratios=PEERS,
        settings=settings,
    )
    assert "roe" not in result.ratios
    assert any(entry["ratio"] == "roe" for entry in result.omitted)


# --- Aggregation ----------------------------------------------------------------


def test_category_and_industry_percentiles_use_the_health_score_weights(settings):
    """So the two numbers sit on the same scale and can be read together."""
    result = compute_peer_benchmark(company_ratios=COMPANY, peer_ratios=PEERS, settings=settings)
    assert result.calculation_basis["weights"] == settings.health_weights
    assert 0 <= result.industry_percentile <= 100

    expected = sum(
        result.category_percentiles[k] * settings.health_weights[k]
        for k in result.category_percentiles
        if result.category_percentiles[k] is not None
    ) / sum(
        settings.health_weights[k]
        for k in result.category_percentiles
        if result.category_percentiles[k] is not None
    )
    assert result.industry_percentile == pytest.approx(expected, abs=1e-2)


def test_an_empty_peer_set_produces_no_percentile_at_all(settings):
    result = compute_peer_benchmark(company_ratios=COMPANY, peer_ratios=[], settings=settings)
    assert result.industry_percentile is None
    assert all(value is None for value in result.category_percentiles.values())
    assert len(result.omitted) == len(RULE_BY_KEY)


# --- Over HTTP -------------------------------------------------------------------


def test_a_peer_set_populates_the_health_score_percentile(client, load_company, caterpillar):
    """The field V1 documented as permanently null now carries a number - and only
    because a sourced peer set was attached."""
    company_id = load_company(caterpillar)
    client.post(f"/companies/{company_id}/compute-ratios")

    before = client.post(f"/companies/{company_id}/compute-health-score").json()
    assert before["peer_percentile"] is None

    response = client.post(
        f"/companies/{company_id}/peer-set",
        json={
            "peers": [
                {
                    "peer_name": f"Machinery Peer {index}",
                    "source": "Illustrative peer used to exercise the benchmarking engine.",
                    "ratios": row,
                }
                for index, row in enumerate(PEERS)
            ]
        },
    )
    assert response.status_code == 201
    assert len(response.json()) == 4

    after = client.post(f"/companies/{company_id}/compute-health-score").json()
    assert after["peer_percentile"] is not None
    assert (
        "not an industry percentile"
        in (after["calculation_basis"]["peer_benchmark"]["interpretation_limit"])
    )


def test_a_peer_with_an_unknown_ratio_key_is_rejected(client, load_company, caterpillar):
    company_id = load_company(caterpillar)
    response = client.post(
        f"/companies/{company_id}/peer-set",
        json={
            "peers": [
                {
                    "peer_name": "Peer",
                    "source": "somewhere",
                    "ratios": {"ebitda_margin": 20.0},
                }
            ]
        },
    )
    assert response.status_code == 422
    assert "not a ratio this engine computes" in response.text


def test_a_peer_without_a_source_is_rejected(client, load_company, caterpillar):
    company_id = load_company(caterpillar)
    response = client.post(
        f"/companies/{company_id}/peer-set",
        json={"peers": [{"peer_name": "Peer", "ratios": {"roe": 20.0}}]},
    )
    assert response.status_code == 422


def test_posting_a_peer_set_replaces_rather_than_appends(client, load_company, caterpillar):
    company_id = load_company(caterpillar)
    body = {
        "peers": [
            {"peer_name": "First", "source": "source one", "ratios": {"roe": 20.0}},
            {"peer_name": "Second", "source": "source two", "ratios": {"roe": 22.0}},
        ]
    }
    client.post(f"/companies/{company_id}/peer-set", json=body)
    client.post(
        f"/companies/{company_id}/peer-set",
        json={"peers": [{"peer_name": "Only", "source": "source three", "ratios": {"roe": 21.0}}]},
    )
    stored = client.get(f"/companies/{company_id}/peer-set").json()
    assert [p["peer_name"] for p in stored] == ["Only"]


def test_the_benchmark_endpoint_returns_ranks_alongside_percentiles(
    client, load_company, caterpillar
):
    company_id = load_company(caterpillar)
    client.post(f"/companies/{company_id}/compute-ratios")
    client.post(
        f"/companies/{company_id}/peer-set",
        json={
            "peers": [
                {"peer_name": f"Peer {i}", "source": "illustrative", "ratios": row}
                for i, row in enumerate(PEERS)
            ]
        },
    )
    body = client.get(f"/companies/{company_id}/peer-benchmark").json()
    assert body["peer_count"] == 4
    assert body["peer_names"] == ["Peer 0", "Peer 1", "Peer 2", "Peer 3"]
    assert body["ratios"]["current_ratio"]["peer_rank"].endswith("of 5")
    assert body["industry_percentile"] is not None


def test_the_benchmark_endpoint_refuses_before_ratios_are_computed(
    client, load_company, caterpillar
):
    company_id = load_company(caterpillar)
    response = client.get(f"/companies/{company_id}/peer-benchmark")
    assert response.status_code == 409
    assert "/compute-ratios first" in response.json()["detail"]
