# Multi-tenancy is one shared DB with user_id on every row

When Idaten went multi-user, tenancy became a shared-schema, row-based design: one SQLite database, `user_id` on every data table, and composite primary keys where the row is naturally keyed per user - `(user_id, date)` for daily rows, `(user_id, key)` for settings.
The `User` row is the tenant identity.
This is the industry-standard multi-tenancy pattern (shared schema, tenant column), correctly sized for a household instance.
Legacy single-user data was migrated by `_migrate_multiuser()` in db.py: SQLite can't ALTER a PK, so PK-changed tables were rebuilt and existing rows assigned to user 1, rehearsed on a live-DB copy before deploying.

## Considered Options

- **One SQLite file per user** - rejected: physical isolation, but every cross-user surface fragments - the admin page aggregates usage and feedback across members, the scheduler loops all connected users, membership/invites are inherently shared - plus N engines, N migration runs, N backups.
- **Schema-per-tenant** - rejected: a Postgres-flavored answer; SQLite has no real schema namespaces, and it inherits the same cross-tenant-query pain.
- **Separate deployment per user** - rejected: the household is one operator running one instance; instance settings (ADR 0003) depend on that shape.
- **Shared schema with user_id column** - chosen.

A note on PK style: many codebases would use a surrogate `id` PK plus `UNIQUE (user_id, date)`.
Same guarantee; the composite PK makes per-user uniqueness the row's identity rather than an annotation, and nothing needs to reference these rows by foreign key.

## Consequences

- Cross-user features are plain queries: admin usage table, feedback summary, scheduler iteration, invites.
- One migration path, one backup, one DB to reason about (compounds with ADR 0007).
- "One plan day per user per date" is a schema fact, not app logic.
- **Isolation is discipline, not structure**: every query must filter by `user_id`, one forgotten filter is a cross-member data leak, and SQLite has no row-level security to backstop it.
  The backstop is `test_tenant_isolation.py`, which is therefore load-bearing, not nice-to-have.
- The named upgrade path when trust boundaries get real (strangers, not household members): Postgres RLS after an ADR 0007 migration - policies enforce `user_id = current_setting('app.current_user_id')` on every query, with the app setting the variable once per transaction.
  That shrinks the surface that must be right from every query to one request hook, the same choke-point move as `make_client` binding `user_id` at construction.
  Short of a DB move, an auto-scoping session layer (SQLAlchemy `with_loader_criteria`) is the in-place version.
- Per-user data export or deletion is a query per table instead of a file copy.
