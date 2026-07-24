---
title: Week page edit mode - drag to reorder the week
labels: [ready-for-agent]
status: done
created: 2026-07-24
completed: 2026-07-24  # commit cee977a, verified live by Will
---

# Week page edit mode - drag to reorder the week

## Problem Statement

As a runner using Idaten, my week rarely survives contact with real life.
A dinner lands on my tempo day, my legs are trashed the day before intervals, or my climbing session moves.
Today the only way to rearrange my week is to open chat and ask the coach to replan, then wait for a proposal and accept it.
That is heavyweight for what is mentally a simple operation: "swap Tuesday and Thursday".
I want to rearrange my own week directly, with my hands, in seconds.

## Solution

The Week page gets an Edit button.
Tapping it flips the page into edit mode: all day cards collapse to their compact one-line form, a dotted outline groups them into a sortable list, and the button label flips to Done.
The user drags whole day cards up and down to swap which content lands on which date.
Past and completed days are locked anchors that do not move.
Drags stage locally; nothing persists until Done, and a Cancel affordance (or Esc) discards everything.
On Done, one atomic reorder request applies the new arrangement, re-pushes any affected watch workouts, and records an event so the coach can comment on the rearrangement in the next daily tip.
If a drop creates two adjacent quality days, a small non-blocking warning appears on the card, but the user always has final authority.

## User Stories

1. As a runner, I want an Edit button on the Week page, so that I can enter a mode dedicated to rearranging my week.
2. As a runner, I want the Edit button to flip to Done while editing, so that one control governs the whole mode.
3. As a runner, I want all day cards to collapse to compact form when I enter edit mode, so that the whole week fits on screen and drags are short.
4. As a runner, I want my accordion expansion state restored when I exit edit mode, so that editing does not destroy my reading context.
5. As a runner, I want a dotted outline around the sortable cards in edit mode, so that I can see which cards participate in reordering.
6. As a runner, I want to drag a day card up or down to swap it with another day, so that I can move a workout to a different date.
7. As a runner, I want the whole day card (run, strength session, everything on it) to move as one unit, so that the mental model stays "swap Tuesday and Thursday".
8. As a runner, I want past days and completed or skipped days to be visibly locked and undraggable, so that I cannot rewrite history.
9. As a runner, I want rest days to be draggable like any other card, so that I can shift my rest day when life demands it.
10. As a runner, I want intent days (declared other-sport days) to be draggable too, so that when my climbing day moves I can fix the plan with the same gesture.
11. As a runner, I want a dragged intent day to actually move my declared intent to the new date on save, so that the plan and my declared schedule stay in agreement.
12. As a runner, I want my drags to stage locally without saving, so that I can experiment freely before committing.
13. As a runner, I want a Cancel affordance and Esc to discard my staged changes, so that a fat-fingered drag never rewrites my week.
14. As a runner, I want Done to apply all my staged swaps in one atomic operation, so that my week is never left half-rearranged.
15. As a runner, I want a non-blocking inline warning when my arrangement puts two quality days back to back, so that I catch risky sequencing before saving.
16. As a runner, I want that warning to never block Done, so that I keep final authority over my own schedule.
17. As a Garmin watch owner, I want swapped days that were already pushed to be automatically re-pushed in the new order on save, so that my watch never shows a stale schedule.
18. As a Garmin watch owner, I want the old workout deleted from each affected day before the new one is scheduled, so that no orphaned workouts pile up on my calendar.
19. As a Garmin watch owner, I want a failed re-push to clear the pushed state and show the normal push affordance, so that the UI reflects reality instead of lying.
20. As a coached runner, I want my rearrangement mentioned as context in the next daily coaching tip, so that the coach stays aware of my week without nagging me at drag time.
21. As a coached runner, I want no immediate coach reaction to a reorder, so that quick calendar mechanics stay quick.
22. As a runner who edited a Garmin-authored day, I want revertibility recomputed after a swap, so that revert-to-Garmin remains truthful about which days diverge from the baseline.
23. As a mobile user, I want touch dragging to work smoothly inside the scrolling week list, so that I can rearrange my week on my phone.
24. As a keyboard user, I want to reorder cards with the keyboard, so that the feature is accessible without a pointer.
25. As a runner mid-drag, I want cards to animate out of the way and show a clear drop position, so that I can predict the result before releasing.
26. As a runner, I want the week summary (planned minutes, kilometres, easy percent) unchanged by reordering, so that swaps read as rescheduling rather than replanning.
27. As a runner, I want the planner to leave my arrangement alone mid-edit, so that cards never reshuffle under my fingers.

