"""FinSight 360 API entrypoint."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.db.session import Base, engine
from app.routers import analysis, companies
from app.services.altman_zscore import (
    COMPONENT_DEFINITIONS,
    COMPONENT_MEANINGS,
    FINANCIAL_SECTOR_REFUSAL,
    MODEL_CITATIONS,
    MODEL_COMPONENTS,
)
from app.services.benchmarks import load_reference_bands
from app.services.line_items import ITEM_BY_KEY
from app.services.ratio_engine import FORMULAS, PERCENT_RATIOS

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
    version="1.0.0",
    description=(
        "Corporate financial health and risk intelligence. A ratio engine, the Altman "
        "Z / Z' / Z'' bankruptcy models applied to the population each was estimated on, "
        "and a weighted health composite benchmarked against peers. Every figure is "
        "computed deterministically; the LLM only narrates the computed output."
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

for module in (companies, analysis):
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
            "health_score": {
                "status": "PROJECT-DEFINED COMPOSITE, not an established model",
                "weights": settings.health_weights,
                "normalisation": (
                    "score = 50 + 50*clamp((value-benchmark)/|benchmark| / full_credit_ratio, -1, 1); "
                    "50 = exactly at benchmark; direction inverted for lower-is-better ratios"
                ),
                "full_credit_ratio": settings.health_full_credit_ratio,
                "peer_percentile": (
                    "Always null in V1. A percentile over a handful of peers presented as "
                    "an industry position would be a claim this dataset cannot support."
                ),
            },
        },
        "line_item_vocabulary": sorted(ITEM_BY_KEY),
        "benchmark_provenance": provenance,
        "benchmark_min_peers": settings.benchmark_min_peers,
        "balance_sheet_tolerance_pct": settings.balance_sheet_tolerance_pct,
        "llm_role": (
            "Narration only. Every figure in an insight report exists in "
            "structured_context before the model is called, and cited metric keys not "
            "present in that context are dropped."
        ),
    }
