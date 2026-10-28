"""Analysis endpoints.

Each POST runs one stage and appends a result row; each GET returns the latest.
Appending rather than overwriting is deliberate - re-running after correcting a
statement should leave the earlier result in place, because "the number changed
when we fixed the filing" is exactly the audit trail this kind of tool needs.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status

from app.enums import Distribution
from app.models import PeerCompany
from app.routers.deps import AppSettings, CurrentCompany, DbSession
from app.schemas import (
    BankruptcyRiskOut,
    BankruptcyRiskRequest,
    DcfValuationOut,
    DcfValuationRequest,
    EarningsQualityOut,
    HealthScoreOut,
    InsightAnswerOut,
    InsightQuestionRequest,
    InsightReportOut,
    PeerCompanyOut,
    PeerSetCreate,
    RatioAnalysisOut,
    ScenarioRunOut,
    ScenarioRunRequest,
    ShockSpecIn,
)
from app.schemas.market import ResearchMemoOut
from app.services import analysis_pipeline as pipeline
from app.services import market_pipeline
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


@router.post("/{company_id}/compute-earnings-quality", response_model=EarningsQualityOut)
def compute_earnings_quality_endpoint(
    company: CurrentCompany, db: DbSession, settings: AppSettings
):
    """Piotroski F-Score and Beneish M-Score for the latest year on file.

    Does not refuse on one fiscal year: the caller sees exactly which tests that
    costs them rather than a 409 saying only "upload more data".
    """
    _require_statements(company)
    row, _, _ = pipeline.run_earnings_quality(company, db, settings)
    return row


@router.get("/{company_id}/earnings-quality", response_model=EarningsQualityOut)
def get_earnings_quality(company: CurrentCompany):
    if not company.earnings_quality:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No earnings quality analysis yet. POST /compute-earnings-quality first.",
        )
    return company.earnings_quality[-1]


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


@router.post("/{company_id}/compute-valuation", response_model=DcfValuationOut, tags=["valuation"])
def compute_valuation_endpoint(
    company: CurrentCompany,
    db: DbSession,
    settings: AppSettings,
    payload: DcfValuationRequest | None = None,
):
    """Run the DCF under the supplied assumptions, or the declared defaults.

    Returns 200 even on a refusal, carrying confidence UNUSABLE and the reason:
    a slider dragged past WACC should show why the number vanished.
    """
    _require_statements(company)
    request = payload or DcfValuationRequest()
    overrides, beta_source = _with_market_beta(company, db, settings, request.model_dump())
    assumptions = pipeline.DcfAssumptions.defaults(settings, **overrides)
    row, _ = pipeline.run_dcf_valuation(company, db, settings, assumptions, beta_source)
    return row


@router.get("/{company_id}/valuation", response_model=DcfValuationOut, tags=["valuation"])
def get_valuation(company: CurrentCompany):
    if not company.dcf_valuations:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No valuation yet. POST /compute-valuation first.",
        )
    return company.dcf_valuations[-1]


def _with_market_beta(company, db, settings, overrides: dict) -> tuple[dict, dict | None]:
    """Fill beta from a regression on the company's listing when the request left it unset."""
    if overrides.get("beta") is not None:
        return overrides, {"source": "REQUEST"}
    estimated, detail = market_pipeline.dcf_beta(company, db, settings)
    if estimated is None:
        return overrides, None
    return {**overrides, "beta": estimated}, detail


def _shock_from_request(spec: ShockSpecIn) -> pipeline.ShockSpec:
    """Translate the wire shape into the simulator's uniform (low, base, high)."""
    if spec.distribution is Distribution.TRIANGULAR:
        return pipeline.ShockSpec(spec.distribution, low=spec.low, base=spec.mode, high=spec.high)
    return pipeline.ShockSpec(spec.distribution, base=spec.mu, high=spec.sigma)


@router.post("/{company_id}/run-scenario", response_model=ScenarioRunOut, tags=["scenario"])
def run_scenario_endpoint(
    company: CurrentCompany,
    db: DbSession,
    settings: AppSettings,
    payload: ScenarioRunRequest | None = None,
):
    """Monte Carlo the deterministic suite and store the distribution.

    Unspecified shocks fall back to defaults, so a bare POST is a complete run.
    """
    _require_statements(company)
    request = payload or ScenarioRunRequest()

    n_trials = request.n_trials or settings.scenario_default_trials
    if n_trials > settings.scenario_max_trials:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"n_trials of {n_trials} exceeds the configured maximum of "
                f"{settings.scenario_max_trials}. Past a few thousand trials the "
                "percentiles stop moving and the extra work buys nothing but latency."
            ),
        )

    shocks = dict(pipeline.DEFAULT_SHOCKS)
    for name, spec in (request.distributions or {}).items():
        if name not in pipeline.DEFAULT_SHOCKS:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"'{name}' is not a shock this simulator applies. Accepted: "
                    f"{sorted(pipeline.DEFAULT_SHOCKS)}. An unrecognised key would "
                    "otherwise be stored in input_distributions and perturb nothing, "
                    "which is the most misleading possible outcome."
                ),
            )
        shocks[name] = _shock_from_request(spec)

    dcf_assumptions = None
    if request.include_dcf:
        dcf_request = request.dcf or DcfValuationRequest()
        overrides, _ = _with_market_beta(company, db, settings, dcf_request.model_dump())
        dcf_assumptions = pipeline.DcfAssumptions.defaults(settings, **overrides)

    row, _ = pipeline.run_scenario(
        company,
        db,
        settings,
        n_trials=n_trials,
        seed=request.seed if request.seed is not None else settings.scenario_default_seed,
        shocks=shocks,
        dcf_assumptions=dcf_assumptions,
    )
    return row


