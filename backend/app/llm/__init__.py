"""Model-agnostic LLM seam (same pattern as practice-two).

The planner and chat agent talk ONLY to `LLMClient`, never to a provider SDK.
Neutral shapes are OpenAI's (history + tool schemas); each concrete client
translates at its own boundary. `make_client` is the one place a provider is
chosen; imports are lazy so running one provider never requires the other SDK.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from ..config import config


@dataclass
class ToolCall:
    """One tool the model wants us to run. `args` is always a parsed dict."""

    id: str
    name: str
    args: dict[str, Any]


@dataclass
class Response:
    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)

    @property
    def is_final(self) -> bool:
        return not self.tool_calls


class LLMClient(Protocol):
    """`messages` is neutral (OpenAI-shaped) history; `tools` neutral function schemas."""

    def complete(
        self, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> Response: ...

    def stream(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        on_text: Callable[[str], None],
    ) -> Response: ...

    def complete_structured(
        self, system: str, messages: list[dict[str, Any]], schema: dict[str, Any], name: str
    ) -> dict[str, Any]:
        """One shot constrained to a JSON schema; returns the parsed object."""
        ...


def make_client(
    provider: str | None = None, *, user_id: int | None = None, call_site: str | None = None
) -> LLMClient:
    """Build a provider client. `user_id` + `call_site` bind token/cost
    accounting for every call this client makes (see app/usage.py); omit them
    for unattributed calls (tests)."""
    provider = (provider or config.llm_provider).lower()
    if provider == "anthropic":
        from .anthropic_client import AnthropicClient

        return AnthropicClient(user_id=user_id, call_site=call_site)
    if provider == "openai":
        from .openai_client import OpenAIClient

        return OpenAIClient(user_id=user_id, call_site=call_site)
    raise ValueError(f"Unknown LLM provider: {provider!r}")
