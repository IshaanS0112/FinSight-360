"""Analysis endpoints.

Each POST runs one stage and appends a result row; each GET returns the latest.
Appending rather than overwriting is deliberate - re-running after correcting a
statement should leave the earlier result in place, because "the number changed
when we fixed the filing" is exactly the audit trail this kind of tool needs.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.routers.deps import AppSettings, CurrentCompany, DbSession
from app.schemas import (
    BankruptcyRiskOut,
    BankruptcyRiskRequest,
    HealthScoreOut,
    InsightReportOut,
    RatioAnalysisOut,
)
from app.services import analysis_pipeline as pipeline
from app.services.altman_zscore import ZScoreResult, compute_z_score
from app.services.enums_bridge import (
    health_result_from_row,
    zscore_result_from_row,
)

router = APIRouter(prefix="/companies", tags=["analysis"])

_NO_STATEMENTS = (
    "No financial statements have been uploaded for this company. Upload at least a "
    "balance sheet and an income statement first."
)


def _require_statements(company) -> None:
    if not company.statements:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=_NO_STATEMENTS)


@router.post("/{company_id}/compute-ratios", response_model=RatioAnalysisOut)
def compute_ratios_endpoint(company: CurrentCompany, db: DbSession):
    _require_statements(company)
    row, _ = pipeline.run_ratios(company, db)
    return row


@router.get("/{company_id}/ratio-analysis", response_model=RatioAnalysisOut)
def get_ratio_analysis(company: CurrentCompany):
    if not company.ratio_analyses:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No ratio analysis has been computed yet. POST /compute-ratios first.",
        )
    return company.ratio_analyses[-1]


@router.post("/{company_id}/compute-bankruptcy-risk", response_model=BankruptcyRiskOut)
def compute_bankruptcy_risk_endpoint(
    company: CurrentCompany,
    db: DbSession,
    settings: AppSettings,
    payload: BankruptcyRiskRequest | None = None,
):
    _require_statements(company)
    request = payload or BankruptcyRiskRequest()
    try:
        row, _ = pipeline.run_bankruptcy_risk(
            company,
            db,
            settings,
            model_override=request.model,
            emerging_market_adjustment=request.emerging_market_adjustment,
        )
    except ValueError as exc:
        # Raised when the emerging-market constant is requested for Z or Z'.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return row


@router.get("/{company_id}/bankruptcy-risk", response_model=BankruptcyRiskOut)
def get_bankruptcy_risk(company: CurrentCompany):
    if not company.bankruptcy_risks:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No bankruptcy risk score yet. POST /compute-bankruptcy-risk first.",
        )
    return company.bankruptcy_risks[-1]


@router.post("/{company_id}/compute-health-score", response_model=HealthScoreOut)
def compute_health_score_endpoint(company: CurrentCompany, db: DbSession, settings: AppSettings):
    ratios = pipeline.latest_ratio_result(company)
    if ratios is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "The health score is computed from the stored ratio analysis. "
                "POST /compute-ratios first."
            ),
        )
    row, _ = pipeline.run_health_score(company, db, settings, ratios)
    return row


@router.get("/{company_id}/health-score", response_model=HealthScoreOut)
def get_health_score(company: CurrentCompany):
    if not company.health_scores:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No health score yet. POST /compute-health-score first.",
        )
    return company.health_scores[-1]


@router.post("/{company_id}/generate-insights", response_model=InsightReportOut)
def generate_insights_endpoint(company: CurrentCompany, db: DbSession, settings: AppSettings):
    """Narrate the three stored results.

    Requires all three, and says which one is missing, rather than quietly
    narrating a partial picture. The insight report is the artefact a reader
    trusts least, so it gets the strictest precondition.
    """
    ratios = pipeline.latest_ratio_result(company)
    if ratios is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Run /compute-ratios first.")
    if not company.bankruptcy_risks:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Run /compute-bankruptcy-risk first."
        )
    if not company.health_scores:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Run /compute-health-score first."
        )

    return pipeline.run_insights(
        company,
        db,
        settings,
        ratios=ratios,
        risk=zscore_result_from_row(company.bankruptcy_risks[-1]),
        health=health_result_from_row(company.health_scores[-1]),
    )


@router.get("/{company_id}/insights-report", response_model=InsightReportOut)
def get_insights_report(company: CurrentCompany):
    if not company.insight_reports:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No insight report yet. POST /generate-insights first.",
        )
    return company.insight_reports[-1]


@router.post("/{company_id}/run-full-analysis", response_model=InsightReportOut)
def run_full_analysis(company: CurrentCompany, db: DbSession, settings: AppSettings):
    """Ratios -> Altman -> health score -> narrative, in one call.

    A convenience for the demo flow and the sample-data loader. The four stages
    are still separately addressable, because a user who disagrees with one stage
    should be able to re-run just that stage.
    """
    _require_statements(company)
    _, ratio_result = pipeline.run_ratios(company, db)
    _, risk_result = pipeline.run_bankruptcy_risk(company, db, settings)
    _, health_result = pipeline.run_health_score(company, db, settings, ratio_result)
    return pipeline.run_insights(
        company, db, settings, ratios=ratio_result, risk=risk_result, health=health_result
    )


__all__ = ["router", "ZScoreResult", "compute_z_score"]
