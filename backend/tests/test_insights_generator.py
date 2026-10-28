"""Insight generator: the LLM narrates, and cannot introduce a figure."""

from __future__ import annotations

import json

import pytest

from app.enums import NarrativeSource, SectorClass
from app.services.altman_zscore import compute_z_score
from app.services.benchmarks import load_reference_bands
from app.services.health_score import compute_health_score
from app.services.insights_generator import (
    _validate_narrative,
    build_structured_context,
    generate_narrative,
)
from app.services.ratio_engine import compute_ratios


@pytest.fixture
def context(cat_items, caterpillar, settings):
    ratios = compute_ratios(cat_items)
    risk = compute_z_score(
        items=cat_items, sector_class=SectorClass.PUBLIC_MANUFACTURER, settings=settings
    )
    table, provenance = load_reference_bands(None)
    health = compute_health_score(
        ratios=ratios,
        industry="industrial machinery",
        peer_ratios=[],
        reference_table=table,
        reference_provenance=provenance,
        settings=settings,
    )
    meta = caterpillar["company"]
    return build_structured_context(
        company_id="00000000-0000-0000-0000-000000000001",
        company_name=meta["name"],
        industry=meta["industry"],
        sector_class=meta["sector_class"],
        fiscal_year=meta["fiscal_year"],
        currency=meta["currency"],
        units=meta["units"],
        data_source=meta["data_source"],
        ratios=ratios,
        risk=risk,
        health=health,
    )


# --- The context is complete before the model is called ----------------------


def test_every_reportable_figure_exists_before_the_llm_runs(context):
    """The central claim, asserted rather than described.

    If the score, the zone, the components, the ratios and the health composite
    are all already in the context, there is nothing numeric left for a model to
    contribute.
    """
    assert context["bankruptcy_risk"]["score"] is not None
    assert context["bankruptcy_risk"]["zone"] == "SAFE"
    assert set(context["bankruptcy_risk"]["components"]) == {"x1", "x2", "x3", "x4", "x5"}
    assert context["health_score"]["overall_score"] is not None
    assert len(context["ratios"]["liquidity"]) == 2
    assert context["ratios"]["formulas"], "the formula behind each ratio travels with it"


def test_context_carries_provenance_and_units(context):
    company = context["company"]
    assert company["currency"] == "USD"
    assert company["units"] == "MILLIONS"
    assert "10-K" in company["data_source"] or "SEC" in company["data_source"]


def test_benchmark_deltas_are_precomputed(context):
    deltas = context["health_score"]["benchmark_deltas"]
    assert "current_ratio" in deltas
    entry = deltas["current_ratio"]
    assert entry["delta"] == pytest.approx(entry["value"] - entry["benchmark"], abs=1e-6)


def test_context_is_json_serialisable(context):
    """It is sent to the model as JSON, so this is a real precondition."""
    assert json.loads(json.dumps(context, default=str))


# --- The fallback ------------------------------------------------------------


def test_no_api_key_falls_back_and_says_why(context, settings):
    narrative = generate_narrative(context, settings)
    assert narrative["generated_by"] == NarrativeSource.TEMPLATE_FALLBACK.value
    assert narrative["fallback_reason"] == "no ANTHROPIC_API_KEY configured"


def test_fallback_still_reports_every_number(context, settings):
    narrative = generate_narrative(context, settings)
    assert str(context["bankruptcy_risk"]["score"]) in narrative["bankruptcy_risk_assessment"]
    assert str(context["health_score"]["overall_score"]) in narrative["executive_summary"]
    assert narrative["key_findings"]


def test_fallback_for_a_financial_issuer_does_not_estimate_a_score(infy_items, infosys, settings):
    ratios = compute_ratios(infy_items)
    risk = compute_z_score(items=infy_items, sector_class=SectorClass.FINANCIAL, settings=settings)
    table, provenance = load_reference_bands(None)
    health = compute_health_score(
        ratios=ratios,
        industry="it services",
        peer_ratios=[],
        reference_table=table,
        reference_provenance=provenance,
        settings=settings,
    )
    ctx = build_structured_context(
        company_id="x",
        company_name="A Bank",
        industry="banking",
        sector_class=SectorClass.FINANCIAL.value,
        fiscal_year=2024,
        currency="USD",
        units="MILLIONS",
        data_source="test",
        ratios=ratios,
        risk=risk,
        health=health,
    )
    narrative = generate_narrative(ctx, settings)
    assert "No Altman score was produced" in narrative["bankruptcy_risk_assessment"]
    assert "sector-appropriate model" in narrative["recommendation"]


