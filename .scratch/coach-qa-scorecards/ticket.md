# Ticket: coach QA - auto-score 100% of chat sessions

Filed 2026-07-27 from a product brainstorm; grilled into a spec the same day.
Status: ready-for-agent.
Industry analog: contact-center Quality Management - automated scorecards over 100% of agent conversations.
Decision record: ADR 0016 (unit, judge provider, version stamps, verdict semantics, and all rejected alternatives).
Design description: the "Continuous QA" section of COACH_QUALITY.md.

## Problem Statement

The admin has no way to know whether the coach behaves well in production chat.
CI evals check behavior at deploy time against fixture worlds, and human thumbs cover reviews and analyses, but chat - the surface where fabricated metrics and false "your plan is updated" claims would actually happen - is completely unobserved.
When the admin edits the chat system prompt, there is no way to see whether real conversations got better or worse; a prompt edit ships on hope.

## Solution

Every night, a scheduler job grades every chat session that has gone quiet against a small behavioral rubric, using a fail-closed LLM judge on a different provider than the coach.
Verdicts (pass / fail / n/a, with the judge's reason) are stored per session per rubric item, stamped with the producing prompt version, the rubric version, and the judge model.
A card on the admin page shows version-grouped pass rates with visible denominators, highlights when a new prompt version underperforms, and lists recent fails with reasons and session references.
The result: the admin reads one card to know the coach is behaving, sees exactly which conversations went bad and why, and gets a before/after answer for every prompt edit.

## User Stories

1. As an admin, I want every chat session automatically graded against a rubric, so that I know the coach behaves even when nobody complains.
2. As an admin, I want the grading to check the coach's claims against what its tools actually returned, so that fabricated metrics are caught, not just bad-sounding prose.
3. As an admin, I want a verdict on whether the coach ever claimed a pending edit was applied, so that the highest-stakes lie in the product is watched every night.
4. As an admin, I want to know whether the coach proposed a concrete edit when a member asked for a change, so that vague advice instead of action is visible.
5. As an admin, I want sessions where a rubric item did not apply recorded as n/a and excluded from pass rates, so that vacuous passes never dilute a real failure signal.
6. As an admin, I want pass rates grouped by prompt version with visible denominators, so that "did my prompt edit help" is answered by reading a table, not by archaeology.
7. As an admin, I want a highlight when a new prompt version underperforms the previous one with enough sessions to matter, so that I look at the right place without a fake statistical alarm.
8. As an admin, I want each fail to show the date, session reference, and the judge's reason, so that I can decide from the reason alone whether to investigate.
9. As an admin, I want the judge's reasons to describe failures without quoting members' words, so that the QA card never becomes ambient surveillance of household chats.
10. As an admin, I want QA judge spend to appear in the usage and cost tracking under its own call site, so that the cost of quality is as visible as the cost of coaching.
11. As an admin, I want to toggle QA scoring off and on like other system-initiated call sites, so that I control when the judge runs and what leaves the perimeter.
12. As an admin, I want a resumed session re-graded in full, so that a verdict always describes the whole conversation and a stale pass never hides a session that went off the rails.
13. As a member, I want my chat sessions scored only for the coach's conduct, with no transcript browser in the admin UI, so that quality monitoring does not mean my conversations are on display.
14. As an operator, I want the rubric to live in code and change only through a deploy, so that every rubric change is reviewed, versioned, and visible in history.
15. As an operator, I want score rows stamped with prompt version, rubric version, and judge model, so that any two scores are comparable or provably not comparable.
16. As an operator, I want the judge on a different provider than the coach, so that the coach is never graded by its own model family.
17. As an operator, I want the nightly job to be idempotent and to catch up after downtime, so that a missed night is a delay, not a hole.
18. As an operator, I want tool calls persisted with each chat session, so that the judge - and I, when debugging - can see the ground truth the coach was working from.

## Implementation Decisions

- Unit of judgment: the whole chat session, addressed as `(call_site, artifact_ref)` where `artifact_ref` is the session id; the schema supports any coach artifact so later call sites need no migration.
- New score table: one row per (session, rubric item), holding verdict (`pass` / `fail` / `n/a`), the judge's reason, `prompt_version`, `rubric_version`, `judge_model`, and timestamps; upsert key is (artifact_ref, rubric item).
- Gradeability: a session is graded once its last message is before today's local midnight; a graded session that receives new messages is re-graded in full at the next run, replacing its verdicts.
- Rubric v1 (three items): grounded data (no metrics absent from tool results), never claims a pending edit was applied, proposes a concrete edit when the member asked for a change (n/a when they did not).
- Rubric home: a Python module of structured items (stable key, criteria text, applicable call sites); its hash is `rubric_version`.
- Judge: one structured-output call per (session, rubric item) through the existing provider seam, fail-closed, schema `{applicable, passed, reason}`; the judge prompt forbids quoting the member.
- Judge config: new `judge_provider` / `judge_model` settings (default OpenAI `gpt-5.4-mini`); the seam gains a per-call model override; usage is recorded under call site `qa`.
- Judge input: the session transcript plus its persisted tool calls; production chat starts writing tool invocations and results as chat message rows of a new `tool_call` kind at the existing dispatch point.
- Provenance: chat assistant messages are stamped at generation time with `prompt_version` = hash of the hand-written system template plus the athlete's style line - never the hydrated prompt.
- Scheduling: the job joins the existing in-process scheduler (ADR 0011) shortly after local midnight, follows the existing catch-up pattern, and is a no-op on re-run.
- Toggle: `qa` becomes a third instance-level call-site toggle (ADR 0003 mechanism); skipped nights are never backfilled, matching forward-only resume semantics.
- Admin UI: one card on the admin page - weekly pass rates as counts, a version-grouped comparison table, a minimum-sample (>=5 applicable) underperformance highlight, and a recent-fails list; no transcript drill-down.
- API: an admin-only QA summary endpoint feeding the card; contract section appended to API_CONTRACT.md before the frontend is built.
- Privacy: all members' sessions are scored; surfacing is admin-only; the judge-provider exposure is documented in COACH_QUALITY.md.

## Testing Decisions

Good tests here assert external behavior at the highest existing seams: the provider seam (stub the judge, script its verdicts), the scheduler job function (call it directly against a seeded world), and the admin API (assert the summary payload).
No new seams are needed.

- Layer 1-2 (deterministic, free): gradeability windows (quiet-since-midnight, straddling, resumption re-grade and upsert), n/a exclusion from computed pass rates, version stamping (template hash stable across hydrated data changes, changing on template/style edits), toggle behavior (off = no judge calls, on = forward-only), idempotent re-run, catch-up after a missed night, tool-call persistence rows, and the summary endpoint's shape and version grouping - all with a stubbed judge through the seam.
- Layer 3-4 (`pytest -m eval`, paid): judge quality itself - each rubric item graded against transcripts with known ground truth (a fabricated pace must fail, a grounded reply must pass, a no-edit-request session must return n/a), following the add-eval-case skill.
- Frontend: vitest for the card's rendering rules (counts not bare percentages, highlight logic, fails list) against fixture payloads.
- Prior art: the judge and fixture-world conventions in the existing eval tests; the toggle tests; the feedback API tests; the metrics/summary endpoint tests.

## Out of Scope

- Scoring call sites other than chat (the schema supports them; a later ticket enables them).
- The parked rubric items: tone, and training-constraint compliance (returns only with a phrasing whose ground truth the judge can see).
- The member "report this session" affordance (fast-follow ticket; reserves surface name `chat_session`, joins score rows on session id).
- Transcript drill-down from the QA card.
- Statistical drift detection, alerting, or any composite per-session score.
- PII redaction machinery and zero-data-retention agreements (documented as the at-scale path, deliberately not built at household volume).
- Judge calibration measurement (needs member reports to compare against).

## Further Notes

- Volume reality: roughly nine sessions a week; the QA job roughly triples LLM call count while adding only cents per month; the biggest call site by volume will be the judge.
- The three stamps answer different questions: `prompt_version` = did my edit change behavior; `rubric_version` = did the bar move; `judge_model` = did the grader change; a trend line is only meaningful within constant stamps.
- Build order note from the brainstorm stands: highest leverage, reuses existing eval machinery, and gives every later feature (voice mode included) a quality baseline.
