# Ticket: author mode can silently overwrite accepted chat edits

Filed 2026-07-27 out of a design discussion after the QA scorecards work.
Status: idea - needs discussion before it becomes a spec.

## Problem Statement

In editor mode, a user-accepted edit is a hard override: `_OVERWRITABLE_SOURCES` in `planner.py` excludes `chat_edit` and `manual`, so materialization can never re-copy Garmin's base over a day the athlete decided.
Author mode has no equivalent guard.
The nightly authored week goes through `apply_plan_days`, whose only hard skips are non-`planned` days (completed/skipped) and the other-sport day-intent coercion - it never checks the day's source.

So the approval-queue contract leaks: a member accepts a `propose_plan_edit` in chat, and the next morning's `generate_plan` run may quietly rewrite that day.
The only protection today is soft: the snapshot shows `current_upcoming_plan` (edits included) and the system prompt says to preserve the existing plan where data doesn't demand a change.
A readiness shift or plain model churn can erase an explicitly approved decision with no proposal and no approval.

The scenario that surfaced it: a member switches from editor to author mode, immediately shapes the week via chat (the only same-day path, since the daily review is idempotent per day), and tomorrow's first authored week overwrites exactly what they just asked for.

## Solution sketch

Follow the editor-mode precedent: in `apply_plan_days`, treat still-`planned` days whose source is `chat_edit` or `manual` as pinned - the nightly author run upserts around them instead of over them.
The pin naturally expires when the day passes (status leaves `planned`), so history is never fenced off.

## Open questions for the discussion

1. Should the author LLM still be allowed to *propose* changing a pinned day through the approval queue (a review-time proposal), or is skipping silently enough?
2. Does the pin apply forever while `planned`, or only for N days after acceptance? A week-old accepted edit in a re-planned world may deserve reconsideration.
3. Should the snapshot mark pinned days explicitly so the model plans the rest of the week around them, instead of producing a day that then gets dropped on write?
4. Does the same reasoning apply to `set_day_intent` days beyond the existing run-coercion guard?

## Interaction with hr-band-targets

See `.scratch/hr-band-targets/ticket.md`: a `chat_edit` day can carry a degenerate zero-width HR band (one exists in production).
If pins land before that ticket's chat-tool width validation, such a day gets pinned - preserving bad data the nightly author run would otherwise have regenerated, and re-anchoring the model on it via `current_upcoming_plan`.
Ordering: land the HR band validation no later than pins, and consider excluding validation-failing days from pin protection.
This also adds weight to open question 3 (mark pinned days in the snapshot): if the model plans around pins, what a pin preserves must itself be sound.

## Pointers

- `apply_plan_days` (`backend/app/planner.py:720`) - the write path missing the source check.
- `_OVERWRITABLE_SOURCES` (`backend/app/planner.py:908`) - the editor-mode precedent and its comment stating the contract.
- `generate_plan` / `_evaluate_today_locked` author branch - the nightly caller.
