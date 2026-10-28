"""Multi-agent research memo: grounding, specialist analysts, curator, editor.

Inspired by guy-hartstein/company-research-agent, whose pipeline runs grounding,
then parallel researchers, then a curator that drops what fails a threshold, then
an editor. The shape carries over; the inputs do not. That project searches the
web. This one reads only figures FinSight already computed and stored, because
an agent that can fetch new numbers is an agent that can invent them.

    grounding    split the stored context into one scoped slice per specialist
    analysts     four specialists, in parallel, each seeing only its own slice
    curator      every number in every sentence must exist in that analyst's
                 slice, or the sentence is removed
    editor       compiles the curated sections; sees no raw context at all,
                 and its own output is curated against the sections it was given
    disagreements found deterministically, never by the model

With no API key every node runs its template, and the trace says so.
"""

from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from app.config import Settings
from app.services.llm import structured_call

INSPIRED_BY = "guy-hartstein/company-research-agent"


@dataclass(frozen=True)
class Specialist:
    key: str
    title: str
    sections: tuple[str, ...]
    brief: str


SPECIALISTS: tuple[Specialist, ...] = (
    Specialist(
        "credit_analyst",
        "Credit risk",
        ("bankruptcy_risk", "risk_suite", "market"),
        "Assess default risk: the Altman variant, Ohlson's probability, the consensus "
        "verdict, and whether the Merton market view confirms or contradicts it.",
    ),
    Specialist(
        "forensic_accountant",
        "Earnings quality",
        ("earnings_quality", "dupont"),
        "Assess whether the reported numbers can be trusted: Piotroski's tests, Beneish's "
        "indices against both thresholds, and what the DuPont decomposition shows.",
    ),
    Specialist(
        "valuation_analyst",
        "Valuation",
        ("valuation", "scenario"),
        "Assess the DCF: the implied value, how much of it is terminal value, the beta "
        "used, and how wide the Monte Carlo distribution is.",
    ),
    Specialist(
        "market_analyst",
        "Market and peers",
        ("market", "peer_benchmark", "trend"),
        "Assess market behaviour and standing: beta, volatility, drawdown and VaR, the "
        "peer percentiles with their ranks, and the largest year-on-year moves.",
    ),
)

ANALYST_SYSTEM = """You are one specialist on a credit research team. You will receive
ONE slice of a company's computed analysis. It is everything you know.

Rules:
- Quote every figure exactly as it appears in your slice, in the slice's units.
  Do not convert units, rescale, round to a new figure, or compute anything new.
  A sentence carrying a number that is not in your slice will be deleted.
- Where the slice marks something PARTIAL, withheld, or refused, say so plainly.
- No investment advice, price targets, or buy/sell/hold language.
- Two to five sentences in the body. Plain language for a credit committee."""

ANALYST_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "headline": {"type": "string"},
        "body": {"type": "string"},
    },
    "required": ["headline", "body"],
    "additionalProperties": False,
}

EDITOR_SYSTEM = """You edit a credit research memo. You receive curated sections from
four specialists and a list of places where the models disagree. You have no other
information.

Rules:
- Use only figures that appear in the sections or disagreements, exactly as written.
- Lead the executive summary with the disagreements if there are any: they are the
  most useful finding, not a footnote.
- The recommendation is one concrete next analytical step, never a trade."""

EDITOR_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "executive_summary": {"type": "string"},
        "recommendation": {"type": "string"},
    },
    "required": ["title", "executive_summary", "recommendation"],
    "additionalProperties": False,
}


def _has_fields(parsed: dict[str, Any], schema: dict[str, Any]) -> bool:
    """Structured outputs should guarantee the schema; a node still never trusts it."""
    return all(isinstance(parsed.get(k), str) for k in schema["required"])


@dataclass
class NodeTrace:
    node: str
    status: str
    source: str
    duration_ms: float
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "node": self.node,
            "status": self.status,
            "source": self.source,
            "duration_ms": round(self.duration_ms, 2),
            "detail": self.detail,
        }


