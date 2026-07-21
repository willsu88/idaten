"""LLM token/cost accounting, recorded at the `LLMClient` seam.

Every provider call funnels through the three client methods, so instrumenting
here captures everything in one place, attributed to `user_id` + `call_site`
(the feature that made the call). Tokens are exact; cost is derived from the
price map below (edit `PRICES` when provider pricing changes - one place).

Token normalization is uniform so the cost formula never double-counts:
`input_tokens` is NON-cached input only, `cache_read_tokens` and
`cache_creation_tokens` are separate. Anthropic already reports them split;
the OpenAI boundary subtracts cached tokens out of `prompt_tokens` before
calling `record` (see openai_client).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .db import session
from .models import LlmUsage

log = logging.getLogger(__name__)


@dataclass
class Usage:
    input_tokens: int = 0          # non-cached input
    output_tokens: int = 0
    cache_read_tokens: int = 0     # cache hits (billed at a discount)
    cache_creation_tokens: int = 0  # cache writes (Anthropic only; billed at a premium)


# USD per 1,000,000 tokens. Rates are approximate and EDITABLE here - cost is an
# observability estimate; the token counts stored alongside are exact. Matched
# by exact model id first, then longest key prefix, then `_DEFAULT`.
PRICES: dict[str, dict[str, float]] = {
    # Anthropic (Opus/Sonnet/Haiku class): cache read ~= 0.1x input, write ~= 1.25x.
    "claude-opus-4-8": {"input": 15.0, "output": 75.0, "cache_read": 1.5, "cache_write": 18.75},
    "claude-sonnet-5": {"input": 3.0, "output": 15.0, "cache_read": 0.3, "cache_write": 3.75},
    "claude-haiku-4-5": {"input": 1.0, "output": 5.0, "cache_read": 0.1, "cache_write": 1.25},
    # OpenAI gpt-5.x - Standard tier, short-context rates (input / cached-input /
    # cache-write / output per 1M). "-" in the price sheet -> 0.0 (no cache-write
    # charge, or caching not offered on the -pro tiers).
    "gpt-5.6-sol": {"input": 5.0, "output": 30.0, "cache_read": 0.5, "cache_write": 6.25},
    "gpt-5.6-terra": {"input": 2.5, "output": 15.0, "cache_read": 0.25, "cache_write": 3.125},
    "gpt-5.6-luna": {"input": 1.0, "output": 6.0, "cache_read": 0.1, "cache_write": 1.25},
    "gpt-5.5-pro": {"input": 30.0, "output": 180.0, "cache_read": 30.0, "cache_write": 0.0},
    "gpt-5.5": {"input": 5.0, "output": 30.0, "cache_read": 0.5, "cache_write": 0.0},
    "gpt-5.4-mini": {"input": 0.75, "output": 4.5, "cache_read": 0.075, "cache_write": 0.0},
    "gpt-5.4-nano": {"input": 0.2, "output": 1.25, "cache_read": 0.02, "cache_write": 0.0},
    "gpt-5.4-pro": {"input": 30.0, "output": 180.0, "cache_read": 30.0, "cache_write": 0.0},
    "gpt-5.4": {"input": 2.5, "output": 15.0, "cache_read": 0.25, "cache_write": 0.0},
    "_DEFAULT": {"input": 5.0, "output": 15.0, "cache_read": 0.5, "cache_write": 6.25},
}


def _rates(model: str) -> dict[str, float]:
    if model in PRICES:
        return PRICES[model]
    best = ""
    for key in PRICES:
        if key != "_DEFAULT" and model.startswith(key) and len(key) > len(best):
            best = key
    return PRICES[best] if best else PRICES["_DEFAULT"]


def cost_usd(model: str, u: Usage) -> float:
    r = _rates(model)
    total = (
        u.input_tokens * r["input"]
        + u.output_tokens * r["output"]
        + u.cache_read_tokens * r["cache_read"]
        + u.cache_creation_tokens * r["cache_write"]
    )
    return round(total / 1_000_000, 6)


def record(provider: str, model: str, u: Usage, user_id: int | None, call_site: str | None) -> None:
    """Persist one usage row. Best-effort and self-contained: an accounting
    failure must never break the LLM call, and unattributed calls (no user_id,
    e.g. tests) are silently skipped."""
    if user_id is None:
        return
    try:
        db = session()
        try:
            db.add(LlmUsage(
                user_id=user_id,
                provider=provider,
                model=model,
                call_site=call_site or "unknown",
                input_tokens=u.input_tokens,
                output_tokens=u.output_tokens,
                cache_read_tokens=u.cache_read_tokens,
                cache_creation_tokens=u.cache_creation_tokens,
                cost_usd=cost_usd(model, u),
            ))
            db.commit()
        finally:
            db.close()
    except Exception:  # noqa: BLE001 - accounting is never allowed to break a chat/plan
        log.warning("failed to record LLM usage (%s/%s %s)", provider, model, call_site,
                    exc_info=True)
