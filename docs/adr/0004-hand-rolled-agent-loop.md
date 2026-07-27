# The chat agent loop is hand-rolled, not a framework

The chat agent is a ~90-line loop we own (`backend/app/chat/agent.py:run_chat`): history kept in neutral OpenAI-shaped dicts, one `client.stream()` call per round, tool calls dispatched and results appended, repeat until the model stops asking for tools or `MAX_TOOL_ROUNDS` fires.
We chose this over adopting an agent framework (LangChain or similar).
The pattern was already proven in a prior project (practice-two) and was ported by hand, so "hand-rolled" means the pattern is owned, not that it was invented here.

## Considered Options

- **Agent framework (LangChain or similar)** - rejected: the loop skeleton it provides is the cheap part, and every hard problem Idaten actually hit lived inside the loop where frameworks are opaque.
  Killing the provider stream from inside the `on_text` callback so a stop halts token spend, not just the UI; yielding SSE-ready event dicts directly from the loop; stamping replayed proposal markers with their current status so the model does not act on stale ones.
  Each of these was a small edit to code we own; under a framework each is a fight with an abstraction layer.
- **Hand-rolled loop** - chosen: ~90 lines, fully observable, every behavior tunable at the line where it happens.

## Consequences

- The trajectory-test layer exists because of this decision: `dispatch` is one plain function, so tests monkeypatch it and assert on the exact `(tool_name, args)` sequence of a turn.
- The rounds cap is evidence-based, not a framework default: traces show a real turn uses ~3 rounds (~5 with a pace-guard retry), so the cap is 6.
- We re-implement what frameworks give free: retries, tracing integrations, and provider translation - the `LLMClient` seam (ADR 0005) exists because this decision forced us to own translation.
- The loop's edge cases are ours alone: the queue-plus-worker-thread streaming bridge, sentinel handling, and error propagation are subtle concurrency code with no upstream community behind them.
- The loop does not compound across projects: each new agent app re-ports it by hand, which is the standing pressure to extract it into a library once a second consumer exists.
