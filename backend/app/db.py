from __future__ import annotations

import os

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import config


class Base(DeclarativeBase):
    pass


os.makedirs(os.path.dirname(config.db_path) or ".", exist_ok=True)
engine = create_engine(
    f"sqlite:///{config.db_path}",
    # `timeout` = sqlite3 busy timeout: writers wait for the lock instead of
    # instantly raising "database is locked" when another thread is mid-write.
    connect_args={"check_same_thread": False, "timeout": 30},
)


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_conn, _record):
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")   # readers don't block the writer
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.close()


SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db() -> None:
    from . import models  # noqa: F401  (register tables)

    Base.metadata.create_all(engine)
    _auto_migrate()
    _migrate_multiuser()


def _auto_migrate() -> None:
    """Add any ORM columns missing from existing SQLite tables.

    create_all only creates missing *tables*; when a model gains a column,
    existing databases need ALTER TABLE. Additive-only; primary-key changes
    are handled by the table rebuild in `_migrate_multiuser`.
    """
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            existing = {c["name"] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing:
                    continue
                coltype = column.type.compile(engine.dialect)
                conn.execute(
                    text(f'ALTER TABLE {table.name} ADD COLUMN "{column.name}" {coltype}')
                )


LEGACY_USER_ID = 1  # pre-multi-user rows all belong to the first (bootstrap) user


def _migrate_multiuser() -> None:
    """One-time upgrade of a single-user database to the multi-user schema.

    SQLite can't ALTER a primary key, so tables whose PK gained user_id
    (daily_health, plan_days, day_intents, settings) are rebuilt: rename old,
    create from the model, copy rows with user_id backfilled, drop old.
    Everything else just gets its NULL user_id values set to the first user.
    Idempotent — a matching schema is a no-op.
    """
    from sqlalchemy import inspect, text

    for table in Base.metadata.sorted_tables:
        existing_pk = inspect(engine).get_pk_constraint(table.name)["constrained_columns"]
        model_pk = [c.name for c in table.primary_key.columns]
        if existing_pk != model_pk:
            _rebuild_table(table)

    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if "user_id" in table.columns and table.name != "auth_sessions":
                conn.execute(text(
                    f'UPDATE "{table.name}" SET user_id = {LEGACY_USER_ID} WHERE user_id IS NULL'
                ))


def _rebuild_table(table) -> None:
    from sqlalchemy import inspect, text

    def source_expr(column, in_old: bool) -> str:
        if column.name == "user_id":
            return f'COALESCE("user_id", {LEGACY_USER_ID})' if in_old else str(LEGACY_USER_ID)
        # Legacy rows may hold NULL where the model now says NOT NULL; fall back
        # to the model's scalar default so the copy can't violate constraints.
        default = getattr(column.default, "arg", None)
        if not column.nullable and isinstance(default, (str, int, float, bool)):
            literal = f"'{default}'" if isinstance(default, str) else str(int(default))
            return f'COALESCE("{column.name}", {literal})'
        return f'"{column.name}"'

    old_name = f"{table.name}__old"
    with engine.begin() as conn:
        conn.execute(text(f'ALTER TABLE "{table.name}" RENAME TO "{old_name}"'))
    table.create(engine)
    with engine.begin() as conn:
        old_cols = {c["name"] for c in inspect(engine).get_columns(old_name)}
        shared = [c for c in table.columns if c.name in old_cols or c.name == "user_id"]
        targets = ", ".join(f'"{c.name}"' for c in shared)
        sources = ", ".join(source_expr(c, c.name in old_cols) for c in shared)
        conn.execute(text(
            f'INSERT INTO "{table.name}" ({targets}) SELECT {sources} FROM "{old_name}"'
        ))
        conn.execute(text(f'DROP TABLE "{old_name}"'))


def get_db():
    """FastAPI dependency."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def session() -> Session:
    """For background jobs (caller closes)."""
    return SessionLocal()
