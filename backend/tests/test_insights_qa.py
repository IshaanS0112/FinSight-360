"""The grounded follow-up Q&A.

# roadmap: v2-08-insights-qa

Every test here is about the boundary rather than the prose. The endpoint's
whole value is that it refuses: a question needing a figure nobody computed
comes back as an explicit refusal naming the figure, not an estimate.
"""

from __future__ import annotations

import json

import pytest

from app.enums import NarrativeSource, SectorClass
from app.services.altman_zscore import compute_z_score
from app.services.benchmarks import load_reference_bands
from app.services.health_score import compute_health_score
from app.services.insights_generator import (
    QA_SYSTEM_PROMPT,
    REFUSAL_PREFIX,
    _allowed_metric_keys,
    _flatten_context_keys,
    _validate_answer,
    answer_question,
    build_structured_context,
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
        earnings_quality={
            "piotroski_f_score": 7,
            "f_score_band": "MIXED",
            "f_score_components": {"accruals": {"status": "PASS", "points": 1}},
            "beneish_m_score": -2.571,
            "m_score_components": {"dsri": {"ratio": 1.0316}},
        },
    )


def _reply(**fields) -> str:
    return json.dumps({"answer": "a", "grounded_in": [], "refused": False, **fields})


# --- The context builder stays backward compatible ----------------------------


def test_a_v1_context_is_unchanged_by_the_v2_sections(cat_items, caterpillar, settings):
    """Sections that were not computed are absent, not present and empty.

    An empty section would let a model cite a Beneish component for a company
    that never had one computed.
    """
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
    minimal = build_structured_context(
        company_id="x",
        company_name="Caterpillar Inc.",
        industry="industrial machinery",
        sector_class="PUBLIC_MANUFACTURER",
        fiscal_year=2024,
        currency="USD",
        units="MILLIONS",
        data_source="test",
        ratios=ratios,
        risk=risk,
        health=health,
    )
    assert set(minimal) == {
        "company",
        "ratios",
        "bankruptcy_risk",
        "health_score",
        "calculation_basis",
    }
    assert "beneish_m_score" not in _allowed_metric_keys(minimal)


def test_the_citation_vocabulary_grows_only_with_what_was_computed(context):
    allowed = _allowed_metric_keys(context)
    assert {"current_ratio", "x1", "piotroski_f_score", "beneish_m_score", "dsri"} <= allowed
    assert "ohlson_o_score" not in allowed, "the suite was not run for this fixture"
    assert "ebitda_to_sponsor_adjusted_leverage" not in allowed


def test_flattened_keys_carry_both_the_leaf_and_the_path(context):
    keys = _flatten_context_keys(context)
    assert "current_ratio" in keys
    assert "ratios.liquidity.current_ratio" in keys
    assert "company.data_source" in keys


# --- The refusal boundary -------------------------------------------------------


def test_an_answer_grounded_in_nothing_becomes_a_refusal(context):
    """The load-bearing guarantee of the endpoint.

    An answer citing no field in the context is indistinguishable from an
    invented one, so it is converted rather than shown.
    """
    result = _validate_answer(
        _reply(answer="EBITDA was 18,500.", grounded_in=["ebitda"], refused=False), context
    )
    assert result["refused"] is True
    assert result["grounded_in"] == []
    assert result["dropped_citations"] == 1
    assert REFUSAL_PREFIX in result["answer"]
    assert "18,500" not in result["answer"], "the invented figure must not survive"


def test_partially_grounded_answers_keep_only_the_verified_citations(context):
    result = _validate_answer(
        _reply(
            answer="Current ratio is 1.42 and EBITDA margin is 28%.",
            grounded_in=["current_ratio", "ebitda_margin"],
            refused=False,
        ),
        context,
    )
    assert result["refused"] is False
    assert result["grounded_in"] == ["current_ratio"]
    assert result["dropped_citations"] == 1


def test_an_explicit_refusal_is_passed_through_with_no_citations(context):
    result = _validate_answer(
        _reply(
            answer="Free cash flow was not computed for this company.",
            grounded_in=[],
            refused=True,
        ),
        context,
    )
    assert result["refused"] is True
    assert result["answer"].startswith("Free cash flow")


def test_dotted_paths_count_as_valid_citations(context):
    result = _validate_answer(
        _reply(answer="ok", grounded_in=["ratios.liquidity.current_ratio"], refused=False), context
    )
    assert result["grounded_in"] == ["ratios.liquidity.current_ratio"]


def test_a_code_fenced_answer_is_still_parsed(context):
    raw = "```json\n" + _reply(answer="fenced", grounded_in=["current_ratio"]) + "\n```"
    assert _validate_answer(raw, context)["answer"] == "fenced"


