"""One place that talks to the language model, for every narrating stage.

Two rules hold for every call, and both live here so no caller can forget them:

  JSON comes from structured outputs (output_config.format), never from an
  assistant prefill, which current models reject with a 400.

  Every failure degrades to (None, reason). The caller then uses its
  deterministic template, so an outage can change the prose but never a number.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import anthropic

from app.config import Settings

logger = logging.getLogger(__name__)


def structured_call(
    settings: Settings,
    *,
    system: str,
    user_content: str,
    schema: dict[str, Any],
    max_tokens: int | None = None,
) -> tuple[dict[str, Any] | None, str]:
    """Ask the model for JSON matching schema. Returns (parsed, "") or (None, reason)."""
    if not settings.anthropic_api_key:
        return None, "no ANTHROPIC_API_KEY configured"
    if not settings.anthropic_model:
        return None, "no ANTHROPIC_MODEL configured"

    client = anthropic.Anthropic(
        api_key=settings.anthropic_api_key, timeout=settings.llm_timeout_seconds
    )
    request: dict[str, Any] = {
        "model": settings.anthropic_model,
        "max_tokens": max_tokens or settings.llm_max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user_content}],
        "output_config": {
            "format": {"type": "json_schema", "schema": schema},
            "effort": settings.llm_effort,
        },
    }
    try:
        response = client.messages.create(**request)
    except anthropic.RateLimitError as exc:
        return None, f"rate limited: {exc.message}"
    except anthropic.APIStatusError as exc:
        return None, f"API error {exc.status_code}: {exc.message}"
    except anthropic.APIConnectionError as exc:
        return None, f"connection error: {exc}"

    return _parse(response)


def _parse(response: Any) -> tuple[dict[str, Any] | None, str]:
    if response.stop_reason == "refusal":
        category = getattr(response.stop_details, "category", None)
        return None, f"model declined the request (category: {category})"
    if response.stop_reason == "max_tokens":
        return None, "response truncated at max_tokens"
    text = next((b.text for b in response.content if b.type == "text"), None)
    if text is None:
        return None, "response contained no text block"
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, f"unparseable model output: {exc}"
    if not isinstance(parsed, dict):
        return None, "model returned JSON that is not an object"
    return parsed, ""