@dataclass
class Draft:
    specialist: Specialist
    headline: str
    body: str
    source: str
    reason: str = ""
    duration_ms: float = 0.0


@dataclass
class CuratedSection:
    key: str
    title: str
    headline: str
    text: str
    removed: list[dict[str, Any]] = field(default_factory=list)
    numbers_checked: int = 0
    source: str = "template"


# --- Curator: numeric grounding -------------------------------------------------

# A number not preceded by a letter, digit, underscore or dot, so "x1", "FY2024"
# and the "1968" in "Z_1968" are identifiers rather than figures.
_NUMBER = re.compile(r"(?<![\w.])([-−]?)(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?(%?)")
_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z(\"'])")
# Bare small integers are counts ("nine tests", "4 of 7"), not figures.
_COUNT_LIMIT = 12


def numbers_in(text: str) -> list[tuple[str, float, int, bool]]:
    """Every figure in text as (raw, value, decimals, is_percent)."""
    found = []
    for match in _NUMBER.finditer(text):
        sign, whole, decimals, percent = match.groups()
        value = float(whole.replace(",", "") + (decimals or ""))
        found.append(
            (
                match.group(0),
                -value if sign else value,
                len(decimals) - 1 if decimals else 0,
                bool(percent),
            )
        )
    return found


def context_numbers(node: Any) -> list[float]:
    """Every figure anywhere in a context slice: numeric leaves, and numbers in text."""
    if isinstance(node, bool) or node is None:
        return []
    if isinstance(node, int | float):
        return [float(node)]
    if isinstance(node, str):
        return [value for _, value, _, _ in numbers_in(node)]
    if isinstance(node, dict):
        return [n for k, v in node.items() for n in context_numbers(k) + context_numbers(v)]
    if isinstance(node, list | tuple):
        return [n for item in node for n in context_numbers(item)]
    return []


def is_grounded(
    value: float, decimals: int, percent: bool, pool: list[float], tolerance: float
) -> bool:
    """Within tolerance of a context figure, or of its percentage form, or its magnitude."""
    if not percent and decimals == 0 and value.is_integer() and abs(value) <= _COUNT_LIMIT:
        return True
    slack = 0.5 * 10 ** (-decimals)
    for v in pool:
        for candidate in (v, v * 100.0) if abs(v) <= 1 else (v,):
            for target in (candidate, -candidate):
                if abs(value - target) <= max(tolerance * abs(target), slack):
                    return True
    return False


def curate_text(text: str, pool: list[float], tolerance: float) -> tuple[str, list[dict], int]:
    """Drop every sentence carrying a figure the pool cannot account for."""
    kept, removed, checked = [], [], 0
    for sentence in _SENTENCE.split(text.strip()):
        figures = numbers_in(sentence)
        checked += len(figures)
        stray = [raw for raw, v, d, p in figures if not is_grounded(v, d, p, pool, tolerance)]
        if stray:
            removed.append({"sentence": sentence, "ungrounded": stray})
        elif sentence:
            kept.append(sentence)
    return " ".join(kept), removed, checked


# --- Grounding ------------------------------------------------------------------


def scope(context: dict[str, Any], specialist: Specialist) -> dict[str, Any] | None:
    """The one slice a specialist may see, or None if none of it was computed."""
    present = {k: context[k] for k in specialist.sections if context.get(k)}
    if not present:
        return None
    company = {k: v for k, v in context.get("company", {}).items() if k != "id"}
    return {"company": company, **present}


# --- Templates (no API key, or a failed call) -----------------------------------


def _pct(x: float | None, digits: int = 1) -> str:
    return "n/a" if x is None else f"{x * 100:.{digits}f}%"


