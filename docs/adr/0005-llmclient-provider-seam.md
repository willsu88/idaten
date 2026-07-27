# Provider access goes through a hand-written LLMClient seam

All five coach call sites (chat, plan, review, execution analysis, weekly summary) talk only to `LLMClient` (`backend/app/llm/__init__.py`), a three-method Protocol: `complete`, `stream`, `complete_structured`.
No provider SDK is imported anywhere else in the app.
The neutral wire format is OpenAI's shapes (history dicts + function-tool schemas); each concrete client translates at its own boundary.
`make_client` is the single place a provider is chosen, with lazy imports so running one provider never requires the other SDK, and it binds `user_id` + `call_site` so the seam is the one choke point for token and cost accounting.

## Considered Options

- **Direct SDK calls at each call site** - rejected: couples five features to one vendor, and switching providers becomes a five-site rewrite instead of a config change.
- **LiteLLM or a proxy layer** - rejected: a dependency doing exactly what ~200 owned lines do, with its own translation bugs and version churn; the same judgment as the hand-rolled loop (ADR 0004).
- **A custom in-house neutral format** - rejected: two translation layers instead of one, and an IR nobody else speaks.
  Choosing OpenAI's shapes makes `OpenAIClient` a near pass-through and concentrates all translation cost in `AnthropicClient` (tool_calls to tool_use blocks, role:tool to tool_result, cache_control injection).
- **Hand-written protocol with OpenAI-shaped neutral format** - chosen.

## Consequences

- Provider switching is a config value; the LLM-judge in the eval suite rides the same seam, so tests and production speak to the identical interface.
- The seam is the natural home for cross-cutting policy: usage accounting today, prompt caching inside `AnthropicClient`, and future model routing via `instance_settings` (ADR 0003).
  Token/cost accounting deliberately lives here and nowhere else - instrument three methods and every call in the app is metered into the `LlmUsage` table - rejecting per-user provider keys (deferred as BYOB) and external observability infra like Grafana (over-engineering at household scale; the table exports later if needed).
- Translation is maintained forever: every provider feature we want must be hand-mapped per client, and the features x providers cost grows.
- OpenAI-as-neutral biases the abstraction: features with no OpenAI equivalent (Anthropic prompt caching) have no home in the wire format and live as client-internal special cases.
- The protocol exposes only what providers share, so provider-unique capabilities are invisible to call sites until the protocol grows.
- The two clients must stay behaviorally equivalent, and no conformance suite enforces it; drift is caught only by flipping the config.
- Known extraction obstacles, recorded for the planned library split: clients read `config.*` directly instead of constructor args, and they call `usage.record()` which writes an app-DB row; both must become injected dependencies first.
