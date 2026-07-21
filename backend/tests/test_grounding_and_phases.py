"""Pace grounding (profile + guard) and Garmin training-plan mirroring."""

from __future__ import annotations

import datetime as dt

from app import metrics
from app.garmin.training_plan import (
    derived_payload,
    garmin_plan_context,
    plan_payload,
    sync_training_plan,
)
from app.models import Activity, PendingEdit, Race, TrainingPlan
from app.planner import pace_violations
from tests.conftest import make_user

TODAY = dt.date.today()


def _add_run(db, user_id, days_ago, km, pace_s_per_km, type_="running"):
    aid = user_id * 1_000_000 + days_ago * 100 + int(km * 10)
    db.add(Activity(
        id=aid, user_id=user_id, date=TODAY - dt.timedelta(days=days_ago),
        type=type_, distance_m=km * 1000, duration_s=km * pace_s_per_km,
    ))
    db.commit()


# --- pace profile ----------------------------------------------------------

def test_pace_profile_median_and_bounds(db):
    u = make_user(db)
    for i, pace in enumerate([480, 465, 450, 435, 420]):  # 8:00 .. 7:00
        _add_run(db, u.id, days_ago=i + 1, km=5, pace_s_per_km=pace)
    p = metrics.pace_profile(db, u.id, TODAY)
    assert p is not None
    assert p["runs_last_90d"] == 5
    assert p["typical_pace"] == "7:30"          # median 450s
    assert p["fastest_avg_pace"] == "7:00"      # 420s
    assert p["typical_pace_s"] == 450


def test_pace_profile_needs_three_runs_and_ignores_walks(db):
    u = make_user(db)
    _add_run(db, u.id, 1, 5, 450)
    _add_run(db, u.id, 2, 5, 450, type_="walking")
    _add_run(db, u.id, 3, 1.5, 450)  # under 2 km
    assert metrics.pace_profile(db, u.id, TODAY) is None


# --- pace guard --------------------------------------------------------------

PROFILE = {
    "runs_last_90d": 10, "typical_pace": "7:30", "fastest_avg_pace": "6:40",
    "slowest_avg_pace": "8:20", "typical_pace_s": 450, "fastest_avg_pace_s": 400,
}


def test_pace_violations_flags_fast_easy_day():
    days = [{"date": "2026-07-20", "workout_type": "easy_run", "target_pace": "5:30"}]
    assert len(pace_violations(days, PROFILE)) == 1


def test_pace_violations_allows_grounded_paces():
    days = [
        {"date": "2026-07-20", "workout_type": "easy_run", "target_pace": "7:40"},
        {"date": "2026-07-21", "workout_type": "tempo", "target_pace": "6:30"},
        {"date": "2026-07-22", "workout_type": "rest", "target_pace": None},
    ]
    assert pace_violations(days, PROFILE) == []


def test_pace_violations_flags_ungrounded_quality():
    days = [{"date": "2026-07-21", "workout_type": "tempo", "target_pace": "5:20"}]
    assert len(pace_violations(days, PROFILE)) == 1


def test_pace_violations_none_without_profile():
    days = [{"date": "2026-07-20", "workout_type": "easy_run", "target_pace": "4:00"}]
    assert pace_violations(days, None) == []


def test_propose_plan_edit_rejected_by_pace_guard(db):
    from app.chat.tools import dispatch

    u = make_user(db)
    for i in range(4):
        _add_run(db, u.id, days_ago=i + 1, km=5, pace_s_per_km=450)  # 7:30/km
    result, edit = dispatch(db, u.id, "propose_plan_edit", {
        "summary": "s", "rationale": "r",
        "days": [{"date": TODAY.isoformat(), "workout_type": "easy_run",
                  "title": "Easy", "description": "", "rationale": "r",
                  "target_pace": "5:30"}],
    })
    import json

    parsed = json.loads(result)
    assert edit is None
    assert "pace guard" in parsed["error"]
    assert parsed["recent_pace_profile"]["typical_pace"] == "7:30"
    assert db.query(PendingEdit).count() == 0


# --- garmin plan mirror -------------------------------------------------------

# Monday 7 full weeks back, so today is always plan week 8 (Monday-aligned).
PLAN_START = TODAY - dt.timedelta(days=TODAY.weekday()) - dt.timedelta(weeks=7)
PLAN_END = TODAY + dt.timedelta(days=120)


