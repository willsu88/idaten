# An execution score is pinned to the prescription the run actually executed

`score_run` (`execution.py`) resolves which prescription the athlete ran - starting from the executed-workout evidence on the activity, not from the calendar - scores against that prescription, and freezes it onto the activity.
Every downstream consumer (the activity detail page, the execution breakdown, the `write_execution_analysis` LLM payload, the coach chat) reads the frozen prescription from the activity and never re-derives it by date.
When the executed prescription differs from the current `PlanDay`, the divergence is recorded as a first-class mismatch fact on the activity, surfaced deterministically in the UI and passed to the analysis prompt so the coach can name it.

The forces, from a production incident (2026-07-27): `PlanDay` is keyed `(user_id, date)` and chat edits mutate the row in place (`apply_plan_days`, `planner.py`), so a day holds exactly one prescription - the latest one.
An athlete's Garmin coach day said "Threshold"; they edited it via chat to "Base" (an easy day); the edit was never pushed to the watch (`auto_push_workouts` off), so the watch still held Threshold, and they ran it.
`score_run` looked up the plan by `(user_id, date)`, got Base, and because the row's version source was `chat_edit` it also discarded Garmin's own compliance score - which had judged the actual Threshold execution - and scored a solid threshold effort badly against an easy band, with a coach note scolding the athlete for over-cooking an easy run.
The "Threshold" title on the activity was never a match at all; it is Garmin's `activityName`, stored verbatim by `garmin/sync.py`.
Two sources of truth about "which workout applies" existed - the watch and the plan table - and nothing linked the run to either.
The prior prescription survives only inside `PlanVersion.snapshot`, which nothing at scoring time consulted.

## Considered Options

- **Status quo: look up `PlanDay` by date at score time** - rejected: it answers "what does the plan say now?" when scoring must answer "what did this run execute?"; any later edit to the day retroactively changes what an already-run workout is judged by, and the incident above is the failure mode.
- **Temporal lookup: score against the plan as it stood at run start** - rejected: it fails the founding incident itself - the Base edit was accepted 28 minutes before the run started, so the as-of lookup still returns Base while the watch, never re-pushed, still held Threshold.
  What the athlete executes is governed by device state, not by the plan table's timeline; no bitemporal schema can recover that.
- **Re-score activities when their day is edited** - rejected: it inverts the bug - an after-the-fact edit rewrites the judgment of a run that already happened; ADR 0017 already fixed the rule that stored execution scores are never recomputed, and a prescription edited after the run was never the one the athlete could have followed.
- **Store only a FK to `PlanVersion`** - rejected as the sole mechanism: it pins identity but not content - reconstructing targets means re-walking the whole-plan snapshot JSON on every read, and the resolved-band semantics of ADR 0017 (score against the band as resolved at write time) argue for freezing the resolved targets themselves, as the execution breakdown already partially does.
- **Match by `garmin_workout_id` alone** - rejected: the field is populated only for Idaten-pushed workouts; Garmin-coach workouts executed straight from the watch - the incident case - never carry it on the `PlanDay`.
- **Resolve the executed prescription at score time and freeze it onto the activity** - chosen.

## Consequences

- Resolution order at score time: if the activity is a structured-workout execution, identify its prescription from the workout evidence Garmin attaches to the activity (workout name, step structure); prefer the current `PlanDay` when it matches, otherwise search the day's `PlanVersion` history for the prescription that matches.
  An unstructured free run falls back to the current `PlanDay` by date, as today.
- The workout name is the only reliable executed-workout evidence, verified against the founding incident's live payload: Garmin returned `trainingPlanId` but `associatedWorkoutId = None` and `directWorkoutComplianceScore = None` for the run.
  So when the resolved prescription is a Garmin coach day, Garmin's compliance score may simply not exist, and scoring falls back to `_coach_segments` (splits' intensity labels plus the training-effect label against the athlete's zones) - the same path a never-edited coach day takes.
- The activity gains a frozen prescription stamp (identity: title, plus the plan version id when resolvable; content: workout type and targets for a `PlanDay` prescription, training effect for a Garmin coach one - Garmin hides a coach workout's numeric targets, so on a watch-scored coach run the stamp carries identity only and the resolved bands live in the computed breakdown) plus a mismatch flag when the executed prescription is not the current `PlanDay`.
  The stamp follows the same freeze-at-write semantics as ADR 0017's resolved bands and ADR 0014's analysis-context flight recorder: what produced a judgment is stored with the judgment.
- Name-based workout matching is a heuristic: Garmin's `activityName` for a structured execution is the workout name, but nothing guarantees uniqueness across a day's version history.
  Ties resolve toward the current `PlanDay`; a wrong tie-break degrades to today's behavior, never below it.
- A mismatched run still flips the day's `PlanDay` to `completed` (`mark_day_completed`) - the athlete trained that day - but carries the flag, so the coach can say "you ran the original Threshold, not the edited Base plan" instead of grading the wrong homework.
- The mismatch fact reaches the athlete through both channels for free: a deterministic banner on the activity page reads the flag verbatim, and the flag rides the existing `write_execution_analysis` payload, so no additional LLM call is introduced.
- Historic activities have no stamp; they keep their stored scores untouched (ADR 0017's no-recompute rule) and consumers must tolerate the stamp's absence.
- The `chat_edit`-implies-`is_idaten_plan` shortcut in `score_run` loses its authority to discard Garmin's compliance score: whether Garmin's score applies now follows from which prescription the run resolved to, not from who last edited the calendar row.
- Known gap: an Idaten-pushed day later re-edited without a re-push (stale `garmin_workout_id`) still scores against the current `PlanDay` without an evidence check - the same detection extends there, but the executed workout would have to be resolved from non-mirror version history, which this decision does not yet build.
- Divergence between the plan table and the watch remains possible (that gap is push policy, ADR 0010's editor stance, and `auto_push_workouts` - out of scope here); this decision makes the divergence detectable and honestly reported instead of silently mis-scored.
