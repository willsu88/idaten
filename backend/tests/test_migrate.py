from __future__ import annotations

from sqlalchemy import inspect, text

from app.db import Base, _auto_migrate, engine


def test_auto_migrate_adds_missing_columns(db):
    db.close()
    # Simulate an old database: races table without the goal_time column
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE races"))
        conn.execute(text(
            "CREATE TABLE races (id INTEGER PRIMARY KEY, name VARCHAR, date DATE, "
            "distance_km FLOAT)"
        ))
        conn.execute(text(
            "INSERT INTO races (name, date, distance_km) VALUES ('Old', '2026-11-14', 21.1)"
        ))

    _auto_migrate()

    cols = {c["name"] for c in inspect(engine).get_columns("races")}
    model_cols = {c.name for c in Base.metadata.tables["races"].columns}
    assert model_cols <= cols
    with engine.connect() as conn:
        row = conn.execute(text("SELECT name, distance_km FROM races")).one()
    assert row.name == "Old" and row.distance_km == 21.1


def test_auto_migrate_idempotent(db):
    db.close()
    _auto_migrate()
    _auto_migrate()


def test_rename_migrates_scored_prescription_with_data(db):
    from app.db import _migrate_renames

    db.close()
    # Simulate a pre-ADR-0026 database: the column under its old name, with data.
    with engine.begin() as conn:
        conn.execute(text(
            'ALTER TABLE activities RENAME COLUMN "attempted_prescription" '
            'TO "scored_prescription"'))
        conn.execute(text(
            "INSERT INTO activities (id, user_id, date, type, name, raw, enriched, "
            "scored_prescription) VALUES (1, 1, '2026-07-16', 'running', 'run', "
            "'{}', 1, '{\"title\": \"Easy\"}')"))

    _migrate_renames()
    _auto_migrate()  # must NOT re-add an empty column beside the renamed one

    cols = {c["name"] for c in inspect(engine).get_columns("activities")}
    assert "attempted_prescription" in cols and "scored_prescription" not in cols
    with engine.connect() as conn:
        row = conn.execute(text(
            "SELECT attempted_prescription FROM activities WHERE id = 1")).one()
    assert "Easy" in row.attempted_prescription

    _migrate_renames()  # idempotent
