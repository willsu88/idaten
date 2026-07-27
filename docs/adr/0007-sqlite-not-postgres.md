# SQLite, not Postgres

The database is a single SQLite file, tuned for the actual deployment shape: one backend process in Docker on a host machine, serving a household.
Its known costs are paid deliberately in `db.py`: WAL mode so readers don't block the writer, a 30s busy timeout so writers wait instead of raising "database is locked", and mutual exclusion between the backfill and the daily job.
When data safety was audited (ROADMAP 2026-07-20), the verdict was that the risk was never SQLite - it was credentials at rest, backup handling, and transport, none of which change with Postgres.

## Considered Options

- **Postgres in docker-compose** - rejected: a second service for a self-hoster to operate, migrate, and back up, purchased with zero concurrent-write need.
  Choosing it here would be convention ("what production uses"), not constraint.
- **Managed cloud DB** - rejected: network latency, cost, and an external dependency in an app whose point is running on your own hardware.
- **SQLite with WAL + busy timeout** - chosen: for an open-source home app, `docker compose up` plus one data directory is the whole deployment, and the DB-as-file is a feature - backups are one file via the SQLite backup API.

## Consequences

- Zero database operations: no server, no pool tuning, no separate backup infra; tests get a fresh temp-file DB each.
- Schema changes are additive by default: `_auto_migrate()` adds missing ORM columns in place, and `_migrate_multiuser()` handled the one PK change with a table rebuild (SQLite can't ALTER a PK), rehearsed on a live-DB copy first.
- The single-writer ceiling is a stated invariant: all writes stay in one process, and the WAL/timeout/job-exclusion mitigations are load-bearing.
- The "database is locked" bug class never fully disappears; one poisoned flush once silently killed every subsequent commit, hence the rule that loop error handlers always `db.rollback()`.
- **Migration out is cheap by construction**: all business logic goes through the SQLAlchemy ORM, so the SQLite-specific surface is confined to `db.py` (engine URL, pragmas, hand-rolled migrations).
  A later Postgres move is: swap the engine URL, replace `_auto_migrate`/`_migrate_multiuser` with Alembic, move the data (pgloader or dump/load), verify JSON and DateTime column behavior.
  Days of careful work, not a rewrite; no call site would notice.
  For an open-source home app, SQLite is enough to spin up - and this exit path is why choosing it now costs little later.