def _credit_template(s: dict) -> tuple[str, str]:
    risk, suite, market = s.get("bankruptcy_risk", {}), s.get("risk_suite", {}), s.get("market", {})
    lines = []
    if risk.get("score") is not None:
        cut = risk.get("cutoffs") or {}
        lines.append(
            f"{risk['model']} scores {risk['score']} against a safe cutoff of "
            f"{cut.get('safe_above')} and a distress cutoff of {cut.get('distress_below')}, "
            f"placing the company in the {risk['zone']} zone."
        )
    ohlson = suite.get("ohlson") or {}
    if ohlson.get("probability") is not None:
        lines.append(f"Ohlson puts the probability of distress at {_pct(ohlson['probability'])}.")
    verdict = suite.get("consensus_verdict")
    if verdict:
        lines.append(f"The accounting consensus is {verdict}.")
    if market.get("merton_distance_to_default") is not None:
        lines.append(
            f"Merton's distance-to-default is {market['merton_distance_to_default']}, a "
            f"market-implied default probability of {_pct(market['merton_probability_of_default'], 2)}; "
            f"the market view {market['market_view']} the accounting models."
        )
    return f"Consensus {verdict or 'not computed'}", " ".join(lines)


def _forensic_template(s: dict) -> tuple[str, str]:
    q, dupont = s.get("earnings_quality", {}), s.get("dupont", {})
    lines = []
    if q.get("piotroski_f_score") is not None:
        failed = [
            k for k, t in (q.get("f_score_components") or {}).items() if t.get("status") == "FAIL"
        ]
        band = q.get("f_score_band") or "no band, because not every test could be evaluated"
        lines.append(f"Piotroski F-Score is {q['piotroski_f_score']} ({band}).")
        if failed:
            lines.append(f"Failed tests: {', '.join(failed)}.")
    if q.get("beneish_m_score") is not None:
        lines.append(
            f"Beneish M-Score is {q['beneish_m_score']}; manipulation flag under Beneish's own "
            f"cutoff: {q.get('manipulation_flag')}, under the stricter one: {q.get('strict_manipulation_flag')}."
        )
    elif q:
        lines.append(
            "The Beneish M-Score was withheld because not all eight indices could be formed."
        )
    five = dupont.get("five_step")
    if five:
        lines.append(f"Five-step DuPont reconciles to an ROE of {five['product_roe_pct']}%.")
    return f"F-Score {q.get('piotroski_f_score', 'n/a')}", " ".join(lines)


def _valuation_template(s: dict) -> tuple[str, str]:
    v, sc = s.get("valuation", {}), s.get("scenario", {})
    lines = []
    if v.get("enterprise_value") is not None:
        lines.append(
            f"The DCF gives an enterprise value of {v['enterprise_value']:,.0f} at a WACC of "
            f"{_pct(v.get('wacc'), 2)}, with {_pct(v.get('terminal_value_share_of_ev'))} of it in the terminal value."
        )
        if v.get("implied_share_price") is not None:
            lines.append(f"Implied share price is {v['implied_share_price']}.")
        if v.get("upside_downside_pct") is not None:
            lines.append(f"That is {v['upside_downside_pct']}% against the year-end price.")
    elif v:
        lines.append("No valuation was produced; the DCF refused its inputs.")
    equity = (sc.get("summary") or {}).get("dcf_equity_value")
    if equity:
        lines.append(
            f"Across {sc['n_trials']} Monte Carlo trials, equity value runs from {equity['p5']:,.0f} "
            f"at p5 to {equity['p95']:,.0f} at p95."
        )
    if v.get("enterprise_value") is None:
        headline = "No valuation produced"
    elif v.get("upside_downside_pct") is not None:
        headline = f"Implied value {v['upside_downside_pct']}% against the year-end price"
    else:
        headline = f"Enterprise value {v['enterprise_value']:,.0f}"
    return headline, " ".join(lines)


