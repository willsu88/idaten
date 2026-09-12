# A target carries exactly one axis, and every reader resolves pace before HR

A workout target - the day-level fields or any individual step - prescribes exactly one axis: a pace band or an HR band, never both.
The invariant is held by a deterministic guard (`dual_target_violations`) with the standard corrective retry in the planner, and by a mechanical clamp (`_drop_dual_targets`) on the chat-edit path.
For data stored before the guard, every reader that must pick an axis picks the same one: pace first, HR only when no well-formed pace band exists.
Uphill steps are the standing exception (ADR 0021): they resolve to HR.

The forces begin with a live defect.
A hybrid-mode tempo session was generated whose warm-up, recovery, and cool-down steps each carried both a pace band and an HR band.
The plan card and the step chips display pace before HR, so the athlete saw "9:29-8:05/km" and ran to it.
`execution._step_segment` resolved HR before pace, so the score judged those same segments against a 138-152 bpm band the athlete was never shown, and a reasonably executed session scored 55.
The precedence rule was written twice, in opposite orders, and neither side logged the ambiguity.

The dual target itself was the model resolving contradictory prompt rules.
Hybrid mode says easy running takes HR and quality takes pace; a structured quality day contains easy steps, and the prompt's "one target type per day" reads as a day-level rule, not a step-level one.
A model satisfying both rules writes both targets on the easy steps.
This is the same failure shape ADR 0021 records: a prompt rule the training-mode rules actively steer against is not an invariant until a deterministic guard holds it.

Pace wins the precedence because the score must judge what the athlete was shown.
The UI displays pace first; `garmin/push.py` sends the watch what the step prescribes; grading a target the athlete could not see is unfalsifiable coaching.
The chat-path clamp drops the HR band rather than the pace for the same reason, and it runs after `_drop_uphill_pace` so a dual-target uphill step has already resolved to HR-only.

## Considered Options

- **HR-first scoring, flip the display instead** - rejected: it grades easy segments of a quality day on HR even when the plan explicitly prescribed pace, and it changes what athletes see on every existing all-pace plan. The axis the athlete steered by must be the axis scored, and the athlete steers by what is displayed.
- **A `target_type` discriminator column** - rejected: it adds a third field that can now disagree with the two it describes, plus a migration, for an invariant the two nullable fields already express ("exactly one is set"). The guard makes the implicit encoding safe.
- **Prompt wording alone** - rejected: this is the arrangement that produced the defect, and the neighboring invariants (pace format, HR band width, terrain) each needed a guard before they held.
- **Reject dual-target proposals on the chat path instead of clamping** - rejected: the chat path has no corrective-retry loop, so rejection surfaces model noise to the athlete as a failed edit. The clamp cannot contradict the edit's intent - it keeps exactly what the UI would have displayed.
- **Guard + retry at generation, mechanical clamp on the chat path, pace-first precedence in every reader** - chosen.

## Consequences

- `execution._step_segment` resolves axes in one order: uphill -> HR; else pace band if well formed; else HR band. A step carrying both is scored on pace and logged, never silent (the ADR 0020 lesson).
- Frontend `stepTargetLabel` / `workoutTargetLabel` precedence (pace first) is now the system-wide rule, not one component's choice.
- Stored dual-target days from before the guard keep working: display and score now agree without a data migration.
- The plan prompt's hybrid rule now says "exactly one axis per target, day-level and per step"; steps within one workout may still differ (HR warm-up, pace work is the normal hybrid quality day).
- The clamp means a model that persistently emits dual targets degrades to pace-only easy steps rather than to split display/scoring; the retry log line is the signal to tune the prompt.
