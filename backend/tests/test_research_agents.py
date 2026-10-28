"""The multi-agent research memo, and the single module that talks to the model.

# roadmap: v3-04-research-agents

No test calls the real API. The client is replaced with a fake that records the
request, so the tests can assert on what is sent (no prefill, structured output)
and on how each failure mode degrades.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import anthropic
import httpx2
import pytest

from app.config import Settings
from app.services import llm
from app.services import research_agents as ra

# --- A fake model client ---------------------------------------------------------


class FakeClient:
    """Records every request and replays a scripted response."""

    calls: list[dict] = []
    reply: object = None

    def __init__(self, **_):
        self.messages = SimpleNamespace(create=self._create)
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        FakeClient.calls.append(kwargs)
        if isinstance(FakeClient.reply, Exception):
            raise FakeClient.reply
        if callable(FakeClient.reply):
            return FakeClient.reply(kwargs)
        return FakeClient.reply


def reply(text="{}", stop_reason="end_turn", category=None):
    return SimpleNamespace(
        stop_reason=stop_reason,
        stop_details=SimpleNamespace(category=category) if category else None,
        content=[SimpleNamespace(type="text", text=text)],
    )


@pytest.fixture
def fake_model(monkeypatch):
    FakeClient.calls = []
    FakeClient.reply = reply(json.dumps({"headline": "h", "body": "b"}))
    monkeypatch.setattr(llm.anthropic, "Anthropic", FakeClient)
    return FakeClient


@pytest.fixture
def keyed():
    return Settings(_env_file=None, anthropic_api_key="test-key", anthropic_model="test-model")


SCHEMA = {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]}


# --- llm.structured_call -----------------------------------------------------------


def test_no_key_is_a_reason_not_an_error(settings):
    assert llm.structured_call(settings, system="s", user_content="u", schema=SCHEMA) == (
        None,
        "no ANTHROPIC_API_KEY configured",
    )


def test_json_comes_from_structured_outputs_not_a_prefill(fake_model, keyed):
    """Assistant prefill returns a 400 on every current model; V2 relied on it."""
    fake_model.reply = reply('{"a": "ok"}')
    parsed, reason = llm.structured_call(keyed, system="s", user_content="u", schema=SCHEMA)
    assert parsed == {"a": "ok"} and reason == ""
    sent = fake_model.calls[0]
    assert [m["role"] for m in sent["messages"]] == ["user"], "no assistant prefill turn"
    assert sent["output_config"]["format"] == {"type": "json_schema", "schema": SCHEMA}
    assert sent["output_config"]["effort"] == keyed.llm_effort


def test_a_refusal_degrades_with_its_category(fake_model, keyed):
    fake_model.reply = reply("", stop_reason="refusal", category="cyber")
    parsed, reason = llm.structured_call(keyed, system="s", user_content="u", schema=SCHEMA)
    assert parsed is None
    assert "declined" in reason and "cyber" in reason


def test_truncation_degrades_rather_than_returning_half_a_json(fake_model, keyed):
    fake_model.reply = reply('{"a": "o', stop_reason="max_tokens")
    assert llm.structured_call(keyed, system="s", user_content="u", schema=SCHEMA)[0] is None


def test_a_connection_failure_degrades(fake_model, keyed):
    fake_model.reply = anthropic.APIConnectionError(request=httpx2.Request("POST", "https://x"))
    parsed, reason = llm.structured_call(keyed, system="s", user_content="u", schema=SCHEMA)
    assert parsed is None and "connection error" in reason


# --- Numeric grounding --------------------------------------------------------------


def test_numbers_are_parsed_and_identifiers_are_not():
    found = {
        raw: (v, d, p)
        for raw, v, d, p in ra.numbers_in(
            "Z_1968 is 3.9203; FY2024 losses were -312,387 and x1 is 0.15. PD 11.1% with −5.96."
        )
    }
    assert found["3.9203"] == (3.9203, 4, False)
    assert found["-312,387"] == (-312387.0, 0, False)
    assert found["11.1%"] == (11.1, 1, True)
    assert found["−5.96"][0] == -5.96
    assert "1968" not in found and "2024" not in found, "identifiers are not figures"


@pytest.mark.parametrize(
    ("value", "decimals", "percent", "grounded"),
    [
        (11.1, 1, True, True),  # 0.111379 written as a percentage
        (3.92, 2, False, True),  # 3.9203 rounded to the sentence's own precision
        (312387.0, 0, False, True),  # -312,387 written as a magnitude
        (9.0, 0, False, True),  # a bare count
        (4.11, 2, False, False),  # invented
        (15.0, 0, False, False),  # past the count limit and not in context
    ],
)
def test_grounding_rules(value, decimals, percent, grounded):
    pool = [0.111379, 3.9203, -312387.0]
    assert ra.is_grounded(value, decimals, percent, pool, 0.01) is grounded


def test_the_curator_removes_only_the_sentence_carrying_the_invented_figure():
    text = "The Z-score is 3.92. EBITDA margin was 28.4%. The zone is SAFE."
    kept, removed, checked = ra.curate_text(text, [3.9203], 0.01)
    assert kept == "The Z-score is 3.92. The zone is SAFE."
    assert removed == [{"sentence": "EBITDA margin was 28.4%.", "ungrounded": ["28.4%"]}]
    assert checked == 2


# --- Grounding and specialists ----------------------------------------------------------

CONTEXT = {
    "company": {"id": "11111111-2222", "name": "Example Co", "fiscal_year": 2024},
    "bankruptcy_risk": {
        "model": "Z_1968",
        "score": 3.9203,
        "zone": "SAFE",
        "cutoffs": {"safe_above": 2.99, "distress_below": 1.81},
    },
    "risk_suite": {
        "consensus_verdict": "LOW_RISK",
        "ohlson": {"probability": 0.111379},
        "variant_scores": {
            "Z_1968": {"zone": "SAFE", "score": 3.9203, "applicable": True},
            "Z_PRIME": {"zone": "GREY", "score": 2.002, "applicable": False},
        },
    },
    "earnings_quality": {
        "piotroski_f_score": 4,
        "f_score_band": "WEAK",
        "f_score_components": {"roa_improving": {"status": "FAIL"}},
        "beneish_m_score": -2.0,
        "manipulation_flag": False,
        "strict_manipulation_flag": True,
    },
    "market": {
        "merton_distance_to_default": 1.30,
        "naive_distance_to_default": 3.16,
        "merton_probability_of_default": 0.0969,
        "market_view": "CONTRADICTS",
        "beta": 1.195,
        "adjusted_beta": 1.1307,
        "risk_metrics": {
            "annualised_volatility": 0.315,
            "max_drawdown": 0.30,
            "historical_var": 0.109,
        },
    },
}


def test_each_specialist_sees_only_its_own_slice():
    credit = ra.scope(CONTEXT, ra.SPECIALISTS[0])
    assert set(credit) == {"company", "bankruptcy_risk", "risk_suite", "market"}
    assert "id" not in credit["company"], "a uuid would seed the number pool with noise"
    valuation = ra.scope(CONTEXT, ra.SPECIALISTS[2])
    assert valuation is None, "no valuation or scenario was computed"


def test_template_sections_pass_the_curator_untouched():
    """The no-key path must not trip its own grounding check."""
    for specialist in ra.SPECIALISTS:
        slice_ = ra.scope(CONTEXT, specialist)
        if slice_ is None:
            continue
        headline, body = ra.TEMPLATES[specialist.key](slice_)
        _, removed, _ = ra.curate_text(body, ra.context_numbers(slice_), 0.01)
        assert removed == [], specialist.key


# --- Disagreements -----------------------------------------------------------------------


def test_every_disagreement_rule_fires_on_a_context_built_to_trip_it():
    kinds = {d["kind"] for d in ra.find_disagreements(CONTEXT)}
    assert kinds == {
        "accounting_vs_market",
        "distress_vs_direction",
        "merton_solved_vs_naive",
        "beneish_thresholds",
        "altman_variant",
    }


def test_an_agreeing_context_reports_no_disagreements():
    agreeing = {
        "bankruptcy_risk": {"zone": "SAFE", "model": "Z_DOUBLE_PRIME"},
        "risk_suite": {"consensus_verdict": "LOW_RISK", "variant_scores": {}},
        "earnings_quality": {"f_score_band": "STRONG"},
        "market": {"market_view": "CONFIRMS"},
    }
    assert ra.find_disagreements(agreeing) == []


def test_mixed_signal_is_reported_as_a_disagreement():
    ctx = {
        "bankruptcy_risk": {"zone": "SAFE"},
        "risk_suite": {"consensus_verdict": "MIXED_SIGNAL", "ohlson": {"probability": 0.8}},
    }
    assert [d["kind"] for d in ra.find_disagreements(ctx)] == ["altman_vs_ohlson"]


# --- The pipeline ------------------------------------------------------------------------


def test_without_a_key_every_node_falls_back_and_says_why(settings):
    result = ra.run_pipeline(CONTEXT, settings)
    nodes = {t["node"]: t for t in result["trace"]}
    assert list(nodes) == [
        "grounding",
        "credit_analyst",
        "forensic_accountant",
        "valuation_analyst",
        "market_analyst",
        "curator",
        "disagreements",
        "editor",
    ]
    assert nodes["valuation_analyst"]["status"] == "skipped"
    assert nodes["credit_analyst"]["detail"] == "no ANTHROPIC_API_KEY configured"
    assert result["generated_by"] == "template_fallback"
    assert result["curator_report"]["sentences_removed"] == 0
    assert result["memo"]["executive_summary"].startswith("The models disagree in 5 places.")


def by_role(analyst_body: str):
    """Answer analyst calls with analyst JSON and the editor call with editor JSON."""
    editor = {"title": "t", "executive_summary": "Z scores 3.9203.", "recommendation": "Next."}

    def respond(kwargs):
        if "edit a credit research memo" in kwargs["system"]:
            return reply(json.dumps(editor))
        return reply(json.dumps({"headline": "Consensus LOW_RISK", "body": analyst_body}))

    return respond


def test_an_invented_figure_from_the_model_is_cut_before_the_editor_sees_it(fake_model, keyed):
    fake_model.reply = by_role("Z scores 3.9203. Revenue grew 47%.")
    result = ra.run_pipeline(CONTEXT, keyed)
    removed = result["curator_report"]["removed"]
    assert {
        "sentence": "Revenue grew 47%.",
        "ungrounded": ["47%"],
        "section": "credit_analyst",
    } in removed
    assert all("47%" not in s["text"] for s in result["sections"])
    assert result["generated_by"] == "llm"


def test_the_editor_never_sees_the_raw_context(fake_model, keyed):
    fake_model.reply = by_role("Z scores 3.9203.")
    ra.run_pipeline(CONTEXT, keyed)
    editor_call = next(c for c in fake_model.calls if "edit a credit research memo" in c["system"])
    material = json.loads(editor_call["messages"][0]["content"])
    assert set(material) == {"company", "sections", "disagreements"}
    assert "risk_suite" not in editor_call["messages"][0]["content"]


def test_a_malformed_model_answer_falls_back_instead_of_crashing(fake_model, keyed):
    fake_model.reply = reply(json.dumps({"unexpected": "shape"}))
    result = ra.run_pipeline(CONTEXT, keyed)
    nodes = {t["node"]: t for t in result["trace"]}
    assert nodes["editor"]["status"] == "fallback"
    assert nodes["credit_analyst"]["detail"] == "model output was missing required fields"


# --- Over HTTP -----------------------------------------------------------------------------


def test_a_memo_needs_the_core_stages_first(client, load_company, caterpillar):
    company_id = load_company(caterpillar)
    assert client.post(f"/companies/{company_id}/research-memo").status_code == 409
    assert client.get(f"/companies/{company_id}/research-memo").status_code == 404


def test_caterpillar_memo_surfaces_the_variant_disagreement(client, load_company, caterpillar):
    """Caterpillar is SAFE under the 1968 model it belongs to and GREY under Z'."""
    company_id = load_company(caterpillar)
    client.post(f"/companies/{company_id}/run-full-analysis")
    memo = client.post(f"/companies/{company_id}/research-memo").json()
    assert memo["generated_by"] == "template_fallback"
    titles = [d["title"] for d in memo["memo"]["disagreements"]]
    assert "Z_PRIME would read a different zone" in titles
    assert client.get(f"/companies/{company_id}/research-memo").json()["id"] == memo["id"]
