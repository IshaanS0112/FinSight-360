"""Financial health narrative: structured context -> constrained LLM prose.

The ordering is the whole module.

1. ``build_structured_context`` assembles every figure the report can contain
   from work the deterministic engines already did - the ratio table, the Altman
   score and its per-component decomposition, the health composite, the benchmark
   deltas. Nothing in it is inferred by a language model.
2. ``generate_narrative`` hands that context to the model under a JSON-only
   contract: narrate the given numbers, do not recompute, do not contradict the
   zone.
   The JSON shape is enforced by structured outputs (services/llm.py), not by
   an assistant prefill, which current models reject.
3. ``_validate_narrative`` drops any cited ratio or component name that does not
   appear in the context, and counts the drops.
4. On any failure - no API key, timeout, unparseable output - ``_fallback_narrative``
   builds the same report from a template. Every number is identical; only the
   prose is missing.
5. ``answer_question`` extends the same contract to a follow-up question. It is
   handed nothing but the ``structured_context`` already stored for the report,
   and an answer that cites nothing in that context is converted into a refusal
   rather than returned. See ``QA_SYSTEM_PROMPT`` and ``_validate_answer``.

So the answer to "does your AI compute the bankruptcy risk?" is no. The Altman
coefficients in ``altman_zscore.py`` compute it. The model writes it up, and
because ``structured_context`` is stored beside the narrative and returned by the
API, that claim is checkable by diffing the two rather than taken on trust.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.config import Settings
from app.enums import NarrativeSource, Zone
from app.services.altman_zscore import (
    COMPONENT_DEFINITIONS,
    COMPONENT_MEANINGS,
    ZScoreResult,
)
from app.services.health_score import HealthScoreResult
from app.services.llm import structured_call
from app.services.ratio_engine import RatioResult

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a credit analyst writing a financial health assessment.

You will receive a structured context containing computed financial ratios, an
Altman bankruptcy-risk score with its per-component decomposition, and a weighted
health score. ALL of it has already been computed by deterministic code.

Your job is to interpret those numbers, not to recompute or second-guess them.

Rules:
- Cite specific figures from the context. Do not round beyond two decimals.
- In key_findings you may only reference ratio keys or Altman component keys that
  appear in the context. Do not invent, merge, or rename them.
- Do not contradict the reported zone or the health score.
- If the context marks the zone as borderline, say so explicitly.
- If the context lists omitted ratios or omitted Altman components, treat those as
  unknown. Never describe an omitted figure as zero, weak, or strong.
- If confidence is PARTIAL, say so explicitly and name what was missing.
- If the Altman zone is NOT_APPLICABLE, explain that no score was produced and why;
  do not estimate one.
- Do not invent market events, management commentary, dates, guidance, or any
  figure not present in the context.
- Write for a credit committee: plain language, no hedging filler, no marketing tone.

The response format is enforced by the API. Fill these fields:
{
  "executive_summary": "<4-6 sentences citing concrete computed figures>",
  "bankruptcy_risk_assessment": "<what the Altman score and its components imply>",
  "key_findings": [
    {"metric": "<exact ratio or component key from the context>",
     "observation": "<what the number shows>",
     "implication": "<so what, for a lender or investor>"}
  ],
  "data_limitations": "<what could not be computed and how that constrains the read>",
  "recommendation": "<one concrete analytical next step>"
}"""


