# Ticket: HR targets collapse to zero-width bands (e.g. "150-150 bpm")

Filed 2026-07-27 from a user report: plan days show HR targets like "145-145 bpm for 30 min", which is impossibly narrow.
Status: spec agreed (grilling session 2026-07-27, decision recorded as ADR 0017) - ready to implement.

## Problem statement

Plan days carry an HR target band (`target_hr_low`/`target_hr_high`), and the UI, Garmin push, and execution scoring all treat it as a range.
In production, the large majority of HR-target days have `low == high` - a zero-width band.

Root cause, primary: the Garmin coach mirror.
Garmin's coach taskList describes a workout with a single HR number (e.g. `18:00@172bpm`).
`_parse_hr` in `planner.py` extracts that one number and `_coach_day_fields` writes it as both bounds (`"target_hr_low": hr, "target_hr_high": hr`, planner.py:968).
Every mirrored base day therefore has a degenerate band, and sources that copy day fields (`reorder`) inherit it.

Root cause, secondary: the LLM paths have no band-width guard.
The plan schema and chat edit tool accept any `low <= high` (even `low == high` - nothing checks at all).
The prompt asks for zone-anchored bands and the model usually complies (observed chat edits produce ~14-18 bpm bands), but at least one chat edit emitted a zero-width band, likely anchoring on the mirrored day it was editing.
Pace targets get a corrective-retry guard (`pace_violations`) and a deterministic post-check (`check_week`); HR targets get neither.

Mode context (verified against the live DB on 2026-07-27): every daily review on record for both users ran in editor mode, and no `daily_review`-source plan version exists, so all observed zero-width bands came from the editor-mode mirror.
User 2's `plan_authoring = "author"` setting is newer than the latest review; `plan_mode` now correctly returns author for them.
Author mode never runs the mirror, but stale mirrored days persist in `plan_days` until regenerated, and the LLM can anchor on them - the one zero-width `chat_edit` day is the likely example.
So the mirror fix protects editor-mode users, and the LLM width guard is the only protection in author mode.

## Why it matters downstream

- `garmin/push.py` `_target` pushes the band verbatim as a custom HR zone (`targetValueOne/Two`), so the watch enforces a 0 bpm corridor and alerts constantly.
- `execution.py` `_step_segment` scores time-in-band against the same corridor, so nearly every second of a correctly-executed run scores as out of range.
- The frontend renders the band verbatim ("HR 145–145"), which is what the user saw.

Note the contrast: pace targets are a single value by schema, and push time widens them by `PACE_BAND_MPS` (±0.15 m/s) before they reach the watch.
HR has no equivalent widening anywhere.
Pace display is a single number by design, so pace does NOT have this bug - but it also means "widen at push" is an established pattern we could mirror.

## Agreed spec (see ADR 0017 for the full rationale and rejected alternatives)

Scope: mirror widening + LLM-path guards, one change.
Historical repair (backfilling past zero-width bands, re-scoring stored execution scores) is deliberately deferred; edit pins stay their own ticket and land after this one.

Invariant: a stored HR target band (day-level or any step inside `steps` blocks) is always a real range; `low == high` is invalid data.
Representation: widen at write - the mirror stores the resolved zone band, consumers stay unchanged.

Widening rule (`_coach_day_fields`):

1. The band is the zone in `settings_store.hr_zones` containing the parsed number.
2. Exact zone boundary: lower zone wins for easy/recovery/long, higher zone for quality (tempo/intervals/race).
3. Zones unavailable, or number outside every zone: fixed ±7 bpm around the number - never snap into the nearest zone.

LLM-path guards (threshold: width < 5 bpm, checked on day-level AND every step in every block):

- `generate_plan`: one corrective retry, following the pace-guard pattern; log if still violated.
- `check_week`: warn on width < 5 bpm; additionally warn (only) when a band is not contained within ±1 zone of a sensible zone for the workout type.
- Chat edit tool: mechanically widen a degenerate band to its containing zone (safe because it is the same band the mirror rule produces).

Tests:

- Layers 1-2: widening rule as a pure function (containment, boundary tie-break, both ±7 fallbacks, never zero-width); chat-tool clamp incl. nested steps; `check_week` warning; generation retry with a stubbed client (template: pace-guard tests in `test_grounding_and_phases.py`); scoring guard - a segment built from a stored zero-width band scores against the widened band.
- Layer 3: assert-style eval (fold into an existing generated-plan case if one exists) - no band narrower than 5 bpm anywhere in a generated plan. Use the `add-eval-case` skill.

Scoring-side guard (decided 2026-07-27, closes the former open question):

- Already-stored execution scores are never recomputed.
- All scoring from now on must never score against a degenerate band: in `execution.py`, when a stored band (day-level or step-level) is narrower than 5 bpm, resolve it through the same widening helper before building the scoring segment. `_idaten_segments` already receives `zones`; it just needs to pass them down.
- Net shape: ONE shared widening function (containment + boundary tie-break + ±7 fallbacks) with three call sites - mirror write, chat-tool clamp, scoring guard.

Note: the nightly editor-mode mirror re-materializes still-`planned` days, so future degenerate days self-heal on deploy without a migration; the scoring guard covers everything the self-heal cannot reach (past days, user-owned edits).

## Interaction with author-mode-edit-pins

This ticket must be considered together with `.scratch/author-mode-edit-pins/ticket.md`, in both directions.

- Without pins, the athlete's manual fix is not durable: the chat edits carrying proper bands are still-`planned` days that the next author-mode `generate_plan` run can silently overwrite (`apply_plan_days` has no source check).
- With pins but without this ticket's chat-tool validation, a zero-width `chat_edit` day gets pinned - permanently fencing off a degenerate band the author run would otherwise have regenerated, and (via `current_upcoming_plan`) seeding the model with a bad anchor every night.

Ordering constraint: the band widening and chat-edit-tool width validation should land no later than edit-pins, and pins should probably not protect days that fail target validation.

## Pointers

- `backend/app/planner.py:930` `_parse_hr`, `:946` `_coach_day_fields` (the `low = high = hr` write), `:808` `check_week` (where the width check goes).
- `backend/app/settings_store.py:273` `hr_zones` (single source for zone bands).
- `backend/app/garmin/push.py:67` `_target` (verbatim HR push; pace widening precedent at `PACE_BAND_MPS`).
- `backend/app/execution.py:44` `_step_segment` (scores against the stored band).
- `backend/app/chat/tools.py:166` chat edit tool schema (no width validation).
