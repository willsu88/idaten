"""GET /api/plan/day — single plan day for the preview/detail page.

Same PlanDay shape as /plan/week days[], plus this date's mode + intent;
`day` is null when nothing is materialized for the date."""

from __future__ import annotations

import datetime as dt

from app.models import DayIntent, PlanDay, PlanVersion, TrainingPlan
from app.planner import materialize_coach_plan

TODAY = dt.date.today()

TASKS = [
    {"date": TODAY.isoformat(), "week": 8, "name": "Threshold",
     "training_effect": "LACTATE_THRESHOLD", "rest_day": False,
     "duration_min": 38, "description": "18:00@172bpm"},
]


def _login(client):
    assert client.post("/api/auth/login",
                       json={"username": "will", "password": "secret1"}).status_code == 200


def _active_plan(db, user_id):
    db.add(TrainingPlan(
        user_id=user_id, garmin_plan_id=1, name="SUPERACE",
        start_date=TODAY - dt.timedelta(days=50), end_date=TODAY + dt.timedelta(days=100),
        duration_weeks=25, phases=[], upcoming_tasks=TASKS,
    ))
    db.commit()


def test_returns_the_day_with_mode(client, db, user):
    _active_plan(db, user.id)
    materialize_coach_plan(db, user.id, TODAY)
    _login(client)
    res = client.get(f"/api/plan/day?date={TODAY.isoformat()}")
    assert res.status_code == 200
    body = res.json()
    assert body["mode"] == "editor"
    assert body["day"]["date"] == TODAY.isoformat()
    # Same shape as week days[] — steps + revertible present.
    assert "steps" in body["day"]
    assert body["day"]["revertible"] is False  # untouched Garmin base
    assert body["intent"] is None
    assert "hr_zones" in body  # present (may be null when no LTHR/zones yet)


def test_edited_day_is_revertible(client, db, user):
    _active_plan(db, user.id)
    materialize_coach_plan(db, user.id, TODAY)
    override = PlanVersion(user_id=user.id, source="chat_edit", summary="ease off")
    db.add(override)
    db.flush()
    day = db.get(PlanDay, (user.id, TODAY))
    day.workout_type = "easy_run"
    day.title = "Easy run"
    day.version_id = override.id
    db.commit()
    _login(client)
    body = client.get(f"/api/plan/day?date={TODAY.isoformat()}").json()
    assert body["day"]["revertible"] is True


def test_null_day_when_nothing_planned(client, db, user):
    _login(client)
    future = (TODAY + dt.timedelta(days=400)).isoformat()
    body = client.get(f"/api/plan/day?date={future}").json()
    assert body["day"] is None
    assert body["intent"] is None


def test_intent_is_returned(client, db, user):
    db.add(DayIntent(user_id=user.id, date=TODAY, sport="surfing"))
    db.commit()
    _login(client)
    body = client.get(f"/api/plan/day?date={TODAY.isoformat()}").json()
    assert body["intent"] is not None
    assert body["intent"]["sport"] == "surfing"


def test_malformed_date_is_422(client, db, user):
    _login(client)
    assert client.get("/api/plan/day?date=not-a-date").status_code == 422