def _market_template(s: dict) -> tuple[str, str]:
    m, peers = s.get("market", {}), s.get("peer_benchmark", {})
    metrics = m.get("risk_metrics") or {}
    lines = []
    if m.get("beta") is not None:
        lines.append(f"Regression beta is {m['beta']} (Blume-adjusted {m['adjusted_beta']}).")
    if metrics.get("annualised_volatility") is not None:
        lines.append(
            f"Annualised volatility is {_pct(metrics['annualised_volatility'])}, the worst drawdown "
            f"{_pct(metrics['max_drawdown'])}, and one-month historical VaR {_pct(metrics['historical_var'])}."
        )
    if peers.get("industry_percentile") is not None:
        lines.append(
            f"Against {peers['peer_count']} peers the weighted percentile is {peers['industry_percentile']}."
        )
    if m.get("adjusted_beta") is not None:
        headline = (
            f"Beta {m['adjusted_beta']}, volatility {_pct(metrics.get('annualised_volatility'))}"
        )
    elif metrics.get("annualised_volatility") is not None:
        headline = (
            f"Volatility {_pct(metrics['annualised_volatility'])}; no comparable benchmark for beta"
        )
    else:
        headline = "No market statistics"
    return headline, " ".join(lines)


TEMPLATES = {
    "credit_analyst": _credit_template,
    "forensic_accountant": _forensic_template,
    "valuation_analyst": _valuation_template,
    "market_analyst": _market_template,
}


# --- Analysts -------------------------------------------------------------------


def run_analyst(specialist: Specialist, slice_: dict | None, settings: Settings) -> Draft:
    start = time.perf_counter()
    if slice_ is None:
        return Draft(
            specialist, "", "", "skipped", "none of this specialist's inputs were computed"
        )
    parsed, reason = structured_call(
        settings,
        system=f"{ANALYST_SYSTEM}\n\nYour brief: {specialist.brief}",
        user_content=json.dumps(slice_, indent=2, default=str),
        schema=ANALYST_SCHEMA,
    )
    if parsed is None or not _has_fields(parsed, ANALYST_SCHEMA):
        headline, body = TEMPLATES[specialist.key](slice_)
        reason = reason or "model output was missing required fields"
        return Draft(
            specialist, headline, body, "template", reason, (time.perf_counter() - start) * 1000
        )
    return Draft(
        specialist,
        parsed["headline"],
        parsed["body"],
        "llm",
        "",
        (time.perf_counter() - start) * 1000,
    )


def run_analysts(slices: dict[str, dict | None], settings: Settings) -> list[Draft]:
    """All four specialists in parallel, as the research agent runs its researchers."""
    with ThreadPoolExecutor(max_workers=settings.research_parallel_workers) as pool:
        futures = [pool.submit(run_analyst, s, slices[s.key], settings) for s in SPECIALISTS]
        return [f.result() for f in futures]


def curate(draft: Draft, slice_: dict | None, tolerance: float) -> CuratedSection | None:
    if draft.source == "skipped":
        return None
    pool = context_numbers(slice_)
    text, removed, checked = curate_text(draft.body, pool, tolerance)
    headline, headline_removed, _ = curate_text(draft.headline, pool, tolerance)
    return CuratedSection(
        key=draft.specialist.key,
        title=draft.specialist.title,
        headline=headline or draft.specialist.title,
        text=text,
        removed=removed + headline_removed,
        numbers_checked=checked,
        source=draft.source,
    )


# --- Disagreements: found by code, not by the model ------------------------------


