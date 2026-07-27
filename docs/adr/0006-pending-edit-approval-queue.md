# Plan changes go through a stateful approval queue, not a confirm dialog

The coach's only side-effecting tool is `propose_plan_edit`, and its side effect is a `PendingEdit` row: nothing touches the plan until the athlete accepts it in the UI.
Proposals carry four statuses (`pending`, `accepted`, `dismissed`, `superseded`) and a one-pending invariant: every new proposal auto-flips all pending ones to `superseded` (`planner.py`), so exactly 0 or 1 proposal is ever live.
Both proposal sources (chat edits, nightly daily review) flow through the same queue and the same `apply_plan_days`.

## Considered Options

- **Synchronous confirm dialog** - rejected: the daily review proposes while the athlete is asleep; there is no session to confirm in.
- **Direct writes + undo** - rejected: the plan is consumed at 6am from the watch, before any review; an unnoticed overnight change means running the wrong workout, then finding the undo button.
  Undo suits changes a human sees before acting on them; this one isn't.
- **Draft plan / PR model (multiple pending changesets, merge on accept)** - rejected as scale we don't have: one athlete and one coach never benefit from parallel changesets, but the merge problem arrives on day one.
  This is the acknowledged evolution path if proposal sources multiply.
- **Advisory-only coach (no write tools)** - rejected: the diff card with one-tap accept is the coaching experience; transcription is friction and error.
- **Stateful approval queue with one-pending invariant** - chosen: the minimum machinery that survives asynchrony.

Within the queue, `superseded` as a fourth status was itself a decision:

- **Reuse `dismissed`** - rejected: a dismiss is an athlete decision carrying feedback signal (reason chips split preference from quality bugs); a supersede is system housekeeping with no human in it.
  Conflating them poisons the quality-loop data and makes the UI lie ("you dismissed this").
- **Hard-delete the old proposal** - rejected: chat markers would reference missing rows on replay, history disappears, and eval-worthy provenance is destroyed.
- **Generic `closed` status + reason column** - not needed at four statuses; the migration target if a fifth reason ever appears.

## Consequences

- The gate is structural, not prompt-based: the model cannot mutate the plan, and the eval suite's strongest assertions (out-of-scope questions call no write tools) exist because writes are tool calls.
- Accepting an old proposal against plan state a newer one assumed is impossible by construction; newest wins, always.
- The stored `current` (pre-edit days) keeps the diff honest: the UI shows the change against what existed at proposal time.
- Accept/dismiss is the feedback signal for proposals (no thumbs needed); dismiss reasons feed COACH_QUALITY.md's loop.
- Chat history replays proposal markers as frozen text while status moves underneath; every replayed marker is therefore stamped with its current status (`_EDIT_STATUS_NOTE`, see ADR 0004), or the model treats dead proposals as live.
- Cost of the design: a state machine and its invariant to maintain, and the athlete can never hold two alternative proposals side by side.
