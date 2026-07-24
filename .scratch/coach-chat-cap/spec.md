---
title: Per-user daily chat message limit, configurable from the admin page
labels: [ready-for-agent]
status: open
---

## Problem Statement

The household admin can see each member's Coach usage and cost on the admin page, but has no way to act on it.
The only chat quota is hardcoded (15 messages per rolling 24 hours for non-admins), invisible in the UI, and resets whenever the server restarts.
An admin who sees a member running up cost has no knob to turn.

## Solution

Give every account a daily chat message limit that the admin can view and edit inline in the admin page's "By member" usage table.
The limit counts user-sent chat messages per calendar day in the app timezone, resets at local midnight, and applies only to the `chat` call site - never to system-initiated Coach features (daily review, plan authoring, execution analysis) and never to the internal LLM calls a single message fans out into.
Members see a quiet warning when they are nearly out of messages and a friendly blocked state when they hit the cap.

## User Stories

1. As an admin, I want to see how many chat messages each account has used today next to its cap, so that I can tell at a glance who is near their limit.
2. As an admin, I want to edit any account's daily cap inline in the "By member" table, so that I can act immediately on the usage evidence in front of me.
3. As an admin, I want the UI to state that the limit applies to chat messages only, so that I do not expect it to throttle daily reviews or plan generation.
4. As an admin, I want to set a cap of "unlimited" for a trusted account, so that I can exempt someone without deleting the feature.
5. As an admin, I want to set a cap of 0, so that I can effectively mute an account's chat access without removing the member.
6. As an admin, I want new accounts (and my own) to default to 8 messages per day, so that spend is bounded without any setup.
7. As an admin, I want the cap to survive server restarts, so that a redeploy does not silently reset everyone's daily count.
8. As an admin, I want the "Msgs today" number, the enforcement, and the member's remaining count to always agree, so that I never have to reconcile conflicting numbers.
9. As a member, I want chat to behave completely normally while I have plenty of messages left, so that the Coach does not feel metered.
10. As a member, I want a quiet hint when I have about 2 messages left today, so that I can save them for what matters.
11. As a member, I want a clear, friendly message when I hit my cap that tells me it resets at midnight, so that I know it is temporary and not an error.
12. As a member, I want my daily count to be based on messages I actually sent, so that a message rejected before processing does not burn my quota.
13. As a member, I want the agent's internal tool-use turns to never count against my limit, so that a complex question costs the same one message as a simple one.
14. As a member, I want my scheduled daily coach note and run analysis to keep working even when I have used all my chat messages, so that the app does not degrade.
15. As a member, I must not be able to raise my own cap through any member-facing settings API, so that the limit is actually enforced.
16. As an admin, I want lowering a cap below today's already-used count to simply block further messages until midnight, so that there is no retroactive weirdness.
17. As an admin who capped my own account, I want to be blocked exactly like a member when I hit my cap, so that behavior is predictable - and I can always raise my cap from the admin page since that does not go through the Coach.

## Implementation Decisions

- The unit of the limit is the chat message (one user-sent message), per the glossary in CONTEXT.md. The admin usage table's existing "Calls" column counts LLM calls; the new columns count chat messages. UI copy must never conflate the two.
- Window: calendar day in the app timezone, computed from UTC `created_at` timestamps. The existing rolling-24-hour semantics are replaced.
- The hardcoded 5-messages-per-5-minutes burst guard stays as-is: in-memory, not configurable, enforced independently of the daily cap.
- Source of truth for "messages used today" is the persisted chat messages table (user-role rows for the current local day). Enforcement, the admin display, and the member-facing remaining count all read this one source. There is no chat-delete endpoint, so there is no reset loophole.
- The current admin exemption from the daily quota is removed: everyone is cappable, everyone defaults to 8 per day, and enforcement is identical for all accounts.
- Cap storage: the existing per-user Setting store, as a server-owned key excluded from the member-facing settings API (like `garmin_profile`). Value semantics: null/absent = default (8), explicit "unlimited" sentinel allowed, 0 = chat disabled.
- Enforcement stays at the existing checkpoint on the chat POST endpoint, before any LLM spend. The check reads the configurable cap instead of the constant. On block: 429 with a body carrying the reset boundary so the frontend can render "resets at midnight".
- Admin usage endpoint: each `by_user` row gains `msgs_today` and `chat_daily_cap`.
- One new admin-only endpoint to set an account's cap (accepting an integer, 0, or the unlimited sentinel).
- Member quota visibility: the existing chat history/session response gains a `quota: {used, cap}` field; the frontend shows a low-quota hint at <= 2 remaining and a blocked composer state at 0. No always-visible counter.
- Admin UI: two columns appended to the "By member" table - "Msgs today" rendered as `used/cap`, and an editable "Daily cap" (click to edit; unlimited representable). The table's caption or header notes the limit applies to chat messages only.

## Testing Decisions

- Test external behavior at the HTTP seams via the existing TestClient fixture in conftest; do not test the counting internals directly.
- Chat POST: N messages succeed, message N+1 returns 429 with reset info; a message on the next local day succeeds; burst guard still fires independently of the daily cap; a request rejected before processing does not consume quota.
- Admin usage GET: `by_user` rows carry correct `msgs_today` and `chat_daily_cap`; counts reflect chat messages, not LLM calls.
- Set-cap endpoint: admin can set integer/0/unlimited; non-admin gets 403; member-facing settings API cannot read or write the cap key.
- Quota field: chat history/session response reports `{used, cap}` consistent with what enforcement would do next.
- Prior art: rate-limit behavior tests in test_phase7, auth/permission tests in test_auth, chat concurrency tests in test_chat_race.
- Frontend has no test infrastructure (parked separately); admin table and composer states are verified manually end-to-end.

## Out of Scope

- Limits or budgets on system-initiated call sites (review, plan, execution analysis).
- Cost-based (USD) budgets per member.
- Making the burst guard configurable.
- Notifying members proactively (email/push) about quota state.
- Frontend test infrastructure.

## Further Notes

- Ship-day behavior change: members drop from 15/day to 8/day, and the admin loses the exemption (unlimited to 8/day). This was an explicit decision; the admin can raise any cap, including their own, from the admin page.
- Glossary terms introduced during design (chat message limit, chat message vs LLM call, burst guard, Coach call site) live in CONTEXT.md at the repo root.
- No ADR: the decisions are cheap to reverse and fail the ADR bar.
