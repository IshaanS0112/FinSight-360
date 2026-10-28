"""Monte Carlo over the deterministic engines.

# roadmap: v2-07-scenario-simulator

The simulator adds no model and no score, so the tests are about three things:
that it really is re-running the same code, that the same seed gives the same
answer, and that the perturbation model is honest about what it does not move.
"""

from __future__ import annotations

import pytest

from app.enums import Distribution, ResultConfidence, SectorClass
from app.services.benchmarks import load_reference_bands
from app.services.dcf_valuation import DcfAssumptions
from app.services.health_score import compute_health_score
from app.services.ratio_engine import compute_ratios
from app.services.scenario_simulator import (
    PERTURBATION_NOTE,
    ShockSpec,
    percentiles,
    perturb,
    run_simulation,
)

CAT = {
    "total_assets": 87764.0,
    "current_assets": 45682.0,
    "current_liabilities": 32272.0,
    "total_liabilities": 68270.0,
    "inventory": 16827.0,
    "shareholder_equity": 19494.0,
    "retained_earnings": 59352.0,
    "total_debt": 38409.0,
    "market_value_equity": 177528.0,
    "revenue": 64809.0,
    "cogs": 40199.0,
    "gross_profit": 24610.0,
    "ebit": 13072.0,
    "net_income": 10792.0,
    "interest_expense": 512.0,
    "operating_cash_flow": 12035.0,
    "capital_expenditure": 3215.0,
    "depreciation_amortization": 2153.0,
    "cash_and_equivalents": 6890.0,
    "shares_outstanding": 477.9,
    "share_price": 363.0,
}

SHOCKS = {
    "revenue_growth": ShockSpec(Distribution.TRIANGULAR, low=-0.10, base=0.03, high=0.10),
    "margin_shift": ShockSpec(Distribution.NORMAL, base=0.0, high=0.03),
    "wacc_shift": ShockSpec(Distribution.NORMAL, base=0.0, high=0.01),
}


def simulate(settings, *, n_trials=400, seed=20240101, with_dcf=True, items=None):
    table, provenance = load_reference_bands(None)
    return run_simulation(
        items=items if items is not None else CAT,
        prior_items={"net_income": 10335.0},
        sector_class=SectorClass.PUBLIC_MANUFACTURER,
        settings=settings,
        shocks=SHOCKS,
        dcf_assumptions=DcfAssumptions.defaults(settings) if with_dcf else None,
        reference_table=table,
        reference_provenance=provenance,
        peer_ratios=[],
        industry="industrial machinery",
        n_trials=n_trials,
        seed=seed,
    )


# --- Percentiles ---------------------------------------------------------------


def test_percentiles_are_empirical_order_statistics():
    """No distribution is fitted; p50 of 1..101 is 51, not a fitted mean."""
    result = percentiles([float(n) for n in range(1, 102)])
    assert result["p50"] == 51.0
    assert result["p5"] == 6.0
    assert result["p95"] == 96.0
    assert result["min"] == 1.0
    assert result["max"] == 101.0
    assert result["n"] == 101


def test_percentiles_of_an_empty_sample_are_none_not_zero():
    assert percentiles([]) is None


# --- The perturbation model -----------------------------------------------------


def test_a_shock_flows_from_revenue_through_ebit_to_equity():
    shocked = perturb(CAT, revenue_growth=0.10, margin_shift=0.0)
    assert shocked["revenue"] == pytest.approx(64809.0 * 1.10, abs=1e-6)
    # Margin held, so EBIT scales with revenue.
    assert shocked["ebit"] == pytest.approx(13072.0 * 1.10, abs=1e-3)
    delta = shocked["ebit"] - 13072.0
    assert shocked["net_income"] == pytest.approx(10792.0 + delta, abs=1e-3)
    assert shocked["shareholder_equity"] == pytest.approx(19494.0 + delta, abs=1e-3)
    assert shocked["retained_earnings"] == pytest.approx(59352.0 + delta, abs=1e-3)


def test_the_balance_sheet_items_the_model_does_not_move_stay_put():
    """Stated in PERTURBATION_NOTE, so it must actually be true."""
    shocked = perturb(CAT, revenue_growth=-0.20, margin_shift=-0.05)
    for key in ("total_assets", "total_liabilities", "current_assets", "current_liabilities"):
        assert shocked[key] == CAT[key]


def test_the_gross_profit_identity_survives_a_shock():
    """Otherwise gross margin would silently stop being computable mid-simulation."""
    shocked = perturb(CAT, revenue_growth=0.05, margin_shift=0.0)
    assert shocked["gross_profit"] == pytest.approx(shocked["revenue"] - shocked["cogs"], abs=1e-6)


