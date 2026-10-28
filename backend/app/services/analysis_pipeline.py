"""Orchestration: turn stored statements into stored analyses.

The router layer stays thin because everything ordering-sensitive lives here.
The order is not arbitrary - the health score needs the ratios, and the insight
report needs all three - so each stage reads the persisted output of the last
rather than recomputing it. That is what makes the stored ``structured_context``
an audit trail instead of a snapshot of a second, parallel computation.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.session import utc_now
from app.enums import AltmanModel, Distribution, ResultConfidence, SectorClass
from app.models import (
    BankruptcyRisk,
    Company,
    DcfValuation,
    EarningsQuality,
    FinancialHealthScore,
    InsightReport,
    RatioAnalysis,
    ResearchMemo,
    ScenarioRun,
)
from app.services import line_items as li
from app.services.altman_zscore import ZScoreResult
from app.services.bankruptcy_risk import compute_risk_suite
from app.services.benchmarks import load_reference_bands
from app.services.dcf_valuation import DcfAssumptions, DcfResult, compute_dcf
from app.services.earnings_quality import (
    BeneishResult,
    PiotroskiResult,
    compute_beneish_m_score,
    compute_piotroski_f_score,
)
from app.services.enums_bridge import health_result_from_row, zscore_result_from_row
from app.services.health_score import HealthScoreResult, compute_health_score
from app.services.insights_generator import (
    answer_question,
    build_structured_context,
    generate_narrative,
)
from app.services.peer_benchmarking import PeerBenchmarkResult, compute_peer_benchmark
from app.services.ratio_engine import RatioResult, compute_ratios
from app.services.ratio_extensions import compute_extensions
from app.services.research_agents import run_pipeline
from app.services.scenario_simulator import ScenarioResult, ShockSpec, run_simulation

logger = logging.getLogger(__name__)


def fiscal_years(company: Company) -> list[int]:
    """Every fiscal year this company has statements for, oldest first."""
    return sorted({s.fiscal_year for s in company.statements if s.fiscal_year is not None})


def latest_fiscal_year(company: Company) -> int | None:
    years = fiscal_years(company)
    return years[-1] if years else None


def merged_line_items(company: Company, fiscal_year: int | None = None) -> dict[str, float]:
    """Every reported line item for one fiscal year, latest upload winning.

    Defaults to the most recent year on file. Merging across years would produce
    ratios belonging to no year at all.
    """
    year = fiscal_year if fiscal_year is not None else latest_fiscal_year(company)
    statements = [
        (s.statement_type, s.line_items)
        for s in company.statements
        if year is None or s.fiscal_year == year
    ]
    return li.merge_statements(statements)


def line_items_by_year(company: Company) -> dict[int, dict[str, float]]:
    """``{fiscal_year: merged line items}`` for every year on file."""
    return {year: merged_line_items(company, year) for year in fiscal_years(company)}


def prior_year_items(company: Company, fiscal_year: int) -> tuple[int, dict[str, float]] | None:
    """The most recent year strictly before fiscal_year, with its line items.

    None when there is no earlier year; callers refuse rather than substitute.
    """
    earlier = [y for y in fiscal_years(company) if y < fiscal_year]
    if not earlier:
        return None
    year = earlier[-1]
    return year, merged_line_items(company, year)


def run_ratios(
    company: Company, db: Session, fiscal_year: int | None = None
) -> tuple[RatioAnalysis, RatioResult]:
    year = fiscal_year if fiscal_year is not None else latest_fiscal_year(company)
    items = merged_line_items(company, year)
    result = compute_ratios(items)
    prior = prior_year_items(company, year) if year is not None else None
    extensions = compute_extensions(
        items=items,
        prior_items=prior[1] if prior else None,
        history={y: compute_ratios(i).all_ratios for y, i in line_items_by_year(company).items()},
        fiscal_year=year,
    )
    row = RatioAnalysis(
        company_id=company.id,
        fiscal_year=year,
        dupont=extensions.dupont,
        cash_conversion_cycle=extensions.cash_conversion_cycle,
        trend=extensions.trend,
        liquidity_ratios=result.liquidity,
        profitability_ratios=result.profitability,
        leverage_ratios=result.leverage,
        efficiency_ratios=result.efficiency,
        omitted_ratios=result.omitted + extensions.omitted,
        calculation_basis={
            **result.calculation_basis,
            "confidence": result.confidence.value,
            "fiscal_year": year,
            "fiscal_years_on_file": fiscal_years(company),
            "extensions": extensions.calculation_basis,
        },
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
    year = latest_fiscal_year(company)
    items = merged_line_items(company, year)
    prior = prior_year_items(company, year) if year is not None else None
    suite = compute_risk_suite(
        items=items,
        prior_items=prior[1] if prior else None,
        sector_class=SectorClass(company.sector_class),
        settings=settings,
        model_override=model_override,
        emerging_market_adjustment=emerging_market_adjustment,
    )
    result = suite.altman
    row = BankruptcyRisk(
        company_id=company.id,
        fiscal_year=year,
        zscore_variant=result.model.value,
        model=result.model.value,
        altman_z_score=result.score,
        zone=result.zone.value,
        confidence=result.confidence.value,
        component_scores=result.components,
        omitted_components=result.omitted_components,
        variant_scores=suite.variants,
        ohlson_o_score=suite.ohlson.o_score,
        ohlson_probability=suite.ohlson.probability,
        ohlson_components=suite.ohlson.components,
        ohlson_omitted=suite.ohlson.omitted,
        consensus_verdict=suite.consensus.value,
        calculation_basis={
            # Altman basis stays top level so every V1 key keeps its position.
            **result.calculation_basis,
            "borderline": result.borderline,
            "prior_fiscal_year": prior[0] if prior else None,
            "ohlson": suite.ohlson.calculation_basis,
            "ohlson_confidence": suite.ohlson.confidence.value,
            "ohlson_probability_bounds": suite.ohlson.probability_bounds,
            "consensus": suite.calculation_basis,
        },
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row, result


def run_earnings_quality(
    company: Company, db: Session, settings: Settings
) -> tuple[EarningsQuality, PiotroskiResult, BeneishResult]:
    """Piotroski and Beneish for the latest year, against the year before it.

    First stage that can fail for want of history rather than a line item; it
    reports that as a reason, not a zero.
    """
    year = latest_fiscal_year(company)
    items = merged_line_items(company, year)
    prior = prior_year_items(company, year) if year is not None else None
    prior_items_map = prior[1] if prior else None

    piotroski = compute_piotroski_f_score(items, prior_items_map)
    beneish = compute_beneish_m_score(items, prior_items_map, settings)

    confidence = (
        ResultConfidence.COMPLETE
        if piotroski.confidence is ResultConfidence.COMPLETE
        and beneish.confidence is ResultConfidence.COMPLETE
        else ResultConfidence.UNUSABLE
        if piotroski.confidence is ResultConfidence.UNUSABLE
        and beneish.confidence is ResultConfidence.UNUSABLE
        else ResultConfidence.PARTIAL
    )

    row = EarningsQuality(
        company_id=company.id,
        fiscal_year=year,
        prior_fiscal_year=prior[0] if prior else None,
        piotroski_f_score=piotroski.score,
        f_score_band=piotroski.band.value if piotroski.band else None,
        f_score_components=piotroski.components,
        beneish_m_score=beneish.m_score,
        m_score_components=beneish.components,
        manipulation_flag=beneish.manipulation_flag,
        confidence=confidence.value,
        omitted=[{"model": "piotroski", **entry} for entry in piotroski.omitted]
        + [{"model": "beneish", **entry} for entry in beneish.omitted],
        calculation_basis={
            "piotroski": piotroski.calculation_basis,
            "piotroski_confidence": piotroski.confidence.value,
            "beneish": beneish.calculation_basis,
            "beneish_confidence": beneish.confidence.value,
            "beneish_strict_manipulation_flag": beneish.strict_manipulation_flag,
            "fiscal_year": year,
            "prior_fiscal_year": prior[0] if prior else None,
            "why_both": (
                "Piotroski says whether the fundamentals are getting stronger. Beneish "
                "says whether the fundamentals are worth believing. Running only the "
                "first is screening a number; running both is screening the number and "
                "the filing that produced it."
            ),
        },
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row, piotroski, beneish


def attached_peer_sets(company: Company) -> list[dict[str, float]]:
    """Ratios from the peer companies explicitly attached to this analysis.

    Preferred over the same-industry sweep: an attached peer carries a required
    source citation and was chosen deliberately.
    """
    return [dict(peer.ratios) for peer in company.peer_companies if peer.ratios]


def peer_ratio_sets(company: Company, db: Session) -> list[dict[str, float]]:
    """The peer set: attached peers, else same-industry, same-units companies."""
    attached = attached_peer_sets(company)
    if attached:
        return attached

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
        sets.append(
            {
                **latest.liquidity_ratios,
                **latest.profitability_ratios,
                **latest.leverage_ratios,
                **latest.efficiency_ratios,
            }
        )
    return sets


def run_peer_benchmark(
    company: Company, db: Session, settings: Settings, ratios: RatioResult
) -> PeerBenchmarkResult:
    """z-score and percentile for every ratio, against this company's peer set."""
    return compute_peer_benchmark(
        company_ratios=ratios.all_ratios,
        peer_ratios=peer_ratio_sets(company, db),
        settings=settings,
    )


