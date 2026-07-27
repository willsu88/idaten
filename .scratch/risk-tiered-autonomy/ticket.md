# Ticket: risk-tiered autonomy for plan edits

Filed 2026-07-27 from a product brainstorm. Status: parked.
Industry analog: risk-rated actions - optimistic execution with the approval gate only on high-stakes operations.
Recommended build order: good small **second** build after [[coach-qa-scorecards]].

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

## Open questions

1. Threshold values for the tier boundary (mileage delta %, race-week radius) - start conservative, tune from usage.
2. Does an auto-applied edit still create a queue record (status `auto_applied`) for audit/history parity with the 4-status queue? Leaning yes.
3. UX for the undo marker on Today/Week views - reuse the pending-diff card visual language?