def find_disagreements(context: dict[str, Any]) -> list[dict[str, str]]:
    """Every place two models in this analysis read the same company differently."""
    found: list[dict[str, str]] = []
    risk = context.get("bankruptcy_risk") or {}
    suite = context.get("risk_suite") or {}
    quality = context.get("earnings_quality") or {}
    market = context.get("market") or {}
    verdict = suite.get("consensus_verdict")
    probability = (suite.get("ohlson") or {}).get("probability")

    if verdict == "MIXED_SIGNAL":
        found.append(
            _disagreement(
                "altman_vs_ohlson",
                "Altman and Ohlson disagree",
                f"Altman reads the {risk.get('zone')} zone; Ohlson puts distress at {_pct(probability)}.",
            )
        )
    if market.get("market_view") in {"CONTRADICTS", "PARTIAL"}:
        found.append(
            _disagreement(
                "accounting_vs_market",
                "The market does not fully agree with the accounting models",
                f"Accounting consensus {verdict}; Merton default probability "
                f"{_pct(market.get('merton_probability_of_default'), 2)}.",
            )
        )
    band = quality.get("f_score_band")
    if (verdict, band) in {("LOW_RISK", "WEAK"), ("HIGH_RISK", "STRONG")}:
        found.append(
            _disagreement(
                "distress_vs_direction",
                "Safe and deteriorating" if verdict == "LOW_RISK" else "Distressed but improving",
                f"The distress models say {verdict}; Piotroski scores {quality.get('piotroski_f_score')} "
                f"({band}). They answer different questions: will it fail, versus is it getting better.",
            )
        )
    solved, naive = (
        market.get("merton_distance_to_default"),
        market.get("naive_distance_to_default"),
    )
    if solved is not None and naive is not None and abs(solved - naive) >= 1.0:
        found.append(
            _disagreement(
                "merton_solved_vs_naive",
                "The two Merton estimates diverge",
                f"Solved distance-to-default {solved} against the naive closed form's {naive}. The naive "
                "model's drift is the trailing stock return, so a rally inflates it.",
            )
        )
    if (
        quality.get("manipulation_flag") is False
        and quality.get("strict_manipulation_flag") is True
    ):
        found.append(
            _disagreement(
                "beneish_thresholds",
                "Clean under one Beneish cutoff, flagged under the other",
                f"M-Score {quality.get('beneish_m_score')} sits between the stricter and the original cutoff.",
            )
        )
    for name, variant in (suite.get("variant_scores") or {}).items():
        if not variant.get("applicable") and variant.get("zone") not in {
            risk.get("zone"),
            "NOT_APPLICABLE",
        }:
            found.append(
                _disagreement(
                    "altman_variant",
                    f"{name} would read a different zone",
                    f"The applicable {risk.get('model')} reads {risk.get('zone')}; {name} reads "
                    f"{variant.get('zone')} at {variant.get('score')} on the same balance sheet.",
                )
            )
    return found


def _disagreement(kind: str, title: str, detail: str) -> dict[str, str]:
    return {"kind": kind, "title": title, "detail": detail}


# --- Editor ---------------------------------------------------------------------


def _editor_template(
    context: dict, sections: list[CuratedSection], disagreements: list[dict]
) -> dict:
    company = context.get("company", {})
    count = len(disagreements)
    lead = (
        f"The models disagree in {count} {'place' if count == 1 else 'places'}. "
        f"First: {disagreements[0]['title']}."
        if disagreements
        else "The models in this analysis agree with each other."
    )
    summary = " ".join([lead, *(f"{s.title} - {s.headline}." for s in sections)])
    if disagreements:
        recommendation = (
            f"Resolve this before relying on any single score: {disagreements[0]['detail']}"
        )
    elif (context.get("risk_suite") or {}).get("consensus_verdict") == "HIGH_RISK":
        recommendation = (
            "Treat as a workout candidate and review debt maturities and covenant headroom next."
        )
    else:
        recommendation = (
            "Add another fiscal year so the trend and year-on-year models have more to work with."
        )
    return {
        "title": f"{company.get('name', 'Company')} - FY{company.get('fiscal_year')} research memo",
        "executive_summary": summary,
        "recommendation": recommendation,
    }


