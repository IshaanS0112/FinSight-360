"""Orchestration: turn stored statements into stored analyses.

The router layer stays thin because everything ordering-sensitive lives here.
The order is not arbitrary - the health score needs the ratios, and the insight
report needs all three - so each stage reads the persisted output of the last
rather than recomputing it. That is what makes the stored ``structured_context``
an audit trail instead of a snapshot of a second, parallel computation.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.enums import AltmanModel, SectorClass
from app.models import (
    BankruptcyRisk,
    Company,
    FinancialHealthScore,
    InsightReport,
    RatioAnalysis,
)
from app.services import line_items as li
from app.services.altman_zscore import ZScoreResult, compute_z_score
from app.services.benchmarks import load_reference_bands
from app.services.health_score import HealthScoreResult, compute_health_score
from app.services.insights_generator import build_structured_context, generate_narrative
from app.services.ratio_engine import RatioResult, compute_ratios

logger = logging.getLogger(__name__)


def merged_line_items(company: Company) -> dict[str, float]:
    """Every reported line item for this company, latest upload winning."""
    return li.merge_statements(
        [(s.statement_type, s.line_items) for s in company.statements]
    )


def run_ratios(company: Company, db: Session) -> tuple[RatioAnalysis, RatioResult]:
    items = merged_line_items(company)
    result = compute_ratios(items)
    row = RatioAnalysis(
        company_id=company.id,
        liquidity_ratios=result.liquidity,
        profitability_ratios=result.profitability,
        leverage_ratios=result.leverage,
        efficiency_ratios=result.efficiency,
        omitted_ratios=result.omitted,
        calculation_basis={**result.calculation_basis, "confidence": result.confidence.value},
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row, result


def run_bankruptcy_risk(
    company: Company,
    db: Session,
    settings: Settings,
    *,
    model_override: AltmanModel | None = None,
    emerging_market_adjustment: bool = False,
) -> tuple[BankruptcyRisk, ZScoreResult]:
    items = merged_line_items(company)
    result = compute_z_score(
        items=items,
        sector_class=SectorClass(company.sector_class),
        settings=settings,
        model_override=model_override,
        emerging_market_adjustment=emerging_market_adjustment,
    )
    row = BankruptcyRisk(
        company_id=company.id,
        model=result.model.value,
        altman_z_score=result.score,
        zone=result.zone.value,
        confidence=result.confidence.value,
        component_scores=result.components,
        omitted_components=result.omitted_components,
        calculation_basis={**result.calculation_basis, "borderline": result.borderline},
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row, result


def peer_ratio_sets(company: Company, db: Session) -> list[dict[str, float]]:
    """Latest computed ratios for every other company in the same industry.

    Same-industry only, and same reporting units - ratios are dimensionless so
    currency does not matter, but comparing a company reporting in millions
    against one reporting in crore would be silently wrong if any absolute
    figure ever entered the comparison.
    """
    if not company.industry:
        return []

    peers = db.scalars(
        select(Company).where(
            Company.industry == company.industry,
            Company.id != company.id,
            Company.units == company.units,
        )
    ).all()

    sets: list[dict[str, float]] = []
    for peer in peers:
        if not peer.ratio_analyses:
            continue
        latest = peer.ratio_analyses[-1]
        sets.append({
            **latest.liquidity_ratios,
            **latest.profitability_ratios,
            **latest.leverage_ratios,
            **latest.efficiency_ratios,
        })
    return sets


def run_health_score(
    company: Company, db: Session, settings: Settings, ratios: RatioResult
) -> tuple[FinancialHealthScore, HealthScoreResult]:
    table, provenance = load_reference_bands(settings.reference_benchmarks_path)
    result = compute_health_score(
        ratios=ratios,
        industry=company.industry,
        peer_ratios=peer_ratio_sets(company, db),
        reference_table=table,
        reference_provenance=provenance,
        settings=settings,
    )
    row = FinancialHealthScore(
        company_id=company.id,
        overall_score=result.overall_score,
        component_scores=result.component_scores,
        peer_percentile=result.peer_percentile,
        confidence=result.confidence.value,
        calculation_basis=result.calculation_basis,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row, result


def latest_ratio_result(company: Company) -> RatioResult | None:
    """Rehydrate the last stored ratio analysis into the engine's dataclass.

    Reading the persisted row rather than recomputing is deliberate: the insight
    report must narrate the numbers that were actually stored and returned to the
    user, not a fresh computation that could differ if a statement was corrected
    in between.
    """
    if not company.ratio_analyses:
        return None
    row = company.ratio_analyses[-1]
    from app.enums import ResultConfidence

    return RatioResult(
        liquidity=dict(row.liquidity_ratios),
        profitability=dict(row.profitability_ratios),
        leverage=dict(row.leverage_ratios),
        efficiency=dict(row.efficiency_ratios),
        omitted=list(row.omitted_ratios),
        calculation_basis=dict(row.calculation_basis),
        confidence=ResultConfidence(row.calculation_basis.get("confidence", "PARTIAL")),
    )


def run_insights(
    company: Company,
    db: Session,
    settings: Settings,
    *,
    ratios: RatioResult,
    risk: ZScoreResult,
    health: HealthScoreResult,
) -> InsightReport:
    context = build_structured_context(
        company_id=str(company.id),
        company_name=company.name,
        industry=company.industry,
        sector_class=company.sector_class,
        fiscal_year=company.fiscal_year,
        currency=company.currency,
        units=company.units,
        data_source=company.data_source,
        ratios=ratios,
        risk=risk,
        health=health,
    )
    narrative = generate_narrative(context, settings)
    row = InsightReport(
        company_id=company.id,
        structured_context=context,
        ai_narrative=narrative,
        generated_by=narrative.get("generated_by", "template_fallback"),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def validate_balance_sheet(items: dict[str, Any], settings: Settings) -> str | None:
    """Check assets = liabilities + equity, within tolerance.

    Returns an error message, or ``None`` if the sheet balances or cannot be
    checked. This is the cheapest possible guard against a transcription error,
    and it is worth having because every ratio and every Altman component is
    scaled by total assets: one mistyped digit there moves every number in the
    system by the same wrong factor, and nothing downstream would look odd.
    """
    assets = li.get(items, "total_assets")
    liabilities = li.get(items, "total_liabilities")
    equity = li.get(items, "shareholder_equity")
    if assets is None or liabilities is None or equity is None:
        return None
    if assets == 0:
        return "total_assets is zero; every ratio scaled by assets would be undefined."

    residual = abs(assets - (liabilities + equity))
    tolerance = abs(assets) * settings.balance_sheet_tolerance_pct / 100.0
    if residual > tolerance:
        return (
            f"Balance sheet does not balance: total_assets ({assets:,.2f}) - "
            f"(total_liabilities {liabilities:,.2f} + shareholder_equity {equity:,.2f}) = "
            f"{assets - (liabilities + equity):,.2f}, which exceeds the "
            f"{settings.balance_sheet_tolerance_pct}% tolerance of {tolerance:,.2f}. "
            "This is almost always a transcription error, and every asset-scaled ratio "
            "would inherit it."
        )
    return None