## Implementation Decisions

- Reordering is date reassignment, not list ordering.
  Plan days stay keyed by user and date; there is no order column.
  A drag swaps whole-day content between dates.
- Draggable: future planned run days, rest days, intent days, and everything riding on those days (strength sessions move with their day).
  Locked: past days and days with completed or skipped status.
- The drag unit is the whole day card.
  Independent per-item dragging (run separate from strength) is explicitly rejected.
- Persistence model: stage locally, commit on Done via a single new batch reorder endpoint that accepts the week's new date-to-content mapping and applies it atomically.
  Cancel and Esc discard staged state.
- The reorder endpoint is a direct edit that bypasses the chat proposal (PendingEdit) machinery.
  The user has final authority over their own schedule; routing a self-made drag through an accept step was rejected as ceremony.
- Coach involvement is deferred, not skipped: the reorder records an event, and the daily review prompt builder injects "the user rearranged their week" context into the next daily tip.
  No immediate reactive chat message.
- Guardrail: a pure client-side heuristic flags two adjacent quality days (tempo, intervals, long run, race) with a non-blocking inline warning.
  No LLM call, no hard block.
- Watch sync on save: for each affected day that was pushed, delete the old Garmin workout and push the new one, reusing the existing unpush and push flows.
  On Garmin failure, clear the pushed timestamp so the existing push affordance surfaces.
- Intent days are draggable; saving a moved intent rewrites the intent record's date through the existing intent upsert semantics.
  The planner must not re-fit the week mid-edit; any planner reaction happens after save through the normal daily flow.
- What travels with a swap: workout content (type, title, steps, targets, rationale).
  What stays date-anchored: execution results, cycle-phase data.
  Revertibility is recomputed server-side after the swap because moved days diverge from the Garmin Coach baseline.
- Edit mode force-collapses all cards to compact form and restores expansion state on exit.
- Drag and drop is implemented with dnd-kit (sortable), a new frontend dependency, chosen for touch, keyboard, and scroll-container handling.
- Accepted trade-offs, on the record: dragging an intent day silently reschedules a declared real-world commitment (the gesture assumes "my plans changed"), and risky sequences get only a heuristic nudge at drag time with real coach feedback deferred to the next tip.

## Testing Decisions

Good tests here exercise external behavior at stable seams: the HTTP API and rendered component behavior.
No test may assert on internal function calls, private state shape, or implementation ordering.

- Seam 1, backend HTTP API (existing seam, primary).
  All reorder semantics are tested through the new reorder endpoint plus the week payload endpoint via the FastAPI TestClient.
  Covered: atomic content swap between dates, rejection of locked days (past, completed, skipped), intent-day date rewrite, revertibility recomputation, watch delete-then-repush for affected pushed days with the Garmin client stubbed at the existing push-module boundary, pushed-state cleared on Garmin failure, and reorder event recorded.
  Prior art: the revert endpoint tests, the plan-day endpoint tests, and the push payload tests.
- Seam 2, daily review prompt grounding (existing seam).
  One test asserts that after a reorder, the next daily review's prompt context includes the rearrangement note.
  Prior art: the daily review and review grounding tests, which monkeypatch the LLM and assert on prompt content.
- Frontend behavior (staging logic, cancel restore, locked-card exclusion, adjacency heuristic) is verified manually for this feature.
  The repo has no frontend test infrastructure today; standing it up is deliberately split into its own ticket (see frontend-test-infra) so this diff stays about reordering.
  To keep that future work cheap, the staging reducer and the adjacency heuristic must be written as pure functions in their own modules, importable without rendering.

## Out of Scope

- Cross-week dragging; edit mode operates within the visible Monday-to-Sunday week only.
- Independent dragging of strength sessions or intents separately from their day card.
- Editing workout content (titles, steps, targets) in edit mode; this is reordering only.
- Immediate coach reactions, proposals, or auto-replanning triggered by a reorder.
- Server-side validation of training quality; the adjacency warning is client-side and advisory.
- Reordering past or completed days in any form.
- Frontend automated tests of any kind; frontend test infrastructure is a separate ticket (frontend-test-infra) to be designed later.

## Further Notes

- The design emerged from a grilling session; the coach-involvement decision (deferred daily-tip context instead of reactive chat) was the user's refinement over an immediate-comment recommendation.
- The batch endpoint should emit exactly one planner-visible event per save regardless of how many cards moved, so a heavy editing session reads as one rearrangement to the coach.
- Frontend test infrastructure was considered and deliberately deferred to its own ticket, to be designed via a grilling session; this feature only prepares for it by keeping state logic pure and importable.
