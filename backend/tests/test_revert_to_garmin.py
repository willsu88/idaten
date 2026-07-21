"""Feature 3: revert an Idaten edit back to the original mirrored Garmin Coach
workout — force-overwriting the override, clearing the pushed watch workout."""

from __future__ import annotations

import datetime as dt

from app.models import DayIntent, PlanDay, PlanVersion, TrainingPlan
from app.planner import (
    edited_days_in_window,
    materialize_coach_plan,
    revert_to_garmin,
)

TODAY = dt.date(2026, 7, 17)

TASKS = [
    {"date": TODAY.isoformat(), "week": 8, "name": "Threshold",
     "training_effect": "LACTATE_THRESHOLD", "rest_day": False,
     "duration_min": 38, "description": "18:00@172bpm"},
    {"date": (TODAY + dt.timedelta(days=1)).isoformat(), "name": "Long Run",
     "training_effect": "AEROBIC_BASE", "rest_day": False,
     "duration_min": 62, "description": "145bpm"},
]


def _plan(db, user_id, tasks=TASKS):
    db.add(TrainingPlan(
        user_id=user_id, garmin_plan_id=1, name="SUPERACE",
        start_date=TODAY - dt.timedelta(days=50), end_date=TODAY + dt.timedelta(days=100),
        duration_weeks=25, phases=[], upcoming_tasks=tasks,
    ))
    db.commit()


def _accept_edit(db, user_id, date, **fields):
    """Simulate an accepted chat edit on a day (source=chat_edit override)."""
    override = PlanVersion(user_id=user_id, source="chat_edit", summary="ease off")
    db.add(override)
    db.flush()
    day = db.get(PlanDay, (user_id, date))
    for k, v in fields.items():
        setattr(day, k, v)
    day.version_id = override.id
    db.commit()
    return day


def test_revert_restores_garmin_workout(db, user):
    _plan(db, user.id)
    materialize_coach_plan(db, user.id, TODAY)
    _accept_edit(db, user.id, TODAY, workout_type="easy_run", title="Easy run",
                 target_hr_low=None, target_hr_high=None, rationale="eased off")

    reverted = revert_to_garmin(db, user.id, [TODAY], TODAY)

    assert reverted == [TODAY]
    thr = db.get(PlanDay, (user.id, TODAY))
    assert thr.workout_type == "tempo"      # back to Garmin's Threshold
    assert thr.title == "Threshold"
    assert thr.target_hr_low == 172
    assert thr.rationale == ""              # Idaten note dropped


def test_revert_clears_pushed_watch_workout(db, user, monkeypatch):
    _plan(db, user.id)
    materialize_coach_plan(db, user.id, TODAY)
    _accept_edit(db, user.id, TODAY, workout_type="easy_run", title="Easy run",
                 garmin_workout_id="99", pushed_at=dt.datetime.now(dt.timezone.utc))

    from app.garmin import push
    calls = []
    monkeypatch.setattr(push, "unpush_day",
                        lambda db, day: calls.append(day.date) or True)

    revert_to_garmin(db, user.id, [TODAY], TODAY)
    assert calls == [TODAY]  # native Garmin stands; Idaten's push removed


def test_revert_leaves_completed_day_untouched(db, user):
    _plan(db, user.id)
    materialize_coach_plan(db, user.id, TODAY)
    day = _accept_edit(db, user.id, TODAY, workout_type="easy_run", title="Easy run")
    day.status = "completed"
    db.commit()

    reverted = revert_to_garmin(db, user.id, [TODAY], TODAY)
    assert reverted == []
    assert db.get(PlanDay, (user.id, TODAY)).title == "Easy run"  # history intact


def test_revert_preserves_committed_intent_day(db, user):
    # Reverting must not stamp a Garmin run over a committed other-sport day.
    _plan(db, user.id)
    materialize_coach_plan(db, user.id, TODAY)
    db.add(DayIntent(user_id=user.id, date=TODAY, sport="freediving",
                     note="Freediving", source="chat"))
    _accept_edit(db, user.id, TODAY, workout_type="cross_train", title="Freediving")

    revert_to_garmin(db, user.id, [TODAY], TODAY)
    day = db.get(PlanDay, (user.id, TODAY))
    assert day.workout_type == "cross_train"
    assert day.title == "Freediving"
    assert day.target_hr_low is None


def test_revert_ignores_date_outside_mirror_window(db, user):
    _plan(db, user.id)
    far = TODAY + dt.timedelta(days=30)  # no task mirrored this far out
    assert revert_to_garmin(db, user.id, [far], TODAY) == []


def test_edited_days_in_window_lists_only_overrides(db, user):
    _plan(db, user.id)
    materialize_coach_plan(db, user.id, TODAY)
    _accept_edit(db, user.id, TODAY, workout_type="easy_run", title="Easy run")
    # The Long Run day (TODAY+1) stays the Garmin base — not an override.
    edited = edited_days_in_window(db, user.id, TODAY, TODAY + dt.timedelta(days=6))
    assert edited == [TODAY]


def test_revert_no_plan_returns_empty(db, user):
    assert revert_to_garmin(db, user.id, [TODAY], TODAY) == []