def run_health_score(
    company: Company, db: Session, settings: Settings, ratios: RatioResult
) -> tuple[FinancialHealthScore, HealthScoreResult]:
    """The V1 composite, with peer_percentile finally populated.

    compute_health_score is untouched. peer_percentile now carries the
    peer-benchmarking engine's weighted figure, and stays null below the
    minimum peer count.
    """
    table, provenance = load_reference_bands(settings.reference_benchmarks_path)
    result = compute_health_score(
        ratios=ratios,
        industry=company.industry,
        peer_ratios=peer_ratio_sets(company, db),
        reference_table=table,
        reference_provenance=provenance,
        settings=settings,
    )
    benchmark = run_peer_benchmark(company, db, settings, ratios)
    row = FinancialHealthScore(
        company_id=company.id,
        overall_score=result.overall_score,
        component_scores=result.component_scores,
        peer_percentile=benchmark.industry_percentile,
        confidence=result.confidence.value,
        calculation_basis={
            **result.calculation_basis,
            "peer_percentile_source": (
                "services/peer_benchmarking.py. Null in V1, because nothing behind the "
                "field was a percentile. Now the weighted mean of the per-category "
                "percentiles, and still null wherever the peer set is too small to "
                "support one."
            ),
            "peer_benchmark": {
                "industry_percentile": benchmark.industry_percentile,
                "category_percentiles": benchmark.category_percentiles,
                "peer_count": benchmark.peer_count,
                "interpretation_limit": benchmark.calculation_basis["interpretation_limit"],
            },
        },
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row, result


def run_dcf_valuation(
    company: Company,
    db: Session,
    settings: Settings,
    assumptions: DcfAssumptions,
    beta_source: dict[str, Any] | None = None,
) -> tuple[DcfValuation, DcfResult]:
    """Value the latest fiscal year under the supplied assumptions."""
    year = latest_fiscal_year(company)
    items = merged_line_items(company, year)
    result = compute_dcf(
        items=items, assumptions=assumptions, settings=settings, beta_source=beta_source
    )
    row = DcfValuation(
        company_id=company.id,
        base_fiscal_year=year,
        assumptions=result.assumptions,
        fcff_projection=result.fcff_projection,
        wacc=result.wacc,
        terminal_value=result.terminal_value,
        enterprise_value=result.enterprise_value,
        equity_value=result.equity_value,
        implied_share_price=result.implied_share_price,
        upside_downside_pct=result.upside_downside_pct,
        confidence=result.confidence.value,
        calculation_basis={
            **result.calculation_basis,
            "base_fiscal_year": year,
            "cost_of_equity": result.cost_of_equity,
            "cost_of_debt": result.cost_of_debt,
            "omitted": result.omitted,
        },
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row, result


DEFAULT_SHOCKS: dict[str, ShockSpec] = {
    # Triangular on growth (downside / base / upside); normal on the shifts.
    "revenue_growth": ShockSpec(Distribution.TRIANGULAR, low=-0.10, base=0.03, high=0.10),
    "margin_shift": ShockSpec(Distribution.NORMAL, base=0.0, high=0.03),
    "wacc_shift": ShockSpec(Distribution.NORMAL, base=0.0, high=0.01),
}


def run_scenario(
    company: Company,
    db: Session,
    settings: Settings,
    *,
    n_trials: int,
    seed: int,
    shocks: dict[str, ShockSpec],
    dcf_assumptions: DcfAssumptions | None,
) -> tuple[ScenarioRun, ScenarioResult]:
    """Monte Carlo the deterministic suite over the latest fiscal year."""
    year = latest_fiscal_year(company)
    items = merged_line_items(company, year)
    prior = prior_year_items(company, year) if year is not None else None
    table, provenance = load_reference_bands(settings.reference_benchmarks_path)

    result = run_simulation(
        items=items,
        prior_items=prior[1] if prior else None,
        sector_class=SectorClass(company.sector_class),
        settings=settings,
        shocks=shocks,
        dcf_assumptions=dcf_assumptions,
        reference_table=table,
        reference_provenance=provenance,
        peer_ratios=peer_ratio_sets(company, db),
        industry=company.industry,
        n_trials=n_trials,
        seed=seed,
    )

    row = ScenarioRun(
        company_id=company.id,
        n_trials=result.n_trials,
        seed=result.seed,
        input_distributions=result.input_distributions,
        result_summary=result.summary,
        calculation_basis={
            **result.calculation_basis,
            "base_fiscal_year": year,
            "confidence": result.confidence.value,
            "dcf_assumptions": asdict(dcf_assumptions) if dcf_assumptions else None,
        },
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
    return RatioResult(
        liquidity=dict(row.liquidity_ratios),
        profitability=dict(row.profitability_ratios),
        leverage=dict(row.leverage_ratios),
        efficiency=dict(row.efficiency_ratios),
        omitted=list(row.omitted_ratios),
        calculation_basis=dict(row.calculation_basis),
        confidence=ResultConfidence(row.calculation_basis.get("confidence", "PARTIAL")),
    )


def stored_v2_context(
    company: Company, db: Session, settings: Settings, ratios: RatioResult
) -> dict[str, Any]:
    """The V2 sections of the structured context, read from what was stored.

    Every section comes from a persisted row, never a fresh computation, so the
    narrative describes the numbers the API actually returned. A stage that was
    never run contributes nothing.
    """
    sections: dict[str, Any] = {}

    if company.ratio_analyses:
        latest = company.ratio_analyses[-1]
        sections["dupont"] = dict(latest.dupont or {})
        sections["cash_conversion_cycle"] = dict(latest.cash_conversion_cycle or {})
        sections["trend"] = dict(latest.trend or {})

    if company.bankruptcy_risks:
        risk_row = company.bankruptcy_risks[-1]
        basis = dict(risk_row.calculation_basis or {})
        sections["risk_suite"] = {
            "fiscal_year": risk_row.fiscal_year,
            "applicable_variant": risk_row.zscore_variant,
            "variant_scores": dict(risk_row.variant_scores or {}),
            "ohlson": {
                "o_score": risk_row.ohlson_o_score,
                "probability": risk_row.ohlson_probability,
                "components": dict(risk_row.ohlson_components or {}),
                "omitted": list(risk_row.ohlson_omitted or []),
                "confidence": basis.get("ohlson_confidence"),
                "size_substitution": (basis.get("ohlson") or {}).get("size_substitution"),
                "probability_bounds": basis.get("ohlson_probability_bounds"),
            },
            "consensus_verdict": risk_row.consensus_verdict,
            "consensus_reason": (basis.get("consensus") or {}).get("consensus_reason"),
        }

    if company.earnings_quality:
        quality = company.earnings_quality[-1]
        quality_basis = dict(quality.calculation_basis or {})
        sections["earnings_quality"] = {
            "fiscal_year": quality.fiscal_year,
            "prior_fiscal_year": quality.prior_fiscal_year,
            "piotroski_f_score": quality.piotroski_f_score,
            "f_score_band": quality.f_score_band,
            "f_score_components": dict(quality.f_score_components or {}),
            "beneish_m_score": quality.beneish_m_score,
            "m_score_components": dict(quality.m_score_components or {}),
            "manipulation_flag": quality.manipulation_flag,
            "strict_manipulation_flag": quality_basis.get("beneish_strict_manipulation_flag"),
            "thresholds": (quality_basis.get("beneish") or {}).get("thresholds"),
            "interpretation_limit": (quality_basis.get("beneish") or {}).get(
                "interpretation_limit"
            ),
            "confidence": quality.confidence,
            "omitted": list(quality.omitted or []),
        }

    benchmark = run_peer_benchmark(company, db, settings, ratios)
    if benchmark.peer_count:
        sections["peer_benchmark"] = {
            "peer_count": benchmark.peer_count,
            "peer_names": [peer.peer_name for peer in company.peer_companies],
            "ratios": benchmark.ratios,
            "category_percentiles": benchmark.category_percentiles,
            "industry_percentile": benchmark.industry_percentile,
            "interpretation_limit": benchmark.calculation_basis["interpretation_limit"],
        }

    if company.dcf_valuations:
        dcf_row = company.dcf_valuations[-1]
        dcf_basis = dict(dcf_row.calculation_basis or {})
        sections["valuation"] = {
            "base_fiscal_year": dcf_row.base_fiscal_year,
            "assumptions": dict(dcf_row.assumptions or {}),
            "wacc": dcf_row.wacc,
            "terminal_value": dcf_row.terminal_value,
            "enterprise_value": dcf_row.enterprise_value,
            "equity_value": dcf_row.equity_value,
            "implied_share_price": dcf_row.implied_share_price,
            "upside_downside_pct": dcf_row.upside_downside_pct,
            "confidence": dcf_row.confidence,
            "terminal_value_share_of_ev": dcf_basis.get("terminal_value_share_of_ev"),
            "fcff_projection": list(dcf_row.fcff_projection or []),
            "refusal": dcf_basis.get("refusal"),
            "beta_note": dcf_basis.get("beta_note"),
        }

    if company.market_risks:
        market_row = company.market_risks[-1]
        sections["market"] = {
            "ticker": market_row.ticker,
            "fiscal_year": market_row.fiscal_year,
            "merton_distance_to_default": market_row.merton_distance_to_default,
            "merton_probability_of_default": market_row.merton_probability_of_default,
            "naive_distance_to_default": market_row.naive_distance_to_default,
            "naive_probability_of_default": market_row.naive_probability_of_default,
            "beta": market_row.beta,
            "adjusted_beta": market_row.adjusted_beta,
            "market_view": market_row.market_view,
            "risk_metrics": dict(market_row.risk_metrics or {}),
            "confidence": market_row.confidence,
            "fiscal_year_end": (market_row.calculation_basis or {}).get("fiscal_year_end"),
        }

    if company.scenario_runs:
        run = company.scenario_runs[-1]
        sections["scenario"] = {
            "n_trials": run.n_trials,
            "seed": run.seed,
            "input_distributions": dict(run.input_distributions or {}),
            "summary": dict(run.result_summary or {}),
            "perturbation_model": (run.calculation_basis or {}).get("perturbation_model"),
        }

    return sections


def full_context(company: Company, db: Session, settings: Settings) -> dict[str, Any] | None:
    """The complete structured context, rebuilt from stored rows. None if a core stage is missing."""
    ratios = latest_ratio_result(company)
    if ratios is None or not company.bankruptcy_risks or not company.health_scores:
        return None
    return build_structured_context(
        company_id=str(company.id),
        company_name=company.name,
        industry=company.industry,
        sector_class=company.sector_class,
        fiscal_year=latest_fiscal_year(company) or company.fiscal_year,
        currency=company.currency,
        units=company.units,
        data_source=company.data_source,
        ratios=ratios,
        risk=zscore_result_from_row(company.bankruptcy_risks[-1]),
        health=health_result_from_row(company.health_scores[-1]),
        **stored_v2_context(company, db, settings, ratios),
    )


def run_research_memo(company: Company, db: Session, settings: Settings) -> ResearchMemo | None:
    """Run the multi-agent memo over the stored context. None if a core stage is missing."""
    context = full_context(company, db, settings)
    if context is None:
        return None
    result = run_pipeline(context, settings)
    row = ResearchMemo(
        company_id=company.id,
        memo=result["memo"],
        sections=result["sections"],
        trace=result["trace"],
        curator_report=result["curator_report"],
        generated_by=result["generated_by"],
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def answer_insight_question(
    company: Company, db: Session, settings: Settings, question: str
) -> tuple[InsightReport, dict[str, Any]]:
    """Answer a follow-up from the stored context and append it to the thread.

    Appended, never rewritten: a refusal is part of the record.
    """
    report = company.insight_reports[-1]
    answer = answer_question(dict(report.structured_context or {}), question, settings)

    entry = {
        "question": question,
        "answer": answer["answer"],
        "grounded_in": answer.get("grounded_in", []),
        "refused": answer.get("refused", False),
        "answered_by": answer.get("answered_by"),
        "dropped_citations": answer.get("dropped_citations", 0),
        "asked_at": utc_now().isoformat(),
        "report_id": str(report.id),
    }
    report.qa_thread = list(report.qa_thread or []) + [entry]
    db.add(report)
    db.commit()
    db.refresh(report)
    return report, entry


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
        fiscal_year=latest_fiscal_year(company) or company.fiscal_year,
        currency=company.currency,
        units=company.units,
        data_source=company.data_source,
        ratios=ratios,
        risk=risk,
        health=health,
        **stored_v2_context(company, db, settings, ratios),
    )
    narrative = generate_narrative(context, settings)
    row = InsightReport(
        company_id=company.id,
        structured_context=context,
        ai_narrative=narrative,
        generated_by=narrative.get("generated_by", "template_fallback"),
        qa_thread=[],
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
