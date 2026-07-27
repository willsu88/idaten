# Ticket: friends + send a workout to a friend

Filed 2026-07-27 (idea noted 2026-07-17, ROADMAP - dissolved into tickets, see git history). Status: idea.

## Want

Users add each other as friends, then share/send a workout to a friend.
Must work BOTH via the UI and via chat (the agent needs a new tool, e.g. `send_workout_to_friend`), plus a friend-management surface.

## Design questions to settle at spec time

- Friend request/accept flow vs auto-friends within the household.
- What exactly is "a workout" being sent: a single plan day with steps, or a library template?
- Does the recipient accept it into their plan (approval-gated, like plan edits) or does it land in an inbox?
- **Tenant isolation**: this is the FIRST feature that deliberately crosses user boundaries (ADR 0008).
  It must be an explicit allowlisted path with a server-side friendship check - never a relaxation of the tools-never-take-a-user-parameter rule.