def build_structured_context(
    *,
    company_id: str,
    company_name: str,
    industry: str | None,
    sector_class: str,
    fiscal_year: int | None,
    currency: str,
    units: str,
    data_source: str | None,
    ratios: RatioResult,
    risk: ZScoreResult,
    health: HealthScoreResult,
    # V2 sections. A section that was not computed is absent, so the model
    # cannot cite it and the Q&A endpoint refuses questions about it.
    dupont: dict[str, Any] | None = None,
    cash_conversion_cycle: dict[str, Any] | None = None,
    trend: dict[str, Any] | None = None,
    risk_suite: dict[str, Any] | None = None,
    earnings_quality: dict[str, Any] | None = None,
    peer_benchmark: dict[str, Any] | None = None,
    valuation: dict[str, Any] | None = None,
    scenario: dict[str, Any] | None = None,
    market: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Freeze every computed signal into the payload the model is allowed to use."""
    context: dict[str, Any] = {
        "company": {
            "id": company_id,
            "name": company_name,
            "industry": industry or "unspecified",
            "sector_class": sector_class,
            "fiscal_year": fiscal_year,
            "currency": currency,
            "units": units,
            "data_source": data_source or "unspecified",
        },
        "ratios": {
            "liquidity": ratios.liquidity,
            "profitability": ratios.profitability,
            "leverage": ratios.leverage,
            "efficiency": ratios.efficiency,
            "omitted": ratios.omitted,
            "confidence": ratios.confidence.value,
            "formulas": ratios.calculation_basis.get("formulas", {}),
        },
        "bankruptcy_risk": {
            "model": risk.model.value,
            "citation": risk.calculation_basis.get("citation"),
            "model_selection": risk.calculation_basis.get("model_selection"),
            "score": risk.score,
            "zone": risk.zone.value,
            "borderline": risk.borderline,
            "cutoffs": risk.calculation_basis.get("cutoffs"),
            "components": risk.components,
            "component_definitions": {k: COMPONENT_DEFINITIONS[k] for k in risk.components},
            "component_meanings": {k: COMPONENT_MEANINGS[k] for k in risk.components},
            "omitted_components": risk.omitted_components,
            "confidence": risk.confidence.value,
            "x4_equity_basis": risk.calculation_basis.get("x4_equity_basis"),
        },
        "health_score": {
            "overall_score": health.overall_score,
            "component_scores": health.component_scores,
            "peer_percentile": health.peer_percentile,
            "confidence": health.confidence.value,
            "weights_effective": health.calculation_basis.get("weights_effective"),
            "benchmark_provenance": health.calculation_basis.get("benchmark_provenance"),
            "benchmark_deltas": _benchmark_deltas(health),
        },
        "calculation_basis": {
            "ratios": ratios.calculation_basis,
            "bankruptcy_risk": risk.calculation_basis,
            "health_score": health.calculation_basis,
        },
    }

    for key, section in (
        ("dupont", dupont),
        ("cash_conversion_cycle", cash_conversion_cycle),
        ("trend", trend),
        ("risk_suite", risk_suite),
        ("earnings_quality", earnings_quality),
        ("peer_benchmark", peer_benchmark),
        ("valuation", valuation),
        ("scenario", scenario),
        ("market", market),
    ):
        if section:
            context[key] = section

    return context


def _benchmark_deltas(health: HealthScoreResult) -> dict[str, dict[str, float]]:
    """Flatten value-vs-benchmark for every ratio that was actually scored."""
    deltas: dict[str, dict[str, float]] = {}
    detail = health.calculation_basis.get("component_detail", {})
    for component in detail.values():
        for ratio_key, info in (component.get("ratios") or {}).items():
            if isinstance(info, dict) and info.get("status") == "SCORED":
                value, benchmark = float(info["value"]), float(info["benchmark"])
                deltas[ratio_key] = {
                    "value": value,
                    "benchmark": benchmark,
                    "delta": round(value - benchmark, 4),
                    "delta_pct_of_benchmark": (
                        round(100.0 * (value - benchmark) / abs(benchmark), 2)
                        if abs(benchmark) > 1e-9
                        else 0.0
                    ),
                    "benchmark_basis": info.get("benchmark_basis"),
                }
    return deltas


def _allowed_metric_keys(context: dict[str, Any]) -> set[str]:
    """Every metric name the narrative may cite.

    Derived from the context actually built, never a static list: a section the
    pipeline did not compute contributes no keys.
    """
    keys: set[str] = set()
    for bucket in ("liquidity", "profitability", "leverage", "efficiency"):
        keys.update(context["ratios"].get(bucket, {}))
    keys.update(context["bankruptcy_risk"].get("components", {}))

    suite = context.get("risk_suite") or {}
    keys.update((suite.get("ohlson") or {}).get("components", {}))
    if suite.get("ohlson", {}).get("o_score") is not None:
        keys.update({"ohlson_o_score", "ohlson_probability", "consensus_verdict"})

    quality = context.get("earnings_quality") or {}
    keys.update(quality.get("f_score_components") or {})
    keys.update(quality.get("m_score_components") or {})
    if quality.get("piotroski_f_score") is not None:
        keys.add("piotroski_f_score")
    if quality.get("beneish_m_score") is not None:
        keys.add("beneish_m_score")

    dupont = context.get("dupont") or {}
    for form in ("three_step", "five_step"):
        keys.update((dupont.get(form) or {}).get("terms", {}))

    cycle = context.get("cash_conversion_cycle") or {}
    keys.update(k for k in cycle if k in {"dio", "dso", "dpo", "ccc"})

    valuation = context.get("valuation") or {}
    keys.update(
        k
        for k in ("wacc", "enterprise_value", "equity_value", "implied_share_price")
        if valuation.get(k) is not None
    )
    if context.get("health_score", {}).get("overall_score") is not None:
        keys.add("health_score")
    market = context.get("market") or {}
    keys.update(
        k
        for k in (
            "merton_distance_to_default",
            "merton_probability_of_default",
            "beta",
            "adjusted_beta",
        )
        if market.get(k) is not None
    )
    return keys


def _fallback_narrative(context: dict[str, Any], reason: str) -> dict[str, Any]:
    """Template report from the same numbers, no model involved."""
    company = context["company"]
    risk = context["bankruptcy_risk"]
    health = context["health_score"]
    ratios = context["ratios"]

    if risk["zone"] == Zone.NOT_APPLICABLE.value:
        risk_sentence = f"No Altman score was produced. {risk.get('model_selection') or ''}".strip()
    else:
        borderline = (
            " The score sits within the borderline margin of a zone cutoff, so the "
            "classification is provisional."
            if risk["borderline"]
            else ""
        )
        risk_sentence = (
            f"{risk['model']} score is {risk['score']}, placing the company in the "
            f"{risk['zone']} zone (safe above {risk['cutoffs']['safe_above']}, distress "
            f"below {risk['cutoffs']['distress_below']}).{borderline}"
        )

    health_sentence = (
        f"The weighted health score is {health['overall_score']} out of 100 "
        f"(components: {_component_list(health['component_scores'])})."
        if health["overall_score"] is not None
        else "No weighted health score could be computed from the available ratios."
    )

    summary = (
        f"{company['name']} ({company['industry']}, FY{company['fiscal_year']}, figures in "
        f"{company['units'].lower()} {company['currency']}). "
        f"{len(_allowed_metric_keys(context))} computed measures are available. "
        f"{risk_sentence} {health_sentence}"
    )

    deltas = health.get("benchmark_deltas") or {}
    key_findings = [
        {
            "metric": key,
            "observation": (
                f"{key} = {info['value']} against a benchmark of {info['benchmark']} "
                f"({info['delta_pct_of_benchmark']:+.2f}% relative)."
            ),
            "implication": (
                "Ahead of benchmark."
                if info["delta_pct_of_benchmark"] >= 0
                else "Behind benchmark."
            ),
        }
        for key, info in list(deltas.items())[:5]
    ]
    for component, values in list(risk.get("components", {}).items())[:2]:
        key_findings.append(
            {
                "metric": component,
                "observation": (
                    f"{component} = {values['ratio']}, contributing {values['contribution']} "
                    f"to the {risk['model']} score."
                ),
                "implication": COMPONENT_MEANINGS.get(component, ""),
            }
        )

    omitted_ratios = [o["ratio"] for o in ratios.get("omitted", [])]
    omitted_components = [o["component"] for o in risk.get("omitted_components", [])]
    limitations = "All specified ratios and score components were computed."
    if omitted_ratios or omitted_components:
        limitations = (
            f"Ratios not computed: {omitted_ratios or 'none'}. Altman components omitted: "
            f"{omitted_components or 'none'}. Omitted figures are unknown, not zero, and the "
            "score is a partial sum where components are missing."
        )

    return {
        "executive_summary": summary,
        "bankruptcy_risk_assessment": risk_sentence,
        "key_findings": key_findings,
        "data_limitations": limitations,
        "recommendation": _fallback_recommendation(risk, health),
        "generated_by": NarrativeSource.TEMPLATE_FALLBACK.value,
        "fallback_reason": reason,
    }


def _component_list(scores: dict[str, float | None]) -> str:
    """Health component scores as prose: "liquidity 15.14, leverage not scored"."""
    return ", ".join(
        f"{name} {'not scored' if value is None else value}" for name, value in scores.items()
    )


def _fallback_recommendation(risk: dict[str, Any], health: dict[str, Any]) -> str:
    if risk["zone"] == Zone.NOT_APPLICABLE.value:
        return (
            "Score this issuer with a sector-appropriate model before drawing any "
            "solvency conclusion; the Altman family does not apply here."
        )
    if risk["confidence"] == "PARTIAL":
        return (
            "Source the missing line items and recompute before acting: the current "
            "score is a partial sum and is biased toward the cutoffs."
        )
    if risk["zone"] == Zone.DISTRESS.value:
        return (
            "Treat as a workout candidate: review debt maturities and covenant headroom "
            "next, since the components driving the score are balance-sheet, not earnings, "
            "in origin."
        )
    if risk["borderline"]:
        return (
            "Re-run with a peer-median benchmark set before committing; the zone "
            "classification flips on a small revision to any single component."
        )
    return (
        "Extend to a multi-year series next - a single fiscal year cannot distinguish a "
        "stable position from a deteriorating one."
    )


def _validate_narrative(raw: str, context: dict[str, Any]) -> dict[str, Any]:
    """Parse the model output and strip anything the context does not support."""
    text = raw.strip()
    if text.startswith("```"):
        # Defensive: the contract says no code fences, models sometimes add them.
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()

    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("Model returned JSON that is not an object")
    for key in (
        "executive_summary",
        "bankruptcy_risk_assessment",
        "key_findings",
        "recommendation",
    ):
        if key not in parsed:
            raise ValueError(f"Model response missing required key: {key}")

    allowed = _allowed_metric_keys(context)
    verified: list[dict[str, str]] = []
    dropped: list[Any] = []
    for item in parsed.get("key_findings") or []:
        if not isinstance(item, dict):
            dropped.append(item)
            continue
        metric = str(item.get("metric", "")).strip()
        if metric in allowed:
            verified.append(
                {
                    "metric": metric,
                    "observation": str(item.get("observation", "")),
                    "implication": str(item.get("implication", "")),
                }
            )
        else:
            dropped.append(item)

    if dropped:
        logger.warning(
            "Dropped %d finding(s) citing metrics absent from the structured context: %s",
            len(dropped),
            [d.get("metric") if isinstance(d, dict) else d for d in dropped],
        )

    return {
        "executive_summary": str(parsed["executive_summary"]),
        "bankruptcy_risk_assessment": str(parsed["bankruptcy_risk_assessment"]),
        "key_findings": verified,
        "data_limitations": str(parsed.get("data_limitations", "")),
        "recommendation": str(parsed["recommendation"]),
        "generated_by": NarrativeSource.LLM.value,
        "dropped_citations": len(dropped),
    }


NARRATIVE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "executive_summary": {"type": "string"},
        "bankruptcy_risk_assessment": {"type": "string"},
        "key_findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "metric": {"type": "string"},
                    "observation": {"type": "string"},
                    "implication": {"type": "string"},
                },
                "required": ["metric", "observation", "implication"],
                "additionalProperties": False,
            },
        },
        "data_limitations": {"type": "string"},
        "recommendation": {"type": "string"},
    },
    "required": [
        "executive_summary",
        "bankruptcy_risk_assessment",
        "key_findings",
        "data_limitations",
        "recommendation",
    ],
    "additionalProperties": False,
}


def generate_narrative(context: dict[str, Any], settings: Settings) -> dict[str, Any]:
    """Narrate the context via the LLM, or return the template fallback on any failure."""
    parsed, reason = structured_call(
        settings,
        system=SYSTEM_PROMPT,
        user_content=json.dumps(context, indent=2, default=str),
        schema=NARRATIVE_SCHEMA,
    )
    if parsed is None:
        logger.info("Narrative falling back to the template: %s", reason)
        return _fallback_narrative(context, reason)
    try:
        return _validate_narrative(json.dumps(parsed), context)
    except ValueError as exc:
        return _fallback_narrative(context, f"invalid model output: {exc}")


# ---------------------------------------------------------------------------
# Follow-up Q&A
# ---------------------------------------------------------------------------

QA_SYSTEM_PROMPT = """You answer follow-up questions about ONE company's financial
analysis, using ONLY the structured context supplied with the question.

The context contains every figure that was computed for this company. It is the
complete set of things you know. You have no other information about this
company, this industry, or anything else, and you must not behave as though you
do.

Rules, in order of importance:
1. If answering the question requires a number that is not in the context, you
   MUST refuse. Set "refused": true and say plainly which figure is missing and
   what would have to be computed to answer. Do not estimate it, do not derive
   it from a related figure, do not answer a nearby question instead.
2. Every figure you state must appear in the context. Do not round beyond two
   decimals and do not recompute anything.
3. List in "grounded_in" the exact metric or field names from the context that
   your answer rests on. An answer with an empty grounded_in list will be
   rejected.
4. Do not offer investment advice, price targets, or a recommendation to buy,
   sell or hold. You may explain what a computed figure means.
5. Where the context marks a figure PARTIAL, omitted, or subject to a documented
   limitation, say so as part of the answer rather than as a footnote.
6. Questions about the future, about management, about events, or about any
   company other than this one are refusals under rule 1.

The response format is enforced by the API. Fill these fields:
{
  "answer": "<the answer, or the explanation of why it cannot be answered>",
  "grounded_in": ["<exact field or metric name from the context>", ...],
  "refused": <true or false>
}"""

REFUSAL_PREFIX = "Not answerable from the computed analysis."


def _flatten_context_keys(context: Any, prefix: str = "") -> set[str]:
    """Every field name in the context, as both leaf name and dotted path.

    Both forms are accepted; the check exists to catch names in neither.
    """
    keys: set[str] = set()
    if isinstance(context, dict):
        for key, value in context.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            keys.add(str(key))
            keys.add(path)
            keys |= _flatten_context_keys(value, path)
    elif isinstance(context, list):
        for item in context:
            keys |= _flatten_context_keys(item, prefix)
    return keys


def _fallback_answer(context: dict[str, Any], question: str) -> dict[str, Any]:
    """Answer from the context by direct lookup, or refuse. No model involved.

    Runs when no API key is configured. Literal by design: it cannot paraphrase,
    so it cannot drift, and its refusal boundary matches the model path's.
    """
    allowed = _allowed_metric_keys(context)
    words = {
        token.strip(" ?.,:;()'\"").replace("-", "_").replace(" ", "_")
        for token in question.lower().split()
    }
    matched = sorted(key for key in allowed if key.lower() in words)

    if not matched:
        return {
            "answer": (
                f"{REFUSAL_PREFIX} No API key is configured, so this endpoint is running "
                "its deterministic fallback: it can report figures that were computed for "
                "this company when the question names them, and nothing else. The question "
                "did not name any computed metric. Available metric names: "
                f"{sorted(allowed)}."
            ),
            "grounded_in": [],
            "refused": True,
            "answered_by": NarrativeSource.TEMPLATE_FALLBACK.value,
        }

    values = _lookup_values(context, matched)
    stated = "; ".join(f"{key} = {value}" for key, value in values.items())
    return {
        "answer": (
            f"From the computed analysis for this company: {stated}. (No API key is "
            "configured, so this is a direct lookup rather than a written answer.)"
        ),
        "grounded_in": sorted(values),
        "refused": False,
        "answered_by": NarrativeSource.TEMPLATE_FALLBACK.value,
    }


def _lookup_values(context: Any, keys: list[str]) -> dict[str, Any]:
    """First value found for each requested key, anywhere in the context."""
    wanted = set(keys)
    found: dict[str, Any] = {}

    def walk(node: Any) -> None:
        if not wanted - set(found):
            return
        if isinstance(node, dict):
            for key, value in node.items():
                if key in wanted and key not in found and not isinstance(value, dict | list):
                    found[key] = value
                elif key in wanted and key not in found and isinstance(value, dict):
                    # A structured metric (an Altman component, an M-Score index)
                    # carries its own value under a conventional field name.
                    for candidate in ("value", "ratio", "score", "days", "days_outstanding"):
                        if candidate in value:
                            found[key] = value[candidate]
                            break
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(context)
    return {key: found[key] for key in keys if key in found}


def _validate_answer(raw: str, context: dict[str, Any]) -> dict[str, Any]:
    """Parse the model's answer and enforce that it rests on the context.

    A non-refusal whose citations all fail the check becomes a refusal: an
    answer grounded in nothing is indistinguishable from an invented one.
    """
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()

    parsed = json.loads(text)
    if not isinstance(parsed, dict) or "answer" not in parsed:
        raise ValueError("Model response is not an object with an 'answer' key")

    allowed = _flatten_context_keys(context)
    cited = [str(item) for item in (parsed.get("grounded_in") or [])]
    verified = [item for item in cited if item in allowed]
    dropped = [item for item in cited if item not in allowed]

    refused = bool(parsed.get("refused", False))
    if not refused and not verified:
        logger.warning(
            "Converting an ungrounded answer into a refusal; citations dropped: %s", dropped
        )
        return {
            "answer": (
                f"{REFUSAL_PREFIX} The model produced an answer that cites no field "
                "present in this company's computed context"
                + (f" (it cited {dropped}, none of which exist here)" if dropped else "")
                + ". An answer grounded in nothing is indistinguishable from an invented "
                "one, so it is withheld rather than shown."
            ),
            "grounded_in": [],
            "refused": True,
            "dropped_citations": len(dropped),
            "answered_by": NarrativeSource.LLM.value,
        }

    return {
        "answer": str(parsed["answer"]),
        "grounded_in": verified,
        "refused": refused,
        "dropped_citations": len(dropped),
        "answered_by": NarrativeSource.LLM.value,
    }


ANSWER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "grounded_in": {"type": "array", "items": {"type": "string"}},
        "refused": {"type": "boolean"},
    },
    "required": ["answer", "grounded_in", "refused"],
    "additionalProperties": False,
}


def answer_question(context: dict[str, Any], question: str, settings: Settings) -> dict[str, Any]:
    """Answer a follow-up using only the stored structured context.

    Cannot reach the database, recompute, or see any other company. A question
    needing an uncomputed figure comes back as an explicit refusal.
    """
    parsed, reason = structured_call(
        settings,
        system=QA_SYSTEM_PROMPT,
        user_content=json.dumps(
            {"question": question, "structured_context": context}, indent=2, default=str
        ),
        schema=ANSWER_SCHEMA,
    )
    if parsed is None:
        logger.info("Q&A falling back to direct lookup: %s", reason)
        return _fallback_answer(context, question)
    try:
        return _validate_answer(json.dumps(parsed), context)
    except ValueError:
        return _fallback_answer(context, question)