@router.get(
    "/{company_id}/scenario-results/{run_id}", response_model=ScenarioRunOut, tags=["scenario"]
)
def get_scenario_result(company: CurrentCompany, run_id: uuid.UUID):
    for run in company.scenario_runs:
        if run.id == run_id:
            return run
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"No scenario run {run_id} for this company.",
    )


@router.get(
    "/{company_id}/scenario-results", response_model=list[ScenarioRunOut], tags=["scenario"]
)
def list_scenario_results(company: CurrentCompany):
    return company.scenario_runs


@router.post(
    "/{company_id}/peer-set",
    response_model=list[PeerCompanyOut],
    status_code=status.HTTP_201_CREATED,
    tags=["peers"],
)
def replace_peer_set(company: CurrentCompany, payload: PeerSetCreate, db: DbSession):
    """Attach or replace this company's sourced peer set. Replaces, never appends."""
    for existing in list(company.peer_companies):
        db.delete(existing)
    rows = [
        PeerCompany(
            company_id=company.id,
            peer_name=peer.peer_name,
            industry=peer.industry or company.industry,
            fiscal_year=peer.fiscal_year or company.fiscal_year,
            source=peer.source,
            ratios=peer.ratios,
        )
        for peer in payload.peers
    ]
    db.add_all(rows)
    db.commit()
    db.refresh(company)
    return company.peer_companies


@router.get("/{company_id}/peer-set", response_model=list[PeerCompanyOut], tags=["peers"])
def get_peer_set(company: CurrentCompany):
    return company.peer_companies


@router.get("/{company_id}/peer-benchmark", tags=["peers"])
def get_peer_benchmark(company: CurrentCompany, db: DbSession, settings: AppSettings):
    """Per-ratio z-score, percentile and rank, read from the stored ratio analysis."""
    ratios = pipeline.latest_ratio_result(company)
    if ratios is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "The peer benchmark standardises the stored ratio analysis. "
                "POST /compute-ratios first."
            ),
        )
    result = pipeline.run_peer_benchmark(company, db, settings, ratios)
    return {
        "company_id": str(company.id),
        "peer_count": result.peer_count,
        "peer_names": [peer.peer_name for peer in company.peer_companies],
        "ratios": result.ratios,
        "category_percentiles": result.category_percentiles,
        "industry_percentile": result.industry_percentile,
        "omitted": result.omitted,
        "calculation_basis": result.calculation_basis,
    }


@router.post("/{company_id}/generate-insights", response_model=InsightReportOut)
def generate_insights_endpoint(company: CurrentCompany, db: DbSession, settings: AppSettings):
    """Narrate the three stored results.

    Requires all three, and says which one is missing, rather than quietly
    narrating a partial picture. The insight report is the artefact a reader
    trusts least, so it gets the strictest precondition.
    """
    ratios = pipeline.latest_ratio_result(company)
    if ratios is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Run /compute-ratios first."
        )
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


@router.post("/{company_id}/insights/ask", response_model=InsightAnswerOut)
def ask_insight_question(
    company: CurrentCompany,
    payload: InsightQuestionRequest,
    db: DbSession,
    settings: AppSettings,
):
    """Answer a follow-up using only the stored structured context.

    Reads one report's frozen context and nothing else. A question needing an
    uncomputed figure comes back as an explicit refusal naming it.
    """
    if not company.insight_reports:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "There is no insight report to ask about. POST /generate-insights first: "
                "the answer comes from that report's stored context, so the context has "
                "to exist before a question can be grounded in it."
            ),
        )
    _, entry = pipeline.answer_insight_question(company, db, settings, payload.question)
    return entry


@router.post("/{company_id}/research-memo", response_model=ResearchMemoOut, tags=["research"])
def generate_research_memo(company: CurrentCompany, db: DbSession, settings: AppSettings):
    """Multi-agent memo: grounding, four specialists in parallel, curator, editor.

    Reads only stored results. Every figure in the memo is checked against the
    context its specialist was given, and the trace records what each node did.
    """
    row = pipeline.run_research_memo(company, db, settings)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "The memo narrates stored results. Run /compute-ratios, "
                "/compute-bankruptcy-risk and /compute-health-score first "
                "(or /run-full-analysis)."
            ),
        )
    return row


@router.get("/{company_id}/research-memo", response_model=ResearchMemoOut, tags=["research"])
def get_research_memo(company: CurrentCompany):
    if not company.research_memos:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No research memo yet. POST /research-memo first.",
        )
    return company.research_memos[-1]


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
    """Ratios -> risk suite -> earnings quality -> health score -> narrative.

    A convenience for the demo flow and the sample-data loader. Every stage is
    still separately addressable, because a user who disagrees with one stage
    should be able to re-run just that stage.
    """
    _require_statements(company)
    _, ratio_result = pipeline.run_ratios(company, db)
    _, risk_result = pipeline.run_bankruptcy_risk(company, db, settings)
    pipeline.run_earnings_quality(company, db, settings)
    _, health_result = pipeline.run_health_score(company, db, settings, ratio_result)
    return pipeline.run_insights(
        company, db, settings, ratios=ratio_result, risk=risk_result, health=health_result
    )