def test_a_response_without_an_answer_key_is_rejected(context):
    with pytest.raises(ValueError, match="answer"):
        _validate_answer(json.dumps({"grounded_in": ["current_ratio"]}), context)


# --- The system prompt ----------------------------------------------------------


def test_the_prompt_makes_refusal_the_first_rule():
    # Collapsed because the prompt is hard-wrapped and the rules span lines.
    prompt = " ".join(QA_SYSTEM_PROMPT.split())
    assert "you MUST refuse" in prompt
    assert "do not derive it from a related figure" in prompt
    assert "empty grounded_in list will be rejected" in prompt
    assert "Do not offer investment advice" in prompt


# --- The no-API-key path --------------------------------------------------------


def test_without_an_api_key_a_named_metric_is_looked_up(context, settings):
    result = answer_question(context, "What is the current_ratio?", settings)
    assert result["answered_by"] == NarrativeSource.TEMPLATE_FALLBACK.value
    assert result["refused"] is False
    assert result["grounded_in"] == ["current_ratio"]
    assert "1.4155" in result["answer"]


def test_without_an_api_key_an_unnamed_metric_is_refused(context, settings):
    result = answer_question(context, "How much free cash flow did they generate?", settings)
    assert result["refused"] is True
    assert REFUSAL_PREFIX in result["answer"]


def test_the_fallback_refuses_exactly_where_the_model_path_would(context, settings):
    """Same boundary, no API key required to demonstrate it."""
    assert answer_question(context, "What was EBITDA?", settings)["refused"] is True
    assert answer_question(context, "Show me roa", settings)["refused"] is False


def test_a_structured_metric_resolves_to_its_own_value(context, settings):
    """An Altman component is a dict; the lookup finds the ratio inside it."""
    result = answer_question(context, "What is x1?", settings)
    assert result["refused"] is False
    assert result["grounded_in"] == ["x1"]


# --- Over HTTP --------------------------------------------------------------------


def test_asking_before_a_report_exists_is_a_conflict(client, load_company, caterpillar):
    company_id = load_company(caterpillar)
    response = client.post(
        f"/companies/{company_id}/insights/ask", json={"question": "Is it safe?"}
    )
    assert response.status_code == 409
    assert "stored context" in response.json()["detail"]


def test_an_answer_is_appended_to_the_report_thread(client, load_company, caterpillar):
    company_id = load_company(caterpillar)
    client.post(f"/companies/{company_id}/run-full-analysis")

    first = client.post(
        f"/companies/{company_id}/insights/ask", json={"question": "What is the current_ratio?"}
    )
    assert first.status_code == 200
    assert first.json()["refused"] is False

    second = client.post(
        f"/companies/{company_id}/insights/ask",
        json={"question": "What is their customer churn rate?"},
    )
    assert second.json()["refused"] is True

    report = client.get(f"/companies/{company_id}/insights-report").json()
    assert len(report["qa_thread"]) == 2
    assert [entry["refused"] for entry in report["qa_thread"]] == [False, True]
    assert report["qa_thread"][0]["report_id"] == report["id"]


def test_the_thread_keeps_refusals_rather_than_tidying_them_away(client, load_company, caterpillar):
    """A refusal is a record of what this tool knew at the time."""
    company_id = load_company(caterpillar)
    client.post(f"/companies/{company_id}/run-full-analysis")
    client.post(f"/companies/{company_id}/insights/ask", json={"question": "What is EBITDA?"})
    thread = client.get(f"/companies/{company_id}/insights-report").json()["qa_thread"]
    assert thread[0]["refused"] is True
    assert thread[0]["grounded_in"] == []


def test_an_empty_question_is_rejected_at_the_schema(client, load_company, caterpillar):
    company_id = load_company(caterpillar)
    client.post(f"/companies/{company_id}/run-full-analysis")
    assert (
        client.post(f"/companies/{company_id}/insights/ask", json={"question": ""}).status_code
        == 422
    )


def test_the_report_context_carries_every_stage_that_ran(client, load_company, caterpillar):
    """The narrative can only cite what the pipeline actually computed and stored."""
    company_id = load_company(caterpillar)
    client.post(f"/companies/{company_id}/run-full-analysis")
    context = client.get(f"/companies/{company_id}/insights-report").json()["structured_context"]

    assert context["risk_suite"]["consensus_verdict"] in {
        "LOW_RISK",
        "HIGH_RISK",
        "MIXED_SIGNAL",
        "INDETERMINATE",
    }
    assert context["earnings_quality"]["piotroski_f_score"] is not None
    assert "dupont" in context
    # No peer set attached and no valuation or scenario run, so those are absent.
    assert "peer_benchmark" not in context
    assert "valuation" not in context
    assert "scenario" not in context
