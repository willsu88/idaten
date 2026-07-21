"""The single-user -> multi-user upgrade: legacy tables (no user_id, date-only
primary keys) must be rebuilt with rows assigned to the first user, losslessly."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import inspect, text

from app.db import Base, engine, init_db
from app.models import DailyHealth, DayIntent, PlanDay, Setting

TODAY = dt.date.today()

LEGACY_DDL = {
    "daily_health": (
        "CREATE TABLE daily_health (date DATE PRIMARY KEY, sleep_seconds FLOAT, "
        "sleep_score FLOAT, hrv FLOAT, hrv_baseline FLOAT, resting_hr FLOAT, "
        "body_battery FLOAT, stress_avg FLOAT, vo2max FLOAT, race_predictions JSON)"
    ),
    "plan_days": (
        "CREATE TABLE plan_days (date DATE PRIMARY KEY, workout_type VARCHAR, "
        "title VARCHAR, description TEXT, duration_min FLOAT, distance_km FLOAT, "
        "target_pace VARCHAR, rationale TEXT, status VARCHAR, version_id INTEGER, "
        "garmin_workout_id VARCHAR, pushed_at DATETIME)"
    ),
    "day_intents": (
        "CREATE TABLE day_intents (date DATE PRIMARY KEY, sport VARCHAR, note TEXT, "
        "duration_min FLOAT, effort VARCHAR, source VARCHAR)"
    ),
    "settings": "CREATE TABLE settings (key VARCHAR PRIMARY KEY, value JSON)",
}


def test_legacy_single_user_db_upgrades(db):
    db.close()
    # Recreate the four PK-changing tables in their legacy shape, with data
    with engine.begin() as conn:
        for name, ddl in LEGACY_DDL.items():
            conn.execute(text(f"DROP TABLE {name}"))
            conn.execute(text(ddl))
        conn.execute(text(
            f"INSERT INTO daily_health (date, hrv, resting_hr) VALUES ('{TODAY}', 62.0, 48.0)"
        ))
        conn.execute(text(
            f"INSERT INTO plan_days (date, workout_type, title, status) "
            f"VALUES ('{TODAY}', 'tempo', 'Tempo', 'planned')"
        ))
        conn.execute(text(
            f"INSERT INTO day_intents (date, sport, source) VALUES ('{TODAY}', 'surfing', 'chat')"
        ))
        conn.execute(text(
            'INSERT INTO settings (key, value) VALUES (\'athlete\', \'{"age": 30}\')'
        ))
        # Legacy activities table: user_id column absent entirely
        conn.execute(text("DROP TABLE activities"))
        conn.execute(text(
            "CREATE TABLE activities (id INTEGER PRIMARY KEY, date DATE, type VARCHAR, "
            "name VARCHAR, distance_m FLOAT)"
        ))
        conn.execute(text(
            f"INSERT INTO activities (id, date, type, distance_m) "
            f"VALUES (42, '{TODAY}', 'running', 10000)"
        ))

    init_db()  # runs _auto_migrate + _migrate_multiuser

    from app.db import SessionLocal

    s = SessionLocal()
    try:
        # Composite PKs in place, rows preserved and owned by user 1
        assert inspect(engine).get_pk_constraint("daily_health")["constrained_columns"] == [
            "user_id", "date"]
        h = s.get(DailyHealth, (1, TODAY))
        assert h is not None and h.hrv == 62.0 and h.resting_hr == 48.0
        p = s.get(PlanDay, (1, TODAY))
        assert p is not None and p.title == "Tempo"
        i = s.get(DayIntent, (1, TODAY))
        assert i is not None and i.sport == "surfing"
        st = s.get(Setting, (1, "athlete"))
        assert st is not None and st.value == {"age": 30}

        row = s.execute(text("SELECT user_id, distance_m FROM activities WHERE id=42")).one()
        assert row.user_id == 1 and row.distance_m == 10000

        # No leftover rebuild scratch tables
        names = set(inspect(engine).get_table_names())
        assert not any(n.endswith("__old") for n in names)
    finally:
        s.close()


def test_migration_idempotent_on_current_schema(db):
    db.close()
    before = {t: inspect(engine).get_columns(t) for t in inspect(engine).get_table_names()}
    init_db()
    init_db()
    after = {t: inspect(engine).get_columns(t) for t in inspect(engine).get_table_names()}
    assert {t: [c["name"] for c in cols] for t, cols in before.items()} == \
           {t: [c["name"] for c in cols] for t, cols in after.items()}
