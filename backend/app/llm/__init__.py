"""App-side binding of the llm-seam library.

The seam itself (LLMClient Protocol, neutral OpenAI-shaped wire format, both
provider clients) lives in https://github.com/willsu88/llm-seam - extracted
from this module per ADR 0005, consumed pinned in requirements.txt.

This wrapper is the one place the library's injected dependencies are wired:
config supplies credentials and model choice, and `on_usage` closes over
`user_id` + `call_site` so every call is metered into the LlmUsage table
(see app/usage.py). Call sites are unchanged - they still talk only to
`LLMClient` via this module's `make_client`.
"""

from __future__ import annotations

from llm_seam import LLMClient, Response, ToolCall, Usage
from llm_seam import make_client as _make_client

from ..config import config
from ..usage import record

__all__ = ["LLMClient", "Response", "ToolCall", "Usage", "make_client"]


def make_client(
    provider: str | None = None,
    *,
    user_id: int | None = None,
    call_site: str | None = None,
    model: str | None = None,
) -> LLMClient:
    """Build a provider client. `user_id` + `call_site` bind token/cost
    accounting for every call this client makes (see app/usage.py); omit them
    for unattributed calls (tests). `model` overrides the provider's configured
    model - used by the QA judge, which is pinned independently of the coach
    (ADR 0016)."""
    provider = (provider or config.llm_provider).lower()
    if provider == "anthropic":
        api_key, default_model = config.anthropic_api_key, config.anthropic_model
    elif provider == "openai":
        api_key, default_model = config.openai_api_key, config.openai_model
    else:
        raise ValueError(f"Unknown LLM provider: {provider!r}")

    def on_usage(prov: str, mdl: str, u: Usage) -> None:
        record(prov, mdl, u, user_id, call_site)

    return _make_client(
        provider, api_key=api_key, model=model or default_model, on_usage=on_usage
    )