def edit(context, sections, disagreements, settings) -> tuple[dict, NodeTrace]:
    """Compile the memo. The model sees only curated sections and disagreements."""
    start = time.perf_counter()
    material = {
        "company": {k: v for k, v in context.get("company", {}).items() if k != "id"},
        "sections": [{"title": s.title, "headline": s.headline, "text": s.text} for s in sections],
        "disagreements": disagreements,
    }
    parsed, reason = structured_call(
        settings,
        system=EDITOR_SYSTEM,
        user_content=json.dumps(material, indent=2),
        schema=EDITOR_SCHEMA,
    )
    if parsed is None or not _has_fields(parsed, EDITOR_SCHEMA):
        memo = _editor_template(context, sections, disagreements)
        reason = reason or "model output was missing required fields"
        return memo, NodeTrace(
            "editor", "fallback", "template", (time.perf_counter() - start) * 1000, reason
        )

    pool = context_numbers(material)
    removed = 0
    for field_name in ("executive_summary", "recommendation"):
        parsed[field_name], dropped, _ = curate_text(
            parsed[field_name], pool, settings.research_number_tolerance
        )
        removed += len(dropped)
    detail = f"curated its own output: {removed} sentence(s) removed"
    return parsed, NodeTrace("editor", "ok", "llm", (time.perf_counter() - start) * 1000, detail)


# --- The pipeline ---------------------------------------------------------------


def run_pipeline(context: dict[str, Any], settings: Settings) -> dict[str, Any]:
    """grounding -> analysts (parallel) -> curator -> disagreements -> editor."""
    trace: list[NodeTrace] = []

    start = time.perf_counter()
    slices = {s.key: scope(context, s) for s in SPECIALISTS}
    ready = sum(1 for v in slices.values() if v)
    trace.append(
        NodeTrace(
            "grounding",
            "ok",
            "deterministic",
            (time.perf_counter() - start) * 1000,
            f"{ready} of {len(SPECIALISTS)} specialists have computed inputs",
        )
    )

    drafts = run_analysts(slices, settings)
    for d in drafts:
        status = {"llm": "ok", "template": "fallback", "skipped": "skipped"}[d.source]
        trace.append(NodeTrace(d.specialist.key, status, d.source, d.duration_ms, d.reason))

    start = time.perf_counter()
    curated = [
        c
        for d in drafts
        if (c := curate(d, slices[d.specialist.key], settings.research_number_tolerance))
    ]
    removed = sum(len(c.removed) for c in curated)
    checked = sum(c.numbers_checked for c in curated)
    trace.append(
        NodeTrace(
            "curator",
            "ok",
            "deterministic",
            (time.perf_counter() - start) * 1000,
            f"{checked} figures checked, {removed} sentence(s) removed",
        )
    )

    start = time.perf_counter()
    disagreements = find_disagreements(context)
    trace.append(
        NodeTrace(
            "disagreements",
            "ok",
            "deterministic",
            (time.perf_counter() - start) * 1000,
            f"{len(disagreements)} found",
        )
    )

    memo, editor_trace = edit(context, curated, disagreements, settings)
    trace.append(editor_trace)

    sources = {n.source for n in trace if n.source in {"llm", "template"}}
    return {
        "memo": {**memo, "disagreements": disagreements},
        "sections": [c.__dict__ for c in curated],
        "trace": [n.as_dict() for n in trace],
        "curator_report": {
            "figures_checked": checked,
            "sentences_removed": removed,
            "tolerance": settings.research_number_tolerance,
            "rule": (
                "A sentence survives only if every figure in it matches a figure in that "
                "analyst's own slice of the computed context - within the tolerance or the "
                "sentence's own rounding, as a value, its percentage form or its magnitude. "
                f"Bare integers up to {_COUNT_LIMIT} are treated as counts."
            ),
            "removed": [{"section": c.key, **r} for c in curated for r in c.removed],
        },
        "generated_by": "llm"
        if sources == {"llm"}
        else "template_fallback"
        if sources == {"template"}
        else "mixed",
        "inspired_by": INSPIRED_BY,
    }
