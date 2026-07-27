# Ticket: extract an agent-eval library (parked until a second consumer exists)

Filed 2026-07-27 during a grilling session. Status: parked - do not build before a second real consumer repo exists (rule of three; an abstraction extracted from one example encodes that example's accidents).
Scope update 2026-07-27: the provider-seam half is unparked into its own ticket ([[llm-seam-extraction]]); the harness half stays parked, with conventions shipped as `docs/TESTING.md` + a skill instead of code.

## The idea

The eval harness pattern in `backend/tests/test_evals.py` is reusable across agent-loop repos:

- a tool-call recorder monkeypatched around `dispatch` (trajectory assertions on `(tool_name, args)`),
- a `judge()` / `assert_judge()` pair through the provider seam, fail-closed ("passed=false when in doubt"), `{passed, reason}` structured output,
- the conventions: deterministic fixture world with known ground truth, hard assertions first, judge only for criteria a fail-closed judge can reliably grade (tone, refusal, "doesn't claim applied" - NOT "no fabricated metrics"),
- opt-in marker wiring (`pytest -m eval`, excluded by default).

## Open design questions (decide when un-parking)

1. **Two libraries, not one.** The provider seam (`LLMClient` / `make_client`) is a runtime dependency; the eval harness is dev/test-only. Coupling them drags test machinery into production consumers. But the harness depends on the seam, so the seam's API must stabilize first.
2. What is actually library-shaped vs convention-shaped? The recorder and judge are ~60 lines; the fixture-world discipline may be better shipped as a template/skill than as code.
3. Versioning cost: cross-repo coupling and API stabilization pressure arrive on day one; only worth it once >=2 repos genuinely consume it.

## Note

The instinct is the field-learnings-into-platform loop: per-deployment learnings harden into shared machinery only once more than one deployment needs them.
