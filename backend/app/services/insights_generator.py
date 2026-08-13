"""Financial health narrative: structured context -> constrained LLM prose.

The ordering is the whole module.

1. ``build_structured_context`` assembles every figure the report can contain
   from work the deterministic engines already did - the ratio table, the Altman
   score and its per-component decomposition, the health composite, the benchmark
   deltas. Nothing in it is inferred by a language model.
2. ``generate_narrative`` hands that context to the model under a JSON-only
   contract: narrate the given numbers, do not recompute, do not contradict the
   zone.
3. ``_validate_narrative`` drops any cited ratio or component name that does not
   appear in the context, and counts the drops.
4. On any failure - no API key, timeout, unparseable output - ``_fallback_narrative``
   builds the same report from a template. Every number is identical; only the
   prose is missing.

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

Respond with JSON only. No preamble, no code fences. Schema:
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
) -> dict[str, Any]:
    """Freeze every computed signal into the payload the model is allowed to use."""
    return {
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
            "component_definitions": {
                k: COMPONENT_DEFINITIONS[k] for k in risk.components
            },
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
    keys: set[str] = set()
    for bucket in ("liquidity", "profitability", "leverage", "efficiency"):
        keys.update(context["ratios"].get(bucket, {}))
    keys.update(context["bankruptcy_risk"].get("components", {}))
    return keys


def _fallback_narrative(context: dict[str, Any], reason: str) -> dict[str, Any]:
    """Template report from the same numbers, no model involved."""
    company = context["company"]
    risk = context["bankruptcy_risk"]
    health = context["health_score"]
    ratios = context["ratios"]

    if risk["zone"] == Zone.NOT_APPLICABLE.value:
        risk_sentence = (
            f"No Altman score was produced. {risk.get('model_selection') or ''}".strip()
        )
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
        f"(components: {health['component_scores']})."
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
                "Ahead of benchmark." if info["delta_pct_of_benchmark"] >= 0 else "Behind benchmark."
            ),
        }
        for key, info in list(deltas.items())[:5]
    ]
    for component, values in list(risk.get("components", {}).items())[:2]:
        key_findings.append({
            "metric": component,
            "observation": (
                f"{component} = {values['ratio']}, contributing {values['contribution']} "
                f"to the {risk['model']} score."
            ),
            "implication": COMPONENT_MEANINGS.get(component, ""),
        })

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
    for key in ("executive_summary", "bankruptcy_risk_assessment", "key_findings", "recommendation"):
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
            verified.append({
                "metric": metric,
                "observation": str(item.get("observation", "")),
                "implication": str(item.get("implication", "")),
            })
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


def generate_narrative(context: dict[str, Any], settings: Settings) -> dict[str, Any]:
    """Narrate the context via the LLM, or return the template fallback on any failure."""
    if not settings.anthropic_api_key:
        return _fallback_narrative(context, "no ANTHROPIC_API_KEY configured")

    try:
        from anthropic import Anthropic

        client = Anthropic(
            api_key=settings.anthropic_api_key, timeout=settings.llm_timeout_seconds
        )
        response = client.messages.create(
            model=settings.anthropic_model,
            max_tokens=settings.llm_max_tokens,
            system=SYSTEM_PROMPT,
            messages=[
                {"role": "user", "content": json.dumps(context, indent=2, default=str)},
                # Prefilling the opening brace makes the JSON-only contract
                # mechanical rather than a request the model may preamble past.
                {"role": "assistant", "content": "{"},
            ],
        )
        return _validate_narrative("{" + response.content[0].text, context)

    except json.JSONDecodeError as exc:
        logger.warning("LLM returned unparseable JSON, falling back: %s", exc)
        return _fallback_narrative(context, f"unparseable model output: {exc}")
    except Exception as exc:  # noqa: BLE001 - the report must degrade, never 500
        logger.warning("LLM narrative generation failed, falling back: %s", exc)
        return _fallback_narrative(context, f"{type(exc).__name__}: {exc}")
