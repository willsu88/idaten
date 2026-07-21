"""API wiring for feature 2 (mode label) + feature 3 (revert-to-Garmin):
the today/week payloads expose mode + revertible, and the endpoint reverts."""

from __future__ import annotations

import datetime as dt

from app.models import PlanVersion, TrainingPlan
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


def _accept_edit(db, user_id, date):
    from app.models import PlanDay
    override = PlanVersion(user_id=user_id, source="chat_edit", summary="ease off")
    db.add(override)
    db.flush()
    day = db.get(PlanDay, (user_id, date))
    day.workout_type = "easy_run"
    day.title = "Easy run"
    day.rationale = "eased off"
    day.version_id = override.id
    db.commit()


def test_today_reports_editor_mode(client, db, user):
    _active_plan(db, user.id)
    materialize_coach_plan(db, user.id, TODAY)
    _login(client)
    body = client.get("/api/dashboard/today").json()
    assert body["mode"] == "editor"
    assert body["workout"]["revertible"] is False  # untouched Garmin base


def test_today_marks_edited_day_revertible(client, db, user):
    _active_plan(db, user.id)
    materialize_coach_plan(db, user.id, TODAY)
    _accept_edit(db, user.id, TODAY)
    _login(client)
    body = client.get("/api/dashboard/today").json()
    assert body["workout"]["revertible"] is True


def test_week_reports_mode_and_revertible(client, db, user):
    _active_plan(db, user.id)
    materialize_coach_plan(db, user.id, TODAY)
    _accept_edit(db, user.id, TODAY)
    _login(client)
    body = client.get("/api/plan/week").json()
    assert body["mode"] == "editor"
    today_row = next(d for d in body["days"] if d["date"] == TODAY.isoformat())
    assert today_row["revertible"] is True


def test_revert_endpoint_restores_day(client, db, user):
    _active_plan(db, user.id)
    materialize_coach_plan(db, user.id, TODAY)
    _accept_edit(db, user.id, TODAY)
    _login(client)
    r = client.post("/api/dashboard/revert-to-garmin",
                    json={"scope": "day", "date": TODAY.isoformat()})
    assert r.status_code == 200
    assert r.json()["reverted"] == [TODAY.isoformat()]
    from app.models import PlanDay
    assert db.get(PlanDay, (user.id, TODAY)).title == "Threshold"


def test_revert_week_scope_reverts_edited_days(client, db, user):
    _active_plan(db, user.id)
    materialize_coach_plan(db, user.id, TODAY)
    _accept_edit(db, user.id, TODAY)
    _login(client)
    r = client.post("/api/dashboard/revert-to-garmin", json={"scope": "week"})
    assert r.status_code == 200
    assert TODAY.isoformat() in r.json()["reverted"]


def test_revert_rejected_in_author_mode(client, db, user):
    # No Garmin plan -> author mode -> revert is a 400.
    _login(client)
    r = client.post("/api/dashboard/revert-to-garmin",
                    json={"scope": "day", "date": TODAY.isoformat()})
    assert r.status_code == 400
