---
title: Per-call-site coach toggles, admin-configurable (cost control)
labels: [design-open]
status: open
---

## Problem Statement

The chat call site has a cost lever (the per-user daily chat message limit), and the admin page shows cost per call site via `llm_usage`.
But the system-initiated Coach call sites - daily review, execution analysis, and the new weekly summary - have no off switch at all.
Every member gets every artifact, so the household's fixed LLM floor grows with each new call site and the admin can see the cost but cannot act on it.

## Solution

Give the admin per-member toggles that turn individual system-initiated coach artifacts on or off: weekly summary, execution analysis narrative, and (pending the open decision below) the daily review note.
Toggles live on the admin page next to the chat message limit and follow its conventions: admin-set, enforcement identical for everyone including the admin, defaults preserve current behavior (everything on).
A toggle governs LLM generation only, never deterministic machinery.

## Open decision (blocks ready-for-agent)

Is the daily review toggleable at all in v1?
Unlike the other two artifacts, the daily review is load-bearing: it carries plan proposals, triggers the Garmin plan refresh, and anchors the Today page.
Options: (a) not toggleable in v1 - ship toggles for weekly summary and execution analysis only; (b) toggleable, but only the coach_note narrative is suppressed while proposals and plan refresh still run; (c) fully toggleable, accepting that proposals stop too.
Recommendation: (a) for v1 - it keeps the ticket small and defers the hard question until the cheaper levers prove insufficient.

## Implementation Decisions (leanings, to confirm at spec time)

- Storage: server-owned per-user Setting keys excluded from the member-facing settings API, same pattern as the chat daily cap.
- Enforcement at the generation seam: the scheduler job and the lazy endpoints check one settings read per call site; a disabled call site generates nothing and the endpoint reports the artifact as absent.
- Execution SCORING is unaffected (non-LLM, computed at sync); only the lazy analysis narrative is suppressed.
- Sync, plan materialization, and readiness ingestion are never affected by any toggle.
- Disabled weekly summaries leave permanent gaps in the Week page history: no backfill on re-enable, same rule as pre-launch weeks.
- UI: hide the artifact's card entirely when disabled rather than showing a "turned off by admin" state (to confirm).
- Frontend admin surface: toggle controls in the "By member" area of the admin page, near the chat cap column.

## Alternatives to weigh before building

Model routing may be the better cost lever: every call site currently pays the global Opus rate, and routing cheap call sites (execution analysis, edit summaries) to a smaller model could save more than turning features off - see the Idea B architecture findings in ROADMAP.md.
Decide which to build first; they compose, but routing may make this ticket unnecessary for a while.

## Related

- ROADMAP.md Idea G points here.
- Weekly summary feature (CONTEXT.md, docs/adr/0002) is being built with its enabled-flag read through a single settings check, so this ticket lands as a settings row + UI, not a refactor.
- Prior art: `.scratch/coach-chat-cap/spec.md` (the chat message limit) for storage, enforcement, and admin-UI conventions.
