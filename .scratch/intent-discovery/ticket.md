# Ticket: intent discovery - mine chat history for tool gaps

Filed 2026-07-27 from a product brainstorm. Status: parked.
Industry analog: conversation-intelligence intent discovery.

## The idea

A batch job clusters chat history into user intents and flags the ones the coach handled badly or could not act on:
no tool existed, it deflected, the user rephrased repeatedly, or the conversation ended without resolution.
Output: a ranked "missing tools / missing features" backlog mined from real usage instead of guesswork.

## Shape

- Periodic job (weekly is plenty at single-user volume): LLM pass over recent conversations -> structured `{intent, resolved, failure_mode}` rows.
- Aggregate into an intent frequency x resolution-rate table; surface unresolved clusters in the frontend (or just a markdown report in `.scratch`/dashboard to start).
- Failure taxonomy worth distinguishing: missing tool, missing data, refused, hallucination risk avoided, user gave up.

## Open questions

1. Single-user volume is low - is a simple "unresolved conversations" list enough, skipping clustering entirely for v1?
2. Feed discovered gaps back automatically (draft ticket generation) or keep it a human-read report?
3. Overlap with coach QA ticket: same nightly scan could emit both scores and intents - one pipeline, two outputs?
   See [[coach-qa-scorecards]].

## Note

This is the field-learnings-into-platform loop as a working artifact: usage -> mined gaps -> roadmap.
