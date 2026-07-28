# Ticket index

One line per ticket, grouped by status.
When a ticket is added or re-scoped, update its line here in the same change.
When a ticket ships, delete its directory and its line - shipped history lives in git log only.
Statuses mirror the `Status:` line inside each ticket; the ticket file is the source of truth.

## Ready to build

- [open-source-preflight](open-source-preflight/ticket.md) - remaining checklist before the repo goes public; most gates already resolved.
- [vps-migration](vps-migration/ticket.md) - move the app off the Mac onto a VPS; full runbook including secrets/backup handling.
- [ramp-coach-evals](ramp-coach-evals/ticket.md) - layer 3-4 eval cases protecting the coach's ramp-guardrail behavior.
- [ci-test-workflow](ci-test-workflow/ticket.md) - test-only GitHub Actions workflow (commit hygiene, not the deploy gate); needs grilling.

## Ideas (need a spec or a discussion first)

- [author-mode-edit-pins](author-mode-edit-pins/ticket.md) - author mode can silently overwrite chat edits the athlete already approved; needs a source-aware guard.
- [model-routing](model-routing/ticket.md) - per-call-site model choice on the LLM seam; route cheap passes to a smaller model.
- [plan-day-structure](plan-day-structure/ticket.md) - opt-in "structure this run for me" on Garmin days, plus plan-day page follow-ups.
- [hill-workouts](hill-workouts/ticket.md) - hill sessions as a workout type; watch can't enforce elevation, so text-instruction intervals.
- [voice-mode](voice-mode/ticket.md) - talk to the coach via a cascaded ASR -> text coach -> TTS pipeline; coach internals untouched.
- [friends-workout-sharing](friends-workout-sharing/ticket.md) - friends list + send a workout to a friend, via UI and a chat tool.
- [execution-score-followups](execution-score-followups/ticket.md) - execution-score nice-to-haves: tier-2 shape-match attribution, trends chart, live eyeball.

## Parked (explicit revival triggers or prerequisites)

- [risk-tiered-autonomy](risk-tiered-autonomy/ticket.md) - auto-apply low-risk plan edits with undo, keep approval for high-stakes ones; unblocked now that QA scorecards shipped.
- [athlete-memory](athlete-memory/ticket.md) - retrieval over full training history so the coach proactively cites precedent.
- [intent-discovery](intent-discovery/ticket.md) - batch-mine chat history for intents the coach handled badly; a backlog from real usage.
- [byob-user-keys](byob-user-keys/ticket.md) - per-user LLM API keys with instance-key fallback; phase 2 of the open-source route.
- [web-push](web-push/ticket.md) - push the morning coach note; killed by eager generation, revive only if notes get missed in practice.
- [strength-phase-3](strength-phase-3/ticket.md) - strength push-to-watch + structured sets/reps content; only if wanted.
- [garmin-use-upstream-wrappers](garmin-use-upstream-wrappers/ticket.md) - swap two raw Garmin calls for upstream `garminconnect` wrappers; ~30 min cleanup.
- [simulated-athlete](simulated-athlete/ticket.md) - persona-driven simulated athletes for coach regression testing; the QA rubric it grades with now exists.
- [agent-eval-library](agent-eval-library/ticket.md) - extract the eval harness as a library; parked until a second consumer repo exists.
