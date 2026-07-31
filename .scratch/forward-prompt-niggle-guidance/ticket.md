# Ticket: the forward generator prompt has no run-planning niggle guidance

Filed 2026-07-31, split out of [cycle-forward-generator](../cycle-forward-generator/ticket.md) during grilling.
Status: idea - needs a spec pass, but the gap is confirmed in code.

## Problem Statement

`active_niggles` is in the shared snapshot (`planner.py:561`), and `REVIEW_SYSTEM_PROMPT` has a full policy for it (`planner.py:1487-1499`): bias down while anything is open, ease firmly at severity 2-3, severity >= 2 vetoes any green-light.

The forward `SYSTEM_PROMPT` mentions niggles only for strength-focus selection (`planner.py:233-236`).
It has no run-planning guidance at all, so the generator can place hard sessions, or an aggressive long-run progression, during an open injury.
This is arguably worse than the cycle gap: the review can only soften same-day for editor mode, and author-mode review delegates back to this same niggle-blind prompt.

The cycle-forward-generator ticket adds only the minimal brake (its follicular green-light is qualified by the severity >= 2 veto); this ticket is the full port.

## Sketch

Mirror the review block's intent for week-authoring: while a severity-1 niggle is open avoid stacking hard sessions and watch load on that area; at severity 2-3 lean firmly toward easing/cross-training/rest for the affected work; warm, by-body-part rationale, never guilt.
Needs a paired eval case (ease under an open severity-2 issue) and possibly a guard case (severity-1 niggle does not gut a sound week).

## Pointers

- `SYSTEM_PROMPT` (`backend/app/planner.py:145-241`) - where the block goes.
- `REVIEW_SYSTEM_PROMPT` niggle block (`backend/app/planner.py:1487-1499`) - the policy to mirror.
- `active_niggles` (`backend/app/niggles.py`) - the snapshot signal.
