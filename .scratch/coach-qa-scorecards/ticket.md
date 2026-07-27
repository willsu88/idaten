# Ticket: coach QA - auto-score 100% of coach conversations

Filed 2026-07-27 from a product brainstorm. Status: parked.
Industry analog: contact-center Quality Management - automated scorecards over 100% of agent conversations, drift detection on prompt changes.
Recommended build order: **first** - highest leverage, reuses existing eval machinery, and gives every later feature (voice mode included) a quality baseline.

## The idea

A nightly batch job grades every coach conversation and every generated plan against a behavioral rubric, stores the scores, and trends them.
This is production QA on the agent itself - the eval harness (`backend/tests/test_evals.py`) promoted from CI-only to continuous.

## Rubric candidates (draft)

- Cited real data from tools, no fabricated metrics or paces.
- Respected training constraints (e.g. mileage ramp limits, rest before race).
- Never claimed a plan edit was applied when it is pending in the approval queue.
- Proposed a concrete edit when the user asked for a change (vs vague advice).
- Tone: direct coach voice, no hedging walls.

Reuse the fail-closed `{passed, reason}` judge pattern; only rubric items a fail-closed judge can reliably grade (the lesson already captured in the agent-eval-library ticket).

## Shape

- Scheduler job (APScheduler, like the daily plan job) scoring the previous day's conversations with a cheap model.
- Scores stored per-conversation per-rubric-item in SQLite.
- Frontend: a small QA trend view (pass rate per rubric item over time); regression flag when a prompt/model change correlates with a drop.
- Tag each score row with the active prompt version / model id so before/after comparison is a query, not archaeology.

## Open questions

1. Cost ceiling: N rubric items x M conversations/day on a cheap model - budget and pick judge model accordingly.
2. Where does the rubric live - code, or a user-editable file (it is also coach-behavior documentation)?
3. Relationship to `COACH_QUALITY.md` - fold that doc's criteria into the rubric?
