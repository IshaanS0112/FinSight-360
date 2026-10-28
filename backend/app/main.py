"""FinSight 360 API entrypoint."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.db.session import Base, engine
from app.routers import analysis, companies, market, portfolio
from app.services.altman_zscore import (
    COMPONENT_DEFINITIONS,
    COMPONENT_MEANINGS,
    FINANCIAL_SECTOR_REFUSAL,
    MODEL_CITATIONS,
    MODEL_COMPONENTS,
)
from app.services.analysis_pipeline import DEFAULT_SHOCKS
from app.services.bankruptcy_risk import (
    OHLSON_CITATION,
    SIZE_SUBSTITUTION_NOTE,
)
from app.services.bankruptcy_risk import (
    TERM_DEFINITIONS as OHLSON_TERM_DEFINITIONS,
)
from app.services.bankruptcy_risk import (
    TERM_MEANINGS as OHLSON_TERM_MEANINGS,
)
from app.services.benchmarks import load_reference_bands
from app.services.earnings_quality import (
    BENEISH_CITATION,
    F_SCORE_TESTS,
    M_SCORE_DEFINITIONS,
    M_SCORE_MEANINGS,
    PIOTROSKI_CITATION,
    ROA_BASIS_NOTE,
)
from app.services.line_items import ITEM_BY_KEY
from app.services.merton_model import MERTON_CITATION, NAIVE_CITATION
from app.services.peer_benchmarking import INTERPRETATION_LIMIT as PEER_INTERPRETATION_LIMIT
from app.services.ratio_engine import FORMULAS, PERCENT_RATIOS
from app.services.ratio_extensions import (
    CYCLE_DEFINITIONS,
    DAYS_IN_YEAR,
    DUPONT_DEFINITIONS,
)
from app.services.scenario_simulator import PERTURBATION_NOTE

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("finsight360")


@asynccontextmanager
async def lifespan(_: FastAPI):
    # create_all is adequate here because the schema is append-only for V1.
    # A migration tool (Alembic) is the correct answer the moment a column needs
    # to change shape - noted in docs/architecture.md.
    Base.metadata.create_all(bind=engine)

    settings = get_settings()
    _, provenance = load_reference_bands(settings.reference_benchmarks_path)
    logger.info("Reference benchmark table: %s", provenance)
    if not settings.anthropic_api_key:
        logger.info(
            "No ANTHROPIC_API_KEY configured. Insight reports will use the deterministic "
            "template fallback - every ratio, Z-score, and health score is identical, "
            "only the prose is missing."
        )
    yield


settings = get_settings()

app = FastAPI(
    title="FinSight 360 API",
    version="3.0.0",
    description=(
        "Corporate financial health and risk intelligence. A multi-year ratio engine with "
        "DuPont and cash-cycle decomposition; the Altman Z / Z' / Z'' family applied to the "
        "population each was estimated on, reconciled against Ohlson's O-Score through an "
        "explicit consensus verdict; Piotroski and Beneish for earnings quality; a DCF with "
        "no hidden assumptions; Monte Carlo stress testing; and peer benchmarking by "
        "z-score. Every figure is computed deterministically; the LLM only narrates the "
        "computed output."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for module in (companies, analysis, market, portfolio):
    app.include_router(module.router)


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/methodology", tags=["meta"])
def methodology() -> dict[str, object]:
    """The parameter set currently in force.

    Exposed as an endpoint because the claim this project makes - that the scores
    are computed, not generated - is only checkable if the coefficients, cutoffs,
    and weights behind them are visible without reading the source.
    """
    _, provenance = load_reference_bands(settings.reference_benchmarks_path)
    return {
        "models": {
            "ratio_engine": {
                "formulas": FORMULAS,
                "percent_ratios": sorted(PERCENT_RATIOS),
                "turnover_basis": "ENDING_BALANCE",
                "note": (
                    "Ratio definitions vary between data providers. These are the forms "
                    "implemented; see docs/architecture.md for a worked comparison against "
                    "a published figure."
                ),
            },
            "altman": {
                "variants": {
                    model.value: {
                        "citation": MODEL_CITATIONS[model],
                        "components": list(MODEL_COMPONENTS[model]),
                        "coefficients": settings.altman_coefficients()[model.value],
                        "cutoffs": settings.altman_cutoffs()[model.value],
                        "x4_equity_basis": (
                            "MARKET_VALUE" if model.value == "Z_1968" else "BOOK_VALUE"
                        ),
                    }
                    for model in MODEL_COMPONENTS
                },
                "component_definitions": COMPONENT_DEFINITIONS,
                "component_meanings": COMPONENT_MEANINGS,
                "emerging_market_constant": settings.zdprime_emerging_market_constant,
                "borderline_margin": settings.zone_borderline_margin,
                "financial_sector_policy": FINANCIAL_SECTOR_REFUSAL,
            },
            "ohlson": {
                "citation": OHLSON_CITATION,
                "coefficients": settings.ohlson_coefficients(),
                "term_definitions": OHLSON_TERM_DEFINITIONS,
                "term_meanings": OHLSON_TERM_MEANINGS,
                "probability_transform": "e^O / (1 + e^O)",
                "distress_cutoff_probability": settings.ohlson_distress_probability,
                # The one documented departure from the published model.
                "size_substitution": SIZE_SUBSTITUTION_NOTE,
            },
            "consensus_verdict": {
                "rule": (
                    "LOW_RISK: Altman zone SAFE and Ohlson probability below "
                    f"{settings.consensus_low_risk_probability}. HIGH_RISK: zone DISTRESS "
                    f"and probability above {settings.consensus_high_risk_probability}. "
                    "MIXED_SIGNAL otherwise. INDETERMINATE when either model declined."
                ),
                "thresholds": {
                    "low_risk_below": settings.consensus_low_risk_probability,
                    "high_risk_above": settings.consensus_high_risk_probability,
                },
                "mixed_signal_is_an_output": (
                    "Two independently estimated models disagreeing is information. It is "
                    "reported as MIXED_SIGNAL rather than averaged away or resolved by "
                    "preferring one model."
                ),
            },
            "piotroski": {
                "citation": PIOTROSKI_CITATION,
                "tests": F_SCORE_TESTS,
                "bands": {"STRONG": "8-9", "MIXED": "5-7", "WEAK": "0-4"},
                "roa_basis": ROA_BASIS_NOTE,
                "partial_policy": (
                    "A partial F-Score is reported as the sum of the tests that could be "
                    "evaluated, with no band, because the bands are calibrated on all nine."
                ),
            },
            "beneish": {
                "citation": BENEISH_CITATION,
                "coefficients": settings.beneish_coefficients(),
                "component_definitions": M_SCORE_DEFINITIONS,
                "component_meanings": M_SCORE_MEANINGS,
                "thresholds": {
                    "beneish_1999": settings.beneish_threshold,
                    "stricter_commonly_cited": settings.beneish_strict_threshold,
                },
                "partial_policy": (
                    "All eight components are required. Each index sits near 1.0 by "
                    "construction, so a dropped term removes roughly its whole coefficient "
                    "from a score measured against a threshold of "
                    f"{settings.beneish_threshold}, and substituting the neutral value 1.0 "
                    "would assert that nothing changed year over year - the claim the "
                    "model exists to test."
                ),
            },
            "dcf": {
                "status": "STANDARD TEXTBOOK CONSTRUCTION, not a proprietary method",
                "formulas": {
                    "fcff": "EBIT*(1-tax) + D&A - CapEx - change in NWC",
                    "cost_of_equity": "Rf + beta*(Rm - Rf)   [CAPM]",
                    "cost_of_debt": "interest_expense / total_debt   [pre-tax]",
                    "wacc": "(E/V)*Re + (D/V)*Rd*(1-tax)",
                    "terminal_value": "FCFF_n*(1+g) / (WACC - g)   [Gordon growth]",
                    "enterprise_value": "sum FCFF_t/(1+WACC)^t + TV/(1+WACC)^n",
                    "equity_value": "enterprise_value - (total_debt - cash)",
                },
                "defaults": {
                    "projection_years": settings.dcf_projection_years,
                    "risk_free_rate": settings.dcf_risk_free_rate,
                    "equity_risk_premium": settings.dcf_equity_risk_premium,
                    "beta": settings.dcf_default_beta,
                    "tax_rate": settings.dcf_tax_rate,
                    "terminal_growth": settings.dcf_terminal_growth,
                },
                "defaults_note": (
                    "Defaults, not constants. Every one is overridable per request and is "
                    "echoed in the stored assumptions. A hidden default in a DCF would be "
                    "the single most misleading thing in this codebase."
                ),
                "beta_policy": (
                    f"Beta is an input with a default of {settings.dcf_default_beta}, not a "
                    "measurement. Computing a real beta needs a price history this tool "
                    "does not hold."
                ),
                "minimum_wacc_terminal_spread": settings.dcf_min_wacc_terminal_spread,
                "refusals": [
                    "Terminal growth within the minimum spread of WACC: the Gordon "
                    "denominator collapses and the value diverges.",
                    "Negative base-year EBIT: reported, but flagged UNUSABLE, because "
                    "every projected FCFF inherits the sign.",
                    "No share count: enterprise and equity value stand, the per-share "
                    "figure is withheld.",
                ],
            },
            "peer_benchmarking": {
                "method": "percentile = Phi(z)*100, z = (value - peer_mean) / peer_stdev",
                "standard_deviation": "sample (n-1)",
                "minimum_peers": settings.benchmark_min_peers,
                "interpretation_limit": PEER_INTERPRETATION_LIMIT,
            },
            "scenario_simulator": {
                "status": "NOT A MODEL. A re-run of the models above under sampled inputs.",
                "default_trials": settings.scenario_default_trials,
                "max_trials": settings.scenario_max_trials,
                "default_seed": settings.scenario_default_seed,
                "shocks": sorted(DEFAULT_SHOCKS),
                "perturbation_model": PERTURBATION_NOTE,
                "percentile_method": (
                    "Empirical order statistics of the trials run. No distribution is "
                    "fitted to the output."
                ),
                "distress_probability": (
                    "The share of trials landing in the Altman distress zone under the "
                    "specified shocks. A sensitivity measure, not a probability of default."
                ),
            },
            "market_data": {
                "returns": "adjusted close, month-end to month-end",
                "market_capitalisation": "split-adjusted close x shares outstanding",
                "no_look_ahead": "every statistic uses prices on or before the fiscal year end",
                "beta": (
                    f"OLS of monthly excess returns on {settings.market_benchmark_ticker} over "
                    f"{settings.market_beta_window_months} months; Blume-adjusted "
                    "(0.67 * beta + 0.33) for the DCF"
                ),
                "risk_free_rate_for_ratios": settings.market_risk_free_rate,
                "var_confidence": settings.market_var_confidence,
                "minimum_observations": settings.market_min_observations,
            },
            "merton": {
                "citation": MERTON_CITATION,
                "naive_cross_check": NAIVE_CITATION,
                "default_point": "short-term debt + 0.5 x long-term debt (KMV)",
                "volatility_window_months": settings.merton_volatility_months,
                "horizon_years": settings.merton_horizon_years,
                "risk_free_rates": settings.merton_risk_free_rates,
                "market_view_bands": {
                    "low_pd_below": settings.merton_low_pd,
                    "high_pd_above": settings.merton_high_pd,
                },
                "financial_sector_policy": (
                    "Not refused. Merton reads market equity rather than accounting ratios, "
                    "so it is the model the Altman and Ohlson refusals point to for banks."
                ),
            },
            "portfolio_lab": {
                "inspired_by": ["PyPortfolio/PyPortfolioOpt", "letianzj/QuantResearch"],
                "expected_returns": ["mean_historical (geometric)", "ema_historical", "capm"],
                "risk_models": ["sample", "ledoit_wolf (constant-variance target)"],
                "optimisers": [
                    "min_volatility",
                    "max_sharpe",
                    "efficient_return",
                    "hrp",
                    "equal_weight",
                    "inverse_volatility",
                ],
                "constraints": "long-only, fully invested, per-asset caps",
                "credit_overlay": (
                    "exclude_high_risk sets a HIGH_RISK company's weight to zero; cap_mixed "
                    "also caps a MIXED_SIGNAL company at 10%"
                ),
                "risk_decomposition": "parametric component VaR (Euler allocation)",
                "minimum_observations": settings.portfolio_min_observations,
                "refusals": [
                    "a mixed-currency universe",
                    "fewer than the minimum overlapping observations",
                    "weight caps that cannot sum to 100%",
                    "a tangency portfolio when no asset beats the risk-free rate",
                ],
            },
            "research_agents": {
                "inspired_by": "guy-hartstein/company-research-agent",
                "pipeline": [
                    "grounding: split the stored context into one slice per specialist",
                    "analysts: credit, forensic accounting, valuation, market - in parallel",
                    "curator: drop any sentence carrying a figure absent from its slice",
                    "disagreements: found by code, never by the model",
                    "editor: compiles curated sections only, then is curated itself",
                ],
                "departure_from_inspiration": (
                    "No web search. An agent that can fetch new numbers is an agent that "
                    "can invent them, so every input is a figure FinSight already stored."
                ),
                "number_tolerance": settings.research_number_tolerance,
                "model": settings.anthropic_model or "not configured",
                "effort": settings.llm_effort,
            },
            "ratio_extensions": {
                "dupont_definitions": DUPONT_DEFINITIONS,
                "cycle_definitions": CYCLE_DEFINITIONS,
                "days_in_year": DAYS_IN_YEAR,
                "reconciliation": (
                    "DuPont is an algebraic identity. The product of its terms is "
                    "reconciled against ROE computed directly and the residual is reported."
                ),
                "cagr_policy": (
                    "CAGR is reported only where both endpoints are strictly positive. A "
                    "compound rate across a sign change is not a real number."
                ),
            },
            "health_score": {
                "status": "PROJECT-DEFINED COMPOSITE, not an established model",
                "weights": settings.health_weights,
                "normalisation": (
                    "score = 50 + 50*clamp((value-benchmark)/|benchmark| / full_credit_ratio, -1, 1); "
                    "50 = exactly at benchmark; direction inverted for lower-is-better ratios"
                ),
                "full_credit_ratio": settings.health_full_credit_ratio,
                "peer_percentile": (
                    "Null in V1, because nothing behind the field was a percentile. Now "
                    "computed by services/peer_benchmarking.py from real z-scores against "
                    "an explicitly sourced peer set - and still null wherever fewer than "
                    f"{settings.benchmark_min_peers} peers reported the ratio, which is "
                    "most of the time. Read its interpretation_limit before quoting it."
                ),
            },
        },
        "line_item_vocabulary": sorted(ITEM_BY_KEY),
        "benchmark_provenance": provenance,
        "benchmark_min_peers": settings.benchmark_min_peers,
        "balance_sheet_tolerance_pct": settings.balance_sheet_tolerance_pct,
        "llm_output_contract": (
            "JSON shape enforced by structured outputs (output_config.format), never by an "
            "assistant prefill. Every failure degrades to a deterministic template."
        ),
        "llm_role": (
            "Narration only. Every figure in an insight report exists in "
            "structured_context before the model is called, and cited metric keys not "
            "present in that context are dropped."
        ),
    }
