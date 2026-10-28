"""Monte Carlo over the deterministic engines. No new model, no new score.

Re-runs the same Altman, Ohlson, health-score and DCF code with perturbed
inputs and reports the spread. See PERTURBATION_NOTE for exactly what moves and
what is held fixed - the simplification biases the distributions tighter than
reality, and the result says so.

The seed is an input and is stored: a distribution that cannot be regenerated
exactly is an anecdote. Percentiles are empirical order statistics; nothing is
fitted to the output.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any

from app.config import Settings
from app.enums import Distribution, ResultConfidence, SectorClass, Zone
from app.services import line_items as li
from app.services.altman_zscore import compute_z_score
from app.services.bankruptcy_risk import compute_ohlson_o_score, consensus_verdict
from app.services.dcf_valuation import DcfAssumptions, compute_dcf
from app.services.health_score import compute_health_score
from app.services.ratio_engine import compute_ratios

_EPS = 1e-9

PERTURBATION_NOTE = (
    "Each trial scales revenue by the sampled growth rate, sets EBIT to revenue x "
    "(base operating margin + sampled margin shift), moves net income with EBIT, "
    "and lets retained earnings and shareholders' equity absorb the change in net "
    "income. Total assets, total liabilities and working capital are held at their "
    "reported values. This understates dispersion: in a bad year the asset base and "
    "current liabilities move as well, so the true Altman and Ohlson distributions "
    "are wider than the ones reported here."
)


@dataclass(frozen=True)
class ShockSpec:
    """One sampled input: a shape and its parameters."""

    distribution: Distribution
    # Triangular: low / base / high. Normal: mu / sigma (carried in low / high).
    low: float = 0.0
    base: float = 0.0
    high: float = 0.0

    def sample(self, rng: random.Random) -> float:
        if self.distribution is Distribution.TRIANGULAR:
            return rng.triangular(self.low, self.high, self.base)
        return rng.gauss(self.base, self.high)

    def describe(self) -> dict[str, Any]:
        if self.distribution is Distribution.TRIANGULAR:
            return {
                "distribution": self.distribution.value,
                "low": self.low,
                "mode": self.base,
                "high": self.high,
            }
        return {"distribution": self.distribution.value, "mu": self.base, "sigma": self.high}


@dataclass
class ScenarioResult:
    n_trials: int
    seed: int
    summary: dict[str, Any] = field(default_factory=dict)
    input_distributions: dict[str, Any] = field(default_factory=dict)
    confidence: ResultConfidence = ResultConfidence.COMPLETE
    calculation_basis: dict[str, Any] = field(default_factory=dict)


def percentiles(values: list[float]) -> dict[str, float] | None:
    """Empirical p5 / p50 / p95 plus the mean, or None for an empty sample.

    Nearest-rank on the sorted sample. No distribution is fitted to the output.
    """
    if not values:
        return None
    ordered = sorted(values)
    count = len(ordered)

    def at(fraction: float) -> float:
        index = min(count - 1, max(0, int(round(fraction * (count - 1)))))
        return ordered[index]

    return {
        "p5": round(at(0.05), 4),
        "p50": round(at(0.50), 4),
        "p95": round(at(0.95), 4),
        "mean": round(sum(ordered) / count, 4),
        "min": round(ordered[0], 4),
        "max": round(ordered[-1], 4),
        "n": count,
    }


def perturb(
    items: dict[str, float], *, revenue_growth: float, margin_shift: float
) -> dict[str, float]:
    """Apply one trial's shocks. Returns a new dict; the base year is not mutated."""
    shocked = dict(items)
    revenue = li.get(items, "revenue")
    ebit = li.get(items, "ebit")
    net_income = li.get(items, "net_income")

    if revenue is None or revenue < _EPS:
        return shocked

    new_revenue = revenue * (1.0 + revenue_growth)
    shocked["revenue"] = new_revenue

    if ebit is None:
        return shocked

    base_margin = ebit / revenue
    new_ebit = new_revenue * (base_margin + margin_shift)
    shocked["ebit"] = new_ebit
    delta_ebit = new_ebit - ebit

    if net_income is not None:
        # Earnings flow through one for one below the operating line.
        new_net_income = net_income + delta_ebit
        shocked["net_income"] = new_net_income
        retained = li.get(items, "retained_earnings")
        if retained is not None:
            shocked["retained_earnings"] = retained + (new_net_income - net_income)
        equity = li.get(items, "shareholder_equity")
        if equity is not None:
            shocked["shareholder_equity"] = equity + (new_net_income - net_income)

    if li.get(items, "cogs") is not None and li.get(items, "gross_profit") is not None:
        # Keep the gross-profit identity intact so gross margin stays computable.
        shocked["gross_profit"] = new_revenue - shocked["cogs"]

    return shocked


