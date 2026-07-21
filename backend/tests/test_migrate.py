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
