# Coach call-site toggles are instance-level, not per-member

The switches that turn system-initiated coach artifacts (weekly summary, execution-analysis narrative) on or off live in a new `instance_settings` table and apply to every member equally, admin included.
We chose this over the originally ticketed per-member design because the real motivation is the open-source operator - someone self-hosting the code deciding which LLM features their deployment runs and pays for - and that decision is about the instance, not about individual members; live household data ($0.20 all-time spend for 2 members) showed no per-member cost problem to solve.
Per-member overrides can be layered on later without moving the enforcement seam: each call site already reads exactly one enabled-flag at its generation choke point.

## Consequences

- A toggle governs LLM generation only: deterministic machinery (execution scoring, sync, plan materialization) never checks it, artifacts written before a flip stay readable, and re-enabling resumes forward-only with no backfill (weeks skipped while off are permanent gaps, the same rule as pre-launch weeks).
- The daily review deliberately has no toggle in v1: it is load-bearing (plan proposals, Garmin plan refresh, the Today page anchor), so switching it off is a product-degradation decision we deferred - see `.scratch/coach-toggles/spec.md`.
- `instance_settings` is the home for future instance-wide operator policy (e.g. model-routing config), keeping the per-user `settings` table free of deployment concerns.
