"""Anthropic client — translates neutral (OpenAI-shaped) history/tools <-> the
Anthropic Messages API at this boundary. The agent loop never moves."""

from __future__ import annotations

import json
from typing import Any, Callable

from anthropic import Anthropic

from ..config import config
from ..usage import Usage, record
from . import Response, ToolCall

# Structured plans (7 days x multi-step workouts + rationales) can exceed 16k
# output tokens; a truncated response fails JSON parsing downstream.
MAX_TOKENS = 32000


def _to_anthropic_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Neutral history -> Anthropic messages.

    - assistant `tool_calls` -> `tool_use` content blocks
    - role "tool" messages -> `tool_result` blocks inside a user message
      (consecutive tool results are combined into one user turn, as the API
      requires all results for a parallel call in a single message)
    """
    out: list[dict[str, Any]] = []
    for m in messages:
        role = m["role"]
        if role == "tool":
            block = {
                "type": "tool_result",
                "tool_use_id": m["tool_call_id"],
                "content": m.get("content") or "",
            }
            if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list):
                out[-1]["content"].append(block)
            else:
                out.append({"role": "user", "content": [block]})
        elif role == "assistant" and m.get("tool_calls"):
            blocks: list[dict[str, Any]] = []
            if m.get("content"):
                blocks.append({"type": "text", "text": m["content"]})
            for tc in m["tool_calls"]:
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": tc["id"],
                        "name": tc["function"]["name"],
                        "input": json.loads(tc["function"]["arguments"] or "{}"),
                    }
                )
            out.append({"role": "assistant", "content": blocks})
        else:
            out.append({"role": role, "content": m.get("content") or ""})
    return out


def _to_anthropic_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "name": t["function"]["name"],
            "description": t["function"].get("description", ""),
            "input_schema": t["function"]["parameters"],
        }
        for t in tools
    ]


class AnthropicClient:
    def __init__(self, *, user_id: int | None = None, call_site: str | None = None) -> None:
        self._client = Anthropic(api_key=config.anthropic_api_key)
        self._model = config.anthropic_model
        self._user_id = user_id
        self._call_site = call_site

    def _record(self, message: Any) -> None:
        """Anthropic reports non-cached input, cache reads and cache writes as
        separate counters - map them straight across (no double-counting)."""
        u = getattr(message, "usage", None)
        if u is None:
            return
        record(
            "anthropic", self._model,
            Usage(
                input_tokens=getattr(u, "input_tokens", 0) or 0,
                output_tokens=getattr(u, "output_tokens", 0) or 0,
                cache_read_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
                cache_creation_tokens=getattr(u, "cache_creation_input_tokens", 0) or 0,
            ),
            self._user_id, self._call_site,
        )

    def _params(self, system: str, messages: list[dict], tools: list[dict]) -> dict:
        # Prompt caching: the system prompt is large (pace profile, Garmin plan,
        # readiness, HR zones as JSON) and byte-identical across the 3+ model
        # calls in one chat turn — and across turns within the cache TTL when the
        # daily inputs haven't changed. Marking it cached means calls after the
        # first read it at ~10% cost instead of full. The breakpoint sits on the
        # system block; since tools render *before* system, the tool schemas are
        # cached under the same prefix. Verify via usage.cache_read_input_tokens.
        system_field: Any = (
            [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
            if system else system
        )
        params: dict[str, Any] = {
            "model": self._model,
            "max_tokens": MAX_TOKENS,
            "system": system_field,
            "messages": _to_anthropic_messages(messages),
        }
        if tools:
            params["tools"] = _to_anthropic_tools(tools)
        return params

    @staticmethod
    def _parse(message: Any) -> Response:
        text_parts: list[str] = []
        calls: list[ToolCall] = []
        for block in message.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                calls.append(ToolCall(id=block.id, name=block.name, args=dict(block.input)))
        return Response(content="".join(text_parts) or None, tool_calls=calls)

    def complete(self, system, messages, tools) -> Response:
        resp = self._client.messages.create(**self._params(system, messages, tools))
        self._record(resp)
        return self._parse(resp)

    def stream(self, system, messages, tools, on_text: Callable[[str], None]) -> Response:
        with self._client.messages.stream(**self._params(system, messages, tools)) as stream:
            for text in stream.text_stream:
                on_text(text)
            final = stream.get_final_message()
            self._record(final)
            return self._parse(final)

    def complete_structured(self, system, messages, schema, name) -> dict[str, Any]:
        # Streamed because the SDK requires it for large max_tokens budgets;
        # callers still get one parsed dict.
        with self._client.messages.stream(
            model=self._model,
            max_tokens=MAX_TOKENS,
            system=system,
            messages=_to_anthropic_messages(messages),
            output_config={"format": {"type": "json_schema", "schema": schema}},
        ) as stream:
            resp = stream.get_final_message()
        self._record(resp)
        if resp.stop_reason == "max_tokens":
            raise RuntimeError(
                f"structured output truncated at {MAX_TOKENS} tokens (schema: {name})"
            )
        text = next(b.text for b in resp.content if b.type == "text")
        return json.loads(text)
