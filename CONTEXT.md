# Context

Glossary of domain terms for Idaten.
Terms here are canonical: code, UI copy, and docs should use these words with these meanings.

## Terms

### Coach
The LLM-backed training assistant.
It is invoked from five call sites: chat, daily review, plan authoring, execution analysis, and weekly summary.

### Coach call site
The feature that triggered an LLM invocation: `chat`, `review`, `plan`, `execution_analysis`, or `weekly_summary`.
Only `chat` is member-initiated; the others are system-initiated (scheduled or lazy-loaded).
The call site is the trigger ("which door the request came through"), not the output; see Surface for the output dimension.

### Surface
A kind of coach-authored output a human can rate: a review's coach note, an execution analysis, a weekly summary, an edit proposal, or a reported chat session (`chat_session`).
The surface is the artifact ("the thing that came out"), while the call site is the trigger.
The mapping is one-to-many: one call site can produce more than one kind of surface (chat can produce both a session transcript and an edit proposal), so the two terms are distinct and must not be conflated.

### Member
A user account in the household.
The first user is the admin; others are invited members.

### Chat message limit
A per-user cap on user-initiated chat messages to the Coach.
It applies only to the `chat` call site, never to system-initiated call sites.
It counts messages per calendar day in the app timezone and resets at local midnight.
It can be set on any account, including the admin; enforcement is identical for everyone.
"Unlimited" is a valid value.

### Chat message
One user-sent message to the Coach.
This is the unit the chat message limit counts.
One chat message may fan out into several LLM calls inside the agent loop; those do not count individually against the limit.

### LLM call
One request to the LLM provider, recorded as one row of usage.
The admin usage table's "Calls" column counts LLM calls, not chat messages; the two must never be conflated in UI copy.

### Burst guard
The fixed short-window limit on chat messages.
It is an anti-runaway safety mechanism, not policy, and is not admin-configurable.

### Weekly summary
The Coach's retrospective on one completed summary week.
Its UI display name is "Week in review"; the two refer to the same artifact.
Exactly one exists per member per summary week; it is always written, including for a week with no activities.
It is a standalone artifact: it does not belong to any activity or daily review, and neither consumes it.

### Summary week
The fixed window a weekly summary covers: Monday through Sunday in the app timezone, closing at local midnight Sunday.
A week is only summarized after it has closed.

### Instance setting
Operator policy that applies to the whole deployment, every member equally, admin included.
Distinct from a member setting (per-user preference) and from a server-owned member setting like the chat message limit (per-user policy).
The admin is the operator: instance settings are set on the admin page and are invisible to the member-facing settings API.

### Coach call-site toggle
An instance setting that turns one system-initiated coach call site's LLM generation on or off.
Absent means enabled; a toggle never affects deterministic machinery (sync, execution scoring, plan materialization) or the serving of artifacts that already exist.
Re-enabling resumes forward-only: artifacts skipped while off are never backfilled.
In v1 the toggleable call sites are `weekly_summary` and `execution_analysis`; the daily review is deliberately not toggleable.
The nightly QA scoring job (`qa`) is toggleable through the same mechanism.
