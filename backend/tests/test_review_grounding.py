"""The daily review grounds on the athlete's ACTUAL plan (plan_days = Garmin base
+ accepted edits), not Garmin's raw taskList — with a per-day Garmin fallback for
days not yet materialized. Prevents the coach note from quoting a workout the
athlete already edited away (e.g. a VO2 session now shown as rest)."""

from __future__ import annotations

import datetime as dt

from app.planner import _todays_prescribed, _upcoming_structure

TODAY = dt.date(2026, 7, 19)
TOM = TODAY + dt.timedelta(days=1)
HORIZON = TODAY + dt.timedelta(days=7)


def _snap(plan_days, garmin_tasks):
    return {
        "current_upcoming_plan": plan_days,
        "garmin_coach_plan": {"scheduled_workouts": garmin_tasks},
    }


def test_todays_prescribed_prefers_plan_day_over_garmin():
    # Garmin's task for today is a hard tempo; the athlete's plan_day is an easy
    # run (an accepted edit). The review must see the easy run.
    snap = _snap(
        plan_days=[{"date": TODAY.isoformat(), "workout_type": "easy_run", "title": "Easy"}],
        garmin_tasks=[{"date": TODAY.isoformat(), "name": "Tempo",
                       "training_effect": "LACTATE_THRESHOLD", "rest_day": False}],
    )
    got = _todays_prescribed(snap, TODAY)
    assert got["workout_type"] == "easy_run"  # the plan_day, not Garmin's tempo


def test_todays_prescribed_falls_back_to_garmin_when_no_plan_day():
    snap = _snap(
        plan_days=[],  # not yet materialized
        garmin_tasks=[{"date": TODAY.isoformat(), "name": "Base",
                       "training_effect": "AEROBIC_BASE", "rest_day": False}],
    )
    got = _todays_prescribed(snap, TODAY)
    assert got["name"] == "Base"  # Garmin fallback


def test_structure_uses_edited_plan_not_garmin_vo2():
    # The real-world case: Garmin has VO2 (hard) tomorrow, but the athlete edited
    # tomorrow to rest. Structural view must count rest, not a hard day.
    snap = _snap(
        plan_days=[
            {"date": TODAY.isoformat(), "workout_type": "long_run", "title": "Long"},
            {"date": TOM.isoformat(), "workout_type": "rest", "title": "Rest"},
        ],
        garmin_tasks=[
            {"date": TODAY.isoformat(), "name": "", "rest_day": True, "training_effect": "INVALID"},
            {"date": TOM.isoformat(), "name": "VO2 Max", "rest_day": False,
             "training_effect": "VO2MAX"},
        ],
    )
    flags = _upcoming_structure(snap, TODAY, HORIZON)
    by_date = {f["date"]: f for f in flags}
    assert by_date[TOM.isoformat()]["rest"] is True    # the edit wins
    assert by_date[TOM.isoformat()]["hard"] is False   # NOT Garmin's VO2
    assert by_date[TODAY.isoformat()]["rest"] is False  # plan_day long run, not Garmin's rest


def test_structure_fallback_for_unmaterialized_day():
    # A day Garmin has but plan_days doesn't (past the materialize horizon) still
    # shows up, using Garmin's latest task.
    snap = _snap(
        plan_days=[{"date": TODAY.isoformat(), "workout_type": "easy_run", "title": "Easy"}],
        garmin_tasks=[{"date": TOM.isoformat(), "name": "Intervals", "rest_day": False,
                       "training_effect": "VO2MAX"}],
    )
    flags = _upcoming_structure(snap, TODAY, HORIZON)
    by_date = {f["date"]: f for f in flags}
    assert by_date[TOM.isoformat()]["hard"] is True  # Garmin fallback for the gap day
