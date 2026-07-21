"""OpenAI client — the neutral shapes ARE OpenAI's, so this is nearly a pass-through."""

from __future__ import annotations

import json
from typing import Any, Callable

from openai import OpenAI

from ..config import config
from ..usage import Usage, record
from . import Response, ToolCall


class OpenAIClient:
    def __init__(self, *, user_id: int | None = None, call_site: str | None = None) -> None:
        self._client = OpenAI(api_key=config.openai_api_key)
        self._model = config.openai_model
        self._user_id = user_id
        self._call_site = call_site

    def _record(self, usage: Any) -> None:
        """OpenAI's `prompt_tokens` INCLUDES cached tokens; split them out so the
        cost formula prices cache reads once, at the discounted rate."""
        if usage is None:
            return
        details = getattr(usage, "prompt_tokens_details", None)
        cached = getattr(details, "cached_tokens", 0) or 0
        prompt = getattr(usage, "prompt_tokens", 0) or 0
        record(
            "openai", self._model,
            Usage(
                input_tokens=max(prompt - cached, 0),
                output_tokens=getattr(usage, "completion_tokens", 0) or 0,
                cache_read_tokens=cached,
                cache_creation_tokens=0,  # OpenAI has no separate cache-write charge
            ),
            self._user_id, self._call_site,
        )

    def _params(self, system: str, messages: list[dict], tools: list[dict]) -> dict:
        params: dict[str, Any] = {
            "model": self._model,
            "messages": [{"role": "system", "content": system}, *messages],
        }
        if tools:
            params["tools"] = tools
            # Reasoning models (gpt-5.x) reject function tools + reasoning_effort
            # on /v1/chat/completions ("...set reasoning_effort to 'none'"). Our
            # chat always sends tools, so disable reasoning on the tool path.
            # Harmless on non-reasoning models. (Reasoning-with-tools would need
            # the /v1/responses API instead.)
            params["reasoning_effort"] = "none"
        return params

    @staticmethod
    def _parse(message: Any) -> Response:
        calls = [
            ToolCall(id=tc.id, name=tc.function.name, args=json.loads(tc.function.arguments or "{}"))
            for tc in (message.tool_calls or [])
        ]
        return Response(content=message.content, tool_calls=calls)

    def complete(self, system, messages, tools) -> Response:
        resp = self._client.chat.completions.create(**self._params(system, messages, tools))
        self._record(resp.usage)
        return self._parse(resp.choices[0].message)

    def stream(self, system, messages, tools, on_text: Callable[[str], None]) -> Response:
        stream = self._client.chat.completions.create(
            **self._params(system, messages, tools),
            stream=True,
            # Ask for a trailing usage-only chunk; without this streamed calls
            # report no usage at all.
            stream_options={"include_usage": True},
        )
        content: list[str] = []
        # tool-call fragments buffered by index until the stream ends
        pending: dict[int, dict[str, Any]] = {}
        usage: Any = None
        for chunk in stream:
            # The final usage chunk carries usage and an EMPTY choices list, so
            # capture it before the choices guard skips the chunk.
            if getattr(chunk, "usage", None) is not None:
                usage = chunk.usage
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta.content:
                content.append(delta.content)
                on_text(delta.content)
            for tc in delta.tool_calls or []:
                slot = pending.setdefault(tc.index, {"id": "", "name": "", "args": ""})
                if tc.id:
                    slot["id"] = tc.id
                if tc.function and tc.function.name:
                    slot["name"] = tc.function.name
                if tc.function and tc.function.arguments:
                    slot["args"] += tc.function.arguments
        self._record(usage)
        calls = [
            ToolCall(id=s["id"], name=s["name"], args=json.loads(s["args"] or "{}"))
            for _, s in sorted(pending.items())
        ]
        return Response(content="".join(content) or None, tool_calls=calls)

    def complete_structured(self, system, messages, schema, name) -> dict[str, Any]:
        resp = self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "system", "content": system}, *messages],
            response_format={
                "type": "json_schema",
                "json_schema": {"name": name, "schema": schema, "strict": True},
            },
        )
        self._record(resp.usage)
        return json.loads(resp.choices[0].message.content or "{}")
