# Ticket: risk-tiered autonomy for plan edits

Filed 2026-07-27 from a product brainstorm. Status: parked.
Industry analog: risk-rated actions - optimistic execution with the approval gate only on high-stakes operations.
Recommended build order: good small build now that coach QA scorecards shipped (ADR 0016) - the prerequisite is met.

## The idea

Today every plan edit goes through the approval queue, regardless of stakes.
Tier edits by risk and calibrate autonomy accordingly:

- **Low risk** (swap two easy days, reword a rationale, minor pace tweak): auto-apply immediately, with a visible undo affordance and a "coach changed this" marker.
- **High risk** (weekly mileage change beyond a threshold, moving/changing the long run, anything inside race week, workout-type changes): keep the pending-approval diff exactly as today.

The gate stays where it earns its friction; trivial changes stop nagging.

## Design constraints

- **The risk classification is CODE, not the model.** Compute tier deterministically from the edit diff (mileage delta, days touched, proximity to race, workout-type change).
  Never let the model self-declare "this edit is low risk" - never let the model classify what code can derive.
- Undo must be real: auto-applied edits keep the before-state and revert in one tap, including un-pushing/re-pushing the watch workout if it already synced.
- Instance-level setting for the autonomy level (off / low-only / default tiers), consistent with the existing coach call-site toggles (ADR 0003).
- Watch push timing: consider deferring the Garmin push for auto-applied edits briefly (or until next sync window) so undo usually beats the push.

## Historical replay findings (2026-07-28)

Replayed a candidate rule set against all 31 real `pending_edits` rows before writing any code.

- Roughly half the history classifies low-tier (same-day downgrades, target loosening, text tweaks, no-op confirmations).
  The queue interruption volume would drop by about half.
- **The dismissals cluster inside the naive "safe" tier.** Three of the five dismissed proposals were physiologically harmless trims that a magnitude-based rule would have auto-applied.
  The user dismissed them because they wanted to do the workout anyway - physiologically safe is not preference-safe.
- The empirical boundary is **same-day vs future-day, not big vs small**: same-day readiness-driven downgrades went 6-for-6 accepted; speculative future-week "keep load sensible" trims went 0-for-2.
- A same-day *trim* of the long run was accepted without friction; keep the long-run escalation rule for moves and extensions only.

## Classifier features (from the real data model)

Input is `PendingEdit.current` vs `PendingEdit.changes` (before/after PlanDay dicts) plus two lookups (race date, open niggles).

1. Weekly load delta (sum `distance_km`/`duration_min` across touched window).
2. Intensity direction on `workout_type` transitions - the asymmetry is the point: removing stress is low, adding stress is high.
3. Long-run identity: moved or extended escalates; same-day trim does not (per replay).
4. `target_pace`/HR target changes beyond a threshold (loosening is low, tightening is high).
5. Text-only edits (numeric fields and type identical) - the floor tier.
6. Race proximity (`days_to_race` for any touched day) and taper phase: everything escalates inside the radius.
7. Open niggle + intensity increase escalates regardless of magnitude.
8. `pushed_at`/`garmin_workout_id` is an *undo-cost* input to the router, separate from risk: a cheap edit with an expensive undo may still deserve the queue.

Keep validity and risk distinct: the pace guard in `create_pending_edit` rejects invalid edits before a proposal exists; risk tiers route valid ones.

## UX position (2026-07-28)

Auto-apply of any edit that encodes a coach-vs-athlete disagreement (downgrades included) converts the user's "no" from a pre-decision into undoing the coach - same outcome, much worse feeling.
So:

- v1 auto-applies **conflict-free edits only**: text, target loosening, no-ops, reflows of already-skipped days.
  Not downgrades, even same-day ones, at first.
- **Autonomy is earned per category from acceptance history**: promote a category (e.g. same-day readiness downgrades) to auto-apply only after a clean accept streak in that category; demote it after an undo.
  The accept/dismiss data to drive this already exists in the queue.
- Consider a middle state between ask and act: default-apply with a veto window ("applies tonight unless you object").

## Riders

- Bug found during replay: edit #12's stored `current` and `changes` are byte-identical - the `current` snapshot appears to capture post-supersession state rather than the true before-state.
  Any diff-based classifier depends on clean before/after snapshots; fix before building on them.

## Open questions

1. Threshold values for the tier boundary (mileage delta %, race-week radius) - start conservative, tune from usage.
2. Does an auto-applied edit still create a queue record (status `auto_applied`) for audit/history parity with the 4-status queue? Leaning yes.
3. UX for the undo marker on Today/Week views - reuse the pending-diff card visual language?
4. Category promotion mechanics: how long an accept streak before a category earns auto-apply, and does one undo demote just the category or drop the autonomy level globally?
5. Is the veto-window middle state worth its complexity, or do the two clean states (ask / act-with-undo) cover it?
