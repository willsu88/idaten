# Context

Glossary of domain terms for Idaten.
Terms here are canonical: code, UI copy, and docs should use these words with these meanings.

## Terms

### Coach
The LLM-backed training assistant.
It is invoked from four call sites: chat, daily review, plan authoring, and execution analysis.

### Coach call site
The feature that triggered an LLM invocation: `chat`, `review`, `plan`, or `execution_analysis`.
Only `chat` is member-initiated; the other three are system-initiated (scheduled or lazy-loaded).

### Member
A user account in the household.
The first user is the admin; others are invited members.

### Chat message limit
A per-user cap on user-initiated chat messages to the Coach.
It applies only to the `chat` call site, never to system-initiated call sites.
It counts messages per calendar day in the app timezone and resets at local midnight.
It can be set on any account, including the admin; enforcement is identical for everyone.
"Unlimited" is a valid value.
The admin dashboard must state explicitly that the limit covers chat only.

### Chat message
One user-sent message to the Coach.
This is the unit the chat message limit counts.
One chat message may fan out into several LLM calls inside the agent loop; those do not count individually against the limit.

### LLM call
One request to the LLM provider, recorded as one row of usage.
The admin usage table's "Calls" column counts LLM calls, not chat messages; the two must never be conflated in UI copy.

### Burst guard
The hardcoded short-window limit on chat messages (currently 5 per 5 minutes).
It is an anti-runaway safety mechanism, not policy, and is not admin-configurable.