def test_perturb_does_not_mutate_the_base_year():
    before = dict(CAT)
    perturb(CAT, revenue_growth=0.5, margin_shift=0.1)
    assert before == CAT


def test_a_company_with_no_revenue_is_returned_unshocked():
    items = {"total_assets": 100.0}
    assert perturb(items, revenue_growth=0.5, margin_shift=0.1) == items


# --- Reproducibility ------------------------------------------------------------


def test_the_same_seed_reproduces_the_distribution_exactly(settings):
    """A distribution that cannot be regenerated is an anecdote."""
    first = simulate(settings, seed=7)
    second = simulate(settings, seed=7)
    assert first.summary == second.summary


def test_a_different_seed_gives_a_different_draw(settings):
    first = simulate(settings, seed=7)
    second = simulate(settings, seed=8)
    assert first.summary["z_score"]["p50"] != second.summary["z_score"]["p50"]


def test_the_seed_is_stored_on_the_result(settings):
    result = simulate(settings, seed=4242)
    assert result.seed == 4242
    assert "4242" in result.calculation_basis["reproducibility"]


# --- What the simulation reports ------------------------------------------------


def test_the_simulated_median_centres_on_the_point_estimate(settings):
    """The simulator must re-run the *same* computation, not a similar one.

    An earlier draft passed industry=None into the health score, so every trial
    benchmarked against the generic reference row while the point estimate used
    the industry row - and the simulated median landed 20 points away from the
    number it was supposed to be stressing. Nothing looked wrong in the output.
    """
    table, provenance = load_reference_bands(None)
    point_estimate = compute_health_score(
        ratios=compute_ratios(CAT),
        industry="industrial machinery",
        peer_ratios=[],
        reference_table=table,
        reference_provenance=provenance,
        settings=settings,
    ).overall_score

    result = simulate(settings, n_trials=2000)
    health = result.summary["health_score"]
    assert health["p5"] <= point_estimate <= health["p95"]
    assert abs(health["p50"] - point_estimate) < 6.0


def test_it_reports_a_spread_around_the_point_estimate(settings):
    result = simulate(settings, n_trials=2000)
    z = result.summary["z_score"]
    assert z["p5"] < z["p50"] < z["p95"]
    # Caterpillar's point estimate is 3.9203; the median of the shocked runs sits
    # near it because the growth triangle is centred close to zero drift.
    assert z["p5"] < 3.9203 < z["p95"]


def test_a_robust_verdict_and_a_fragile_valuation_look_different(settings):
    """The single most useful thing the simulator produces.

    Caterpillar's Altman zone does not move under these shocks; its DCF equity
    value spans a multiple. Reporting both as one number would hide that the
    second is an assumption and the first is a finding.
    """
    result = simulate(settings, n_trials=2000)
    assert result.summary["zone_shares"] == {"SAFE": 1.0}
    assert result.summary["distress_probability"] == 0.0

    equity = result.summary["dcf_equity_value"]
    assert equity["p95"] / equity["p5"] > 2.0


def test_zone_and_consensus_shares_sum_to_one(settings):
    result = simulate(settings, n_trials=500)
    assert sum(result.summary["zone_shares"].values()) == pytest.approx(1.0, abs=1e-6)
    assert sum(result.summary["consensus_shares"].values()) == pytest.approx(1.0, abs=1e-6)


def test_it_runs_the_variant_the_point_estimate_selected(settings):
    result = simulate(settings, n_trials=200)
    assert result.summary["altman_model"] == "Z_1968"
    assert "Z_1968" in result.calculation_basis["altman_variant_note"]


def test_refused_dcf_trials_are_counted_not_filled_with_zero(settings):
    """A trial whose margin shock turned EBIT negative has no valuation, not a zero one."""
    result = simulate(settings, n_trials=1000, items={**CAT, "ebit": 400.0})
    assert result.summary["dcf_trials_refused"] >= 0
    equity = result.summary["dcf_equity_value"]
    if equity is not None:
        assert equity["n"] + result.summary["dcf_trials_refused"] == 1000


def test_the_perturbation_model_states_the_direction_of_its_own_bias(settings):
    """Holding the balance sheet fixed makes the distributions too tight, and says so."""
    result = simulate(settings, n_trials=200)
    note = result.calculation_basis["perturbation_model"]
    assert note == PERTURBATION_NOTE
    assert "understates dispersion" in note


