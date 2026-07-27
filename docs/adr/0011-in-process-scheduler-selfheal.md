# The daily job runs on an in-process scheduler that self-heals, not cron

The daily job (per user: sync, review/plan, auto-push) runs on an in-process APScheduler `BackgroundScheduler` at the configured local hour - and the design assumes the host is unreliable, because the deployment is a Docker container on a laptop that sleeps.
A catch-up check runs at startup and every 30 minutes: if the plan hour has passed and today's run hasn't happened, the job fires immediately (`scheduler.py`).
Around it: a per-user 180s ensure-cooldown so the Today page's polling can't spawn repeated syncs, a lock so the daily job and backfill never overlap (the single-writer invariant of ADR 0007), and per-user iteration where one failing user never blocks the others.

The principle: **the schedule is a hint; the invariant is "each user has today's artifacts."**
Correctness comes from reconciling toward that invariant, not from the trigger firing at the right instant.
A cron-at-8am design silently skips the day whenever the machine was asleep at 8am, and the product's core artifact - the morning plan and coach note - simply doesn't exist that day.

## Considered Options

- **Host cron / launchd** - rejected: lives outside the container (breaks "docker compose up is the whole deployment") and still misses while the machine sleeps.
- **Celery beat or a broker-backed scheduler** - rejected: a second service plus a message broker to run a once-a-day loop for a household.
- **Cloud cron hitting an endpoint** - rejected: an external dependency in a self-hosted app, and a new auth surface through the tunnel.
- **In-process scheduler + reconciliation catch-up** - chosen: every alternative exists to make the trigger reliable; reconciliation makes trigger reliability unnecessary.

## Consequences

- Zero extra infrastructure; downtime of any cause is healed within 30 minutes of wake.
- The catch-up logic is testable in-process (`test_scheduler_selfheal.py`), no real clocks or cron needed.
- Single-process by construction: no distributed lock, so a second app instance would double-fire the daily job.
  This ADR depends on ADR 0007's one-process invariant; horizontal scaling would need a real job store.
- In-memory state (cooldowns, running flag) resets on restart - acceptable because the DB answers "has today run", but the throttle isn't durable.
- Timezone handling is hand-rolled: SQLite returns naive datetimes, `_as_local` views them as UTC in the household zone - a known bug farm managed by convention and tests.
- A silently-dead scheduler thread has no watchdog; a user notices before the system does.