class FakeGarmin:
    def __init__(self, active=True):
        self.active = active

    def get_training_plans(self):
        status = "Scheduled" if self.active else "Completed"
        return {"trainingPlanList": [{
            "trainingPlanId": 45820254,
            "name": "Half plan",
            "trainingStatus": {"statusKey": status},
            "startDate": f"{PLAN_START.isoformat()}T00:00:00.0",
            "endDate": f"{PLAN_END.isoformat()}T00:00:00.0",
            "durationInWeeks": 25,
            "avgWeeklyWorkouts": 5,
        }]}

    def get_adaptive_training_plan_by_id(self, plan_id):
        assert plan_id == 45820254
        return {
            "adaptivePlanPhases": [
                {"trainingPhase": "BASE", "currentPhase": True,
                 "startDate": PLAN_START.isoformat(),
                 "endDate": (TODAY + dt.timedelta(days=7)).isoformat()},
                {"trainingPhase": "BUILD", "currentPhase": False,
                 "startDate": (TODAY + dt.timedelta(days=8)).isoformat(),
                 "endDate": PLAN_END.isoformat()},
            ],
            "taskList": [
                {"weekId": 7, "calendarDate": TODAY.isoformat(),
                 "taskWorkout": {"workoutName": "Threshold",
                                 "workoutDescription": "18:00@172bpm",
                                 "sportType": {"sportTypeKey": "running"},
                                 "estimatedDurationInSecs": 2280,
                                 "priorityType": "REQUIRED",
                                 "trainingEffectLabel": "THRESHOLD",
                                 "restDay": False,
                                 "adaptiveCoachingWorkoutStatus": "NOT_COMPLETE"}},
                {"weekId": 20, "calendarDate": (TODAY + dt.timedelta(days=90)).isoformat(),
                 "taskWorkout": {"workoutName": "Far away"}},  # outside window
            ],
        }


def test_sync_training_plan_mirrors_active_plan(db):
    u = make_user(db)
    assert sync_training_plan(db, u.id, FakeGarmin()) is True
    row = db.get(TrainingPlan, u.id)
    assert row.garmin_plan_id == 45820254
    assert [p["phase"] for p in row.phases] == ["base", "build"]
    assert len(row.upcoming_tasks) == 1  # far-away task filtered out
    task = row.upcoming_tasks[0]
    assert task["week"] == 8 and task["name"] == "Threshold"
    assert task["duration_min"] == 38


def test_sync_training_plan_removes_row_when_no_active_plan(db):
    u = make_user(db)
    sync_training_plan(db, u.id, FakeGarmin())
    assert sync_training_plan(db, u.id, FakeGarmin(active=False)) is False
    assert db.get(TrainingPlan, u.id) is None


def test_plan_payload_week_and_phase(db):
    u = make_user(db)
    sync_training_plan(db, u.id, FakeGarmin())
    payload = plan_payload(db.get(TrainingPlan, u.id), TODAY)
    assert payload["source"] == "garmin"
    assert payload["phase"] == "base"
    # start 52 days ago, Monday-aligned weeks: today is week 8
    assert payload["current_week"] == 8
    assert payload["total_weeks"] == 25


def test_garmin_plan_context_feeds_planner(db):
    u = make_user(db)
    sync_training_plan(db, u.id, FakeGarmin())
    ctx = garmin_plan_context(db, u.id, TODAY)
    assert ctx["phase"] == "base" and ctx["current_week"] == 8
    assert ctx["scheduled_workouts"][0]["name"] == "Threshold"


def test_derived_payload_fallback():
    race = TODAY + dt.timedelta(days=60)  # 60 days out = build phase
    payload = derived_payload("My race", race, TODAY)
    assert payload["source"] == "derived"
    assert payload["phase"] == "build"
    assert payload["phases"][-1]["phase"] == "race"
    # Timeline starts at race-84d (24 days ago), Monday-aligned: week 4 or 5.
    assert 4 <= payload["current_week"] <= 5
    assert payload["current_week"] <= payload["total_weeks"]


def test_training_plan_endpoint_prefers_garmin(client, db):
    from app.auth import create_session

    u = make_user(db)
    token = create_session(db, u)
    client.cookies.set("gb_session", token)
    # No plan, no race -> null
    assert client.get("/api/training-plan").json() is None
    # Primary race -> derived
    db.add(Race(user_id=u.id, name="R", date=TODAY + dt.timedelta(days=30),
                distance_km=21.1, is_primary=True))
    db.commit()
    assert client.get("/api/training-plan").json()["source"] == "derived"
    # Mirrored Garmin plan wins
    sync_training_plan(db, u.id, FakeGarmin())
    body = client.get("/api/training-plan").json()
    assert body["source"] == "garmin" and body["current_week"] == 8


def test_accept_superseded_edit_conflicts(client, db):
    from app.auth import create_session

    u = make_user(db)
    token = create_session(db, u)
    client.cookies.set("gb_session", token)
    edit = PendingEdit(user_id=u.id, summary="old", changes=[], current=[],
                       status="superseded")
    db.add(edit)
    db.commit()
    res = client.post(f"/api/edits/{edit.id}/accept")
    assert res.status_code == 409
    assert "superseded" in res.json()["detail"]
