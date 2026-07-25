---
title: Instance-level coach call-site toggles (operator control)
labels: [done]
status: closed
---

## Problem Statement (revised at grilling, 2026-07-25)

The original framing was household cost control, and the data killed it: all-time LLM spend at review time was $0.20 total (~$1/month extrapolated floor for 2 members).
The real driver is the open-source route: someone self-hosting this code should decide which system-initiated coach features their instance runs and pays for.
The admin IS the operator, so the control lives on the admin page.

## Decisions (grilling session 2026-07-25)

1. Build it, reframed: an operator/deployment control, not a household cost lever.
2. Instance-level granularity: one toggle per call site, applying to every member equally (docs/adr/0003).
   Per-member is deferred until a real household need appears; the enforcement seam is identical if it ever does.
3. V1 scope: weekly summary and the execution-analysis narrative only (the original ticket's option a).
   The daily review stays always-on; it is load-bearing (plan proposals, Garmin plan refresh, Today page anchor) and its toggle question is deferred.
4. Storage: a new `instance_settings` table (key, value JSON) read through `app/instance_settings.py`; admin toggles it at runtime, no restart.
5. Disabled UX: hide + no backfill.
   The endpoint reports the artifact absent, the card does not render, re-enable resumes forward-only, and weeks skipped while off stay permanent gaps (same rule as pre-launch weeks).
6. Defaults: everything on (absent = enabled), so existing deployments see no change.

## What shipped

- `instance_settings` table + module: `call_site_enabled` / `set_call_site_enabled` / `coach_toggles`, absent = enabled, falsy stored value = disabled.
- `weekly.summaries_enabled(db)` retargeted from the per-user Setting seam to the instance toggle; scheduler `_weekly_done` treats disabled as done.
- `POST /api/activities/{id}/analysis` returns `{analysis: null, coach: null}` while disabled and nothing is cached; a cached narrative is always served.
- Admin endpoints: `GET`/`PUT /api/auth/coach_toggles` (partial PUT, admin-only).
- Admin page: "Coach features" switch row in the LLM card; member UI needed no change (both cards already hide on absence).

## Invariants held

- A toggle governs LLM generation only, never deterministic machinery: execution scoring, sync, plan materialization, and readiness ingestion are untouched.
- Enforcement is one settings read at each call site's generation choke point, at generation time; a mid-week flip affects whatever generates next.
- The toggles are invisible to `GET`/`PUT /api/settings`.

## Deferred

- Daily review toggle (options b/c in the original ticket).
- Per-member overrides layered on the instance switch.
- Model routing (the other cost lever, ROADMAP Idea B findings); it composes with this and `instance_settings` is its natural config home.