def test_distress_probability_is_labelled_a_sensitivity_not_a_default_rate(settings):
    result = simulate(settings, n_trials=200)
    meaning = result.calculation_basis["distress_probability_meaning"]
    assert "not a probability of default" in meaning


def test_skipping_the_dcf_leaves_the_rest_intact(settings):
    result = simulate(settings, n_trials=200, with_dcf=False)
    assert result.summary["dcf_equity_value"] is None
    assert result.summary["z_score"]["n"] == 200
    assert result.confidence is ResultConfidence.COMPLETE


# --- Over HTTP -------------------------------------------------------------------


def _load_valuable_caterpillar(client, load_company, caterpillar) -> str:
    company_id = load_company(caterpillar)
    for statement in (
        {
            "statement_type": "BALANCE_SHEET",
            "line_items": {
                "cash_and_equivalents": 6890,
                "shares_outstanding": 477.9,
                "share_price": 363,
            },
        },
        {"statement_type": "CASH_FLOW", "line_items": {"depreciation_amortization": 2153}},
    ):
        assert (
            client.post(f"/companies/{company_id}/financial-statements", json=statement).status_code
            == 201
        )
    return company_id


def test_a_bare_post_runs_a_complete_reproducible_simulation(
    client, load_company, caterpillar, settings
):
    company_id = _load_valuable_caterpillar(client, load_company, caterpillar)
    body = client.post(f"/companies/{company_id}/run-scenario", json={"n_trials": 500}).json()

    assert body["n_trials"] == 500
    assert body["seed"] == settings.scenario_default_seed
    assert set(body["input_distributions"]) == {"revenue_growth", "margin_shift", "wacc_shift"}
    assert body["result_summary"]["zone_shares"]["SAFE"] == 1.0
    assert body["result_summary"]["dcf_equity_value"]["n"] > 0

    fetched = client.get(f"/companies/{company_id}/scenario-results/{body['id']}").json()
    assert fetched["result_summary"] == body["result_summary"]


def test_custom_distributions_change_the_outcome(client, load_company, caterpillar):
    company_id = _load_valuable_caterpillar(client, load_company, caterpillar)
    severe = client.post(
        f"/companies/{company_id}/run-scenario",
        json={
            "n_trials": 800,
            "seed": 11,
            "distributions": {
                "revenue_growth": {
                    "distribution": "TRIANGULAR",
                    "low": -0.60,
                    "mode": -0.35,
                    "high": -0.10,
                },
                "margin_shift": {"distribution": "NORMAL", "mu": -0.12, "sigma": 0.04},
            },
        },
    ).json()
    assert severe["result_summary"]["z_score"]["p50"] < 3.9203
    assert severe["result_summary"]["health_score"]["p50"] < 55


def test_an_unrecognised_shock_name_is_rejected(client, load_company, caterpillar):
    """Storing a key that perturbs nothing is the most misleading possible outcome."""
    company_id = _load_valuable_caterpillar(client, load_company, caterpillar)
    response = client.post(
        f"/companies/{company_id}/run-scenario",
        json={"distributions": {"tax_shock": {"distribution": "NORMAL", "mu": 0, "sigma": 0.1}}},
    )
    assert response.status_code == 422
    assert "is not a shock this simulator applies" in response.json()["detail"]


def test_a_malformed_triangular_shock_is_rejected(client, load_company, caterpillar):
    company_id = _load_valuable_caterpillar(client, load_company, caterpillar)
    response = client.post(
        f"/companies/{company_id}/run-scenario",
        json={
            "distributions": {
                "revenue_growth": {
                    "distribution": "TRIANGULAR",
                    "low": 0.10,
                    "mode": -0.05,
                    "high": 0.20,
                }
            }
        },
    )
    assert response.status_code == 422
    assert "low <= mode <= high" in response.text


def test_too_many_trials_is_refused_with_a_reason(client, load_company, caterpillar, settings):
    company_id = _load_valuable_caterpillar(client, load_company, caterpillar)
    response = client.post(
        f"/companies/{company_id}/run-scenario",
        json={"n_trials": settings.scenario_max_trials + 1},
    )
    assert response.status_code == 422
    assert "percentiles stop moving" in response.json()["detail"]


def test_an_unknown_run_id_is_a_404(client, load_company, caterpillar):
    company_id = _load_valuable_caterpillar(client, load_company, caterpillar)
    missing = "00000000-0000-0000-0000-000000000999"
    assert client.get(f"/companies/{company_id}/scenario-results/{missing}").status_code == 404