def test_partial_confidence_drives_the_recommendation(vi_items, settings):
    ratios = compute_ratios(vi_items)
    risk = compute_z_score(
        items=vi_items, sector_class=SectorClass.NON_MANUFACTURER, settings=settings
    )
    table, provenance = load_reference_bands(None)
    health = compute_health_score(
        ratios=ratios,
        industry="telecom",
        peer_ratios=[],
        reference_table=table,
        reference_provenance=provenance,
        settings=settings,
    )
    ctx = build_structured_context(
        company_id="x",
        company_name="Vodafone Idea Limited",
        industry="telecom",
        sector_class="NON_MANUFACTURER",
        fiscal_year=2024,
        currency="INR",
        units="MILLIONS",
        data_source="test",
        ratios=ratios,
        risk=risk,
        health=health,
    )
    narrative = generate_narrative(ctx, settings)
    assert "partial sum" in narrative["recommendation"]
    assert "x3" in narrative["data_limitations"]
    assert "not zero" in narrative["data_limitations"]


# --- Validation of model output ----------------------------------------------


def _model_reply(findings: list[dict]) -> str:
    return json.dumps(
        {
            "executive_summary": "summary",
            "bankruptcy_risk_assessment": "assessment",
            "key_findings": findings,
            "data_limitations": "none",
            "recommendation": "next step",
        }
    )


def test_hallucinated_metric_citations_are_dropped(context):
    raw = _model_reply(
        [
            {"metric": "current_ratio", "observation": "1.42", "implication": "adequate"},
            {
                "metric": "ebitda_to_sponsor_adjusted_leverage",
                "observation": "invented",
                "implication": "x",
            },
            {"metric": "x1", "observation": "0.15", "implication": "positive working capital"},
        ]
    )
    result = _validate_narrative(raw, context)
    assert [f["metric"] for f in result["key_findings"]] == ["current_ratio", "x1"]
    assert result["dropped_citations"] == 1
    assert result["generated_by"] == NarrativeSource.LLM.value


def test_omitted_ratio_cannot_be_cited(vi_items, settings):
    """ROE is withheld for Vodafone Idea, so a model citing it gets it dropped."""
    ratios = compute_ratios(vi_items)
    risk = compute_z_score(
        items=vi_items, sector_class=SectorClass.NON_MANUFACTURER, settings=settings
    )
    table, provenance = load_reference_bands(None)
    health = compute_health_score(
        ratios=ratios,
        industry="telecom",
        peer_ratios=[],
        reference_table=table,
        reference_provenance=provenance,
        settings=settings,
    )
    ctx = build_structured_context(
        company_id="x",
        company_name="Vodafone Idea Limited",
        industry="telecom",
        sector_class="NON_MANUFACTURER",
        fiscal_year=2024,
        currency="INR",
        units="MILLIONS",
        data_source="test",
        ratios=ratios,
        risk=risk,
        health=health,
    )
    result = _validate_narrative(
        _model_reply([{"metric": "roe", "observation": "29.99%", "implication": "strong"}]), ctx
    )
    assert result["key_findings"] == []
    assert result["dropped_citations"] == 1


def test_code_fenced_json_is_still_parsed(context):
    raw = "```json\n" + _model_reply([]) + "\n```"
    assert _validate_narrative(raw, context)["executive_summary"] == "summary"


def test_missing_required_key_is_rejected(context):
    with pytest.raises(ValueError, match="missing required key"):
        _validate_narrative(json.dumps({"executive_summary": "only this"}), context)


def test_non_object_json_is_rejected(context):
    with pytest.raises(ValueError, match="not an object"):
        _validate_narrative("[1, 2, 3]", context)


def test_system_prompt_forbids_treating_omissions_as_zero():
    from app.services.insights_generator import SYSTEM_PROMPT

    assert "Never describe an omitted figure as zero" in SYSTEM_PROMPT
    assert "do not estimate one" in SYSTEM_PROMPT
