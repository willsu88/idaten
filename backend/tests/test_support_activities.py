"""Non-run sessions (strength, yoga, rides…) surfaced as support work:
`support_activities` on /dashboard/today and per-day `support` on /plan/week.
Their load already counts toward CTL/ATL/ramp; these fields make them visible."""

from __future__ import annotations

import datetime as dt

from app.models import Activity, PlanDay

TODAY = dt.date.today()
MONDAY = TODAY - dt.timedelta(days=TODAY.weekday())


def _login(client):
    assert client.post("/api/auth/login",
                       json={"username": "will", "password": "secret1"}).status_code == 200


def test_today_lists_non_run_sessions(client, db, user):
    db.add(Activity(id=1, user_id=user.id, date=TODAY, type="strength_training",
                    name="Strength", duration_s=1920, training_load=35,
                    garmin_rpe=6))
    db.add(Activity(id=2, user_id=user.id, date=TODAY, type="running",
                    name="Morning Run", distance_m=8000, duration_s=2700))
    # Every "…running" variant is a run, never support work.
    db.add(Activity(id=3, user_id=user.id, date=TODAY, type="treadmill_running",
                    name="Treadmill", duration_s=1800))
    db.add(Activity(id=4, user_id=user.id, date=TODAY - dt.timedelta(days=1),
                    type="yoga", name="Yoga"))  # yesterday — not today's card
    db.commit()
    _login(client)

    support = client.get("/api/dashboard/today").json()["support_activities"]
    assert [s["id"] for s in support] == [1]
    s = support[0]
    assert s["type"] == "strength_training"
    assert s["duration_min"] == 32.0
    assert s["training_load"] == 35
    assert s["rpe"] == 6  # falls back to the Garmin-logged RPE


def test_today_support_empty_without_sessions(client, db, user):
    db.add(Activity(id=1, user_id=user.id, date=TODAY, type="running",
                    name="Run", duration_s=1800))
    db.commit()
    _login(client)
    assert client.get("/api/dashboard/today").json()["support_activities"] == []


def test_week_days_carry_support_sessions(client, db, user):
    db.add(PlanDay(user_id=user.id, date=MONDAY, workout_type="easy_run",
                   title="Easy", duration_min=40))
    db.add(PlanDay(user_id=user.id, date=MONDAY + dt.timedelta(days=1),
                   workout_type="rest", title="Rest"))
    db.add(Activity(id=1, user_id=user.id, date=MONDAY + dt.timedelta(days=1),
                    type="strength_training", name="Strength", duration_s=1800))
    db.add(Activity(id=2, user_id=user.id, date=MONDAY, type="running",
                    name="Run", duration_s=2400))
    db.commit()
    _login(client)

    days = client.get(f"/api/plan/week?start={MONDAY.isoformat()}").json()["days"]
    by_date = {d["date"]: d["support"] for d in days}
    assert by_date[MONDAY.isoformat()] == []
    rest_support = by_date[(MONDAY + dt.timedelta(days=1)).isoformat()]
    assert [s["id"] for s in rest_support] == [1]
    assert rest_support[0]["duration_min"] == 30.0
