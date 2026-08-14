# Ticket: friends + send a workout to a friend

Filed 2026-07-27 (idea noted 2026-07-17, ROADMAP - dissolved into tickets, see git history). Status: done (built 2026-08-14).
Spec settled 2026-08-14 in design conversation; decisions below are final.

## Want

Send a plan day's workout to another household member.
The recipient accepts it onto their own plan, either verbatim or with the targets translated to their own HR zones and paces.
Works from the UI and from chat (new agent tool `send_workout_to_friend`).

## Settled decisions

- **Friends = household members.** No friend graph, no requests, no Friends page; the instance roster is the social circle.
  Cross-instance sharing is out of scope (a future portable-export feature would reuse the de-personalize half of the translation).
- **A share is a snapshot**, not a reference: a whitelisted projection of the sender's PlanDay (no rationale, no readiness context) plus the sender's fitness parameters (HR zones, VDOT) frozen at send time.
- **Inbox on Today.** A pending share renders as a card on the recipient's Today page (same surface as pending coach edits) with three actions: "Accept their targets", "Accept with my zones" (side-by-side preview), Decline.
- **Accept writes directly to PlanDay** via `apply_plan_days` with `PlanVersion.source = "shared"` - the accept tap is the approval; no second pass through the PendingEdit queue.
  "shared" is not in `_OVERWRITABLE_SOURCES`, so the coach's daily job plans around it and never regenerates over it, and scoring attributes to it exactly like an accepted chat edit.
  Auto-push after accept when `auto_push_workouts` is on (same as edit accept).
- **Adaptation is deterministic code, not an LLM call.**
  HR bands map by zone position (sender's zones -> fractional zone span -> recipient's zones, then `ensure_hr_band`).
  Pace bands map by %vVO2max (Daniels cost curve both directions), then grounded against the recipient's observed pace profile.
  A recipient in `hr` training mode gets pace targets converted to their equivalent zone bands; HR targets are never converted to pace.
  ADR 0020/0017/0021 invariants hold on the adapted output (band grammar, min HR width, no uphill pace).
  When either side lacks the needed parameters (no Garmin VDOT/zones), only accept-as-is is offered, with the reason shown.
- **Date**: a share targets the sender's date by default; the recipient may pick another date on accept. A share whose target date passes un-accepted auto-expires.
- **Only run workouts are shareable** (`RUN_TYPES_PLAN`, i.e. not rest/cross_train).
- **No sent-status surface in v1** (sender does not see accepted/declined).
- **Tenant boundary**: the `shared_workouts` table is the only place two user_ids share a row; reads always scope by the authenticated side; the chat tool takes a friend *name*, never an id, and resolves it server-side.

## Build order

1. ADR (cross-tenant sharing) + API_CONTRACT v1.42 section.
2. `app/sharing.py`: snapshot builder + pure adapt functions, unit-tested.
3. `SharedWorkout` model (auto-migrated) + `/api/share/*` endpoints + tenant tests.
4. Chat tool `send_workout_to_friend`.
5. Frontend: send picker on day detail / workout card, inbox card on Today with preview.