def run_simulation(
    *,
    items: dict[str, float],
    prior_items: dict[str, float] | None,
    sector_class: SectorClass,
    settings: Settings,
    shocks: dict[str, ShockSpec],
    dcf_assumptions: DcfAssumptions | None,
    reference_table: dict[str, dict[str, float]],
    reference_provenance: str,
    peer_ratios: list[dict[str, float]],
    industry: str | None,
    n_trials: int,
    seed: int,
) -> ScenarioResult:
    """Re-run the deterministic suite ``n_trials`` times under sampled inputs."""
    rng = random.Random(seed)
    revenue_shock = shocks["revenue_growth"]
    margin_shock = shocks["margin_shift"]
    wacc_shock = shocks.get("wacc_shift")

    health_scores: list[float] = []
    z_scores: list[float] = []
    ohlson_probabilities: list[float] = []
    equity_values: list[float] = []
    implied_prices: list[float] = []
    zone_counts: dict[str, int] = {zone.value: 0 for zone in Zone}
    verdict_counts: dict[str, int] = {}
    dcf_refusals = 0

    base_z = compute_z_score(items=items, sector_class=sector_class, settings=settings)

    for _ in range(n_trials):
        trial_items = perturb(
            items,
            revenue_growth=revenue_shock.sample(rng),
            margin_shift=margin_shock.sample(rng),
        )

        ratios = compute_ratios(trial_items)
        health = compute_health_score(
            ratios=ratios,
            # Must be the company's own industry, or trials benchmark against the
            # generic row while the point estimate used the industry row.
            industry=industry,
            peer_ratios=peer_ratios,
            reference_table=reference_table,
            reference_provenance=reference_provenance,
            settings=settings,
        )
        if health.overall_score is not None:
            health_scores.append(health.overall_score)

        # Applicable variant only; the three-variant sweep is for the point estimate.
        zscore = compute_z_score(
            items=trial_items,
            sector_class=sector_class,
            settings=settings,
            model_override=base_z.model,
        )
        if zscore.score is not None:
            z_scores.append(zscore.score)
        zone_counts[zscore.zone.value] += 1

        ohlson = compute_ohlson_o_score(
            items=trial_items,
            prior_items=prior_items,
            settings=settings,
            sector_class=sector_class,
        )
        if ohlson.probability is not None:
            ohlson_probabilities.append(ohlson.probability)

        verdict, _ = consensus_verdict(
            zone=zscore.zone, ohlson_probability=ohlson.probability, settings=settings
        )
        verdict_counts[verdict.value] = verdict_counts.get(verdict.value, 0) + 1

        if dcf_assumptions is not None:
            shift = wacc_shock.sample(rng) if wacc_shock else 0.0
            trial_assumptions = dcf_assumptions
            if abs(shift) > _EPS:
                base_wacc = dcf_assumptions.wacc_override
                if base_wacc is not None:
                    trial_assumptions = DcfAssumptions(
                        **{**dcf_assumptions.__dict__, "wacc_override": base_wacc + shift}
                    )
                else:
                    # No override in force, so shift the cost of equity instead -
                    # beta and the risk-free rate are the dials CAPM actually has.
                    trial_assumptions = DcfAssumptions(
                        **{
                            **dcf_assumptions.__dict__,
                            "risk_free_rate": dcf_assumptions.risk_free_rate + shift,
                        }
                    )
            dcf = compute_dcf(items=trial_items, assumptions=trial_assumptions, settings=settings)
            if dcf.equity_value is None:
                dcf_refusals += 1
            else:
                equity_values.append(dcf.equity_value)
                if dcf.implied_share_price is not None:
                    implied_prices.append(dcf.implied_share_price)

    distress = zone_counts[Zone.DISTRESS.value]
    summary: dict[str, Any] = {
        "health_score": percentiles(health_scores),
        "z_score": percentiles(z_scores),
        "ohlson_probability": percentiles(ohlson_probabilities),
        "dcf_equity_value": percentiles(equity_values),
        "dcf_implied_share_price": percentiles(implied_prices),
        "zone_shares": {
            zone: round(count / n_trials, 4) for zone, count in zone_counts.items() if count
        },
        "consensus_shares": {
            verdict: round(count / n_trials, 4) for verdict, count in verdict_counts.items()
        },
        "distress_probability": round(distress / n_trials, 4),
        "altman_model": base_z.model.value,
        "dcf_trials_refused": dcf_refusals,
    }

    confidence = (
        ResultConfidence.UNUSABLE
        if not z_scores and not health_scores
        else ResultConfidence.PARTIAL
        if not z_scores or not health_scores or (dcf_assumptions is not None and not equity_values)
        else ResultConfidence.COMPLETE
    )

    return ScenarioResult(
        n_trials=n_trials,
        seed=seed,
        summary=summary,
        input_distributions={name: spec.describe() for name, spec in shocks.items()},
        confidence=confidence,
        calculation_basis={
            "what_this_is": (
                "The same Altman, Ohlson, health-score and DCF code as the point "
                "estimate, run n times with perturbed inputs. No new model and no new "
                "score: the only thing the simulator adds is the spread."
            ),
            "perturbation_model": PERTURBATION_NOTE,
            "percentile_method": (
                "Empirical order statistics of the trials actually run. No distribution "
                "is fitted to the output, because fitting a normal to a non-linear "
                "model's output would reintroduce the assumption the simulation exists "
                "to avoid."
            ),
            "reproducibility": (
                f"Seeded with {seed} and stored on the run. Re-running with the same "
                "seed, trial count and distributions reproduces this distribution "
                "exactly."
            ),
            "altman_variant_note": (
                f"Every trial uses {base_z.model.value}, the variant selected for this "
                "company's sector class at the point estimate. The three-variant sweep "
                "is a comparison for a reader, not something to distribute."
            ),
            "dcf_refusal_note": (
                f"{dcf_refusals} of {n_trials} trials produced no valuation, almost "
                "always because the sampled shock drove operating margin negative or the "
                "shifted discount rate closed on terminal growth. Those trials are "
                "excluded from the DCF percentiles and counted here rather than being "
                "filled with a zero."
            )
            if dcf_assumptions is not None
            else None,
            "distress_probability_meaning": (
                "The share of trials landing in the Altman distress zone under these "
                "assumptions. It is a sensitivity measure, not a probability of default: "
                "it says how fragile the zone classification is to the shocks specified, "
                "and nothing about their real-world likelihood."
            ),
        },
    )
