"""GET /api/plan/week `summary` — the week's load in the plan's own
time-at-intensity currency (planned/done minutes, Z1+Z2 easy share) with
completed-run km as an actuals-only footnote."""

from __future__ import annotations

import datetime as dt

from app.models import Activity, PlanDay

MONDAY = dt.date.today() - dt.timedelta(days=dt.date.today().weekday())


def _login(client):
    assert client.post("/api/auth/login",
                       json={"username": "will", "password": "secret1"}).status_code == 200


def _seed(db, uid):
    # Plan: two run days (40 + 60 min) and a rest day (never counts).
    db.add(PlanDay(user_id=uid, date=MONDAY, workout_type="easy_run",
                   title="Easy", duration_min=40, status="completed"))
    db.add(PlanDay(user_id=uid, date=MONDAY + dt.timedelta(days=2),
                   workout_type="threshold", title="Threshold", duration_min=60))
    db.add(PlanDay(user_id=uid, date=MONDAY + dt.timedelta(days=1),
                   workout_type="rest", title="Rest", duration_min=30))
    # Actuals: a 45-min 8 km run (30 min easy / 15 hard) + 30 min of cycling
    # (counts toward time, never toward run km).
    db.add(Activity(id=1, user_id=uid, date=MONDAY, type="running", name="Run",
                    distance_m=8000, duration_s=2700,
                    time_in_zones={"z1": 600, "z2": 1200, "z3": 900}))
    db.add(Activity(id=2, user_id=uid, date=MONDAY + dt.timedelta(days=1),
                    type="cycling", name="Ride", distance_m=15000, duration_s=1800))
    db.commit()


def test_summary_aggregates_the_week(client, db, user):
    _seed(db, user.id)
    _login(client)
    res = client.get(f"/api/plan/week?start={MONDAY.isoformat()}")
    assert res.status_code == 200
    s = res.json()["summary"]
    assert s["planned_min"] == 100      # 40 + 60; rest day excluded
    assert s["done_min"] == 75          # 45 run + 30 ride
    assert s["run_km"] == 8.0           # runs only, never the ride
    assert s["easy_pct"] == 67          # (600+1200)/2700 of zone time


def test_summary_empty_week(client, db, user):
    _login(client)
    res = client.get(f"/api/plan/week?start={MONDAY.isoformat()}")
    assert res.status_code == 200
    s = res.json()["summary"]
    assert s == {"planned_min": None, "done_min": 0, "run_km": None,
                 "easy_pct": None, "strength": None}
