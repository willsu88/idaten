"""Phase C base: materialize the Garmin coach taskList into plan_days as the
editor base, override-safe (never clobbers a user-accepted edit)."""

from __future__ import annotations

import datetime as dt

from app.models import DayIntent, PlanDay, PlanVersion, TrainingPlan
from app.planner import materialize_coach_plan

TODAY = dt.date(2026, 7, 17)

# A realistic slice of Julianne's mirrored coach week.
TASKS = [
    {"date": TODAY.isoformat(), "week": 8, "name": "Threshold",
     "training_effect": "LACTATE_THRESHOLD", "rest_day": False,
     "duration_min": 38, "description": "18:00@172bpm"},
    {"date": (TODAY + dt.timedelta(days=1)).isoformat(), "name": "",
     "training_effect": "INVALID", "rest_day": True, "description": ""},
    {"date": (TODAY + dt.timedelta(days=2)).isoformat(), "name": "Long Run",
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


def test_materialize_creates_base_days(db, user):
    _plan(db, user.id)
    changed = materialize_coach_plan(db, user.id, TODAY)
    assert len(changed) == 3

    thr = db.get(PlanDay, (user.id, TODAY))
    assert thr.workout_type == "tempo"
    assert thr.title == "Threshold"
    assert thr.target_hr_low == 172 and thr.target_hr_high == 172
    assert thr.rationale == ""  # base plan carries no Idaten rationale

    rest = db.get(PlanDay, (user.id, TODAY + dt.timedelta(days=1)))
    assert rest.workout_type == "rest"
    assert rest.title == "Rest"
    assert rest.target_hr_low is None

    long = db.get(PlanDay, (user.id, TODAY + dt.timedelta(days=2)))
    assert long.workout_type == "long_run"
    assert long.target_hr_low == 145


def test_materialize_is_idempotent(db, user):
    _plan(db, user.id)
    materialize_coach_plan(db, user.id, TODAY)
    changed = materialize_coach_plan(db, user.id, TODAY)
    assert changed == []  # nothing materially changed on the second pass


def test_materialize_never_overwrites_accepted_edit(db, user):
    _plan(db, user.id)
    materialize_coach_plan(db, user.id, TODAY)
    # The athlete accepted an ease-off for the threshold day (chat_edit origin).
    override = PlanVersion(user_id=user.id, source="chat_edit", summary="ease off")
    db.add(override)
    db.flush()
    thr = db.get(PlanDay, (user.id, TODAY))
    thr.workout_type = "easy_run"
    thr.title = "Easy run"
    thr.target_hr_low = None
    thr.target_hr_high = None
    thr.version_id = override.id
    db.commit()

    changed = materialize_coach_plan(db, user.id, TODAY)  # a later daily re-copy
    thr = db.get(PlanDay, (user.id, TODAY))
    assert thr.workout_type == "easy_run"   # override preserved, not reverted
    assert thr.title == "Easy run"
    assert all(c.date != TODAY for c in changed)


def test_materialize_skips_completed_day(db, user):
    _plan(db, user.id)
    materialize_coach_plan(db, user.id, TODAY)
    thr = db.get(PlanDay, (user.id, TODAY))
    thr.status = "completed"
    thr.workout_type = "tempo"
    db.commit()
    # Rewrite the coach task for today; materialize must not touch a done day.
    plan = db.get(TrainingPlan, user.id)
    plan.upcoming_tasks = [{**TASKS[0], "name": "Changed", "description": "20:00@175bpm"}]
    db.commit()
    materialize_coach_plan(db, user.id, TODAY)
    assert db.get(PlanDay, (user.id, TODAY)).status == "completed"
    assert db.get(PlanDay, (user.id, TODAY)).title == "Threshold"  # untouched


def test_materialize_overwrites_legacy_authored_day(db, user):
    # A day authored by the old daily_job (version None or daily_job) is base and
    # gets replaced by Garmin's plan when we switch to editor mode.
    db.add(PlanDay(user_id=user.id, date=TODAY, workout_type="intervals",
                   title="Old Idaten intervals", status="planned"))
    db.commit()
    _plan(db, user.id)
    materialize_coach_plan(db, user.id, TODAY)
    thr = db.get(PlanDay, (user.id, TODAY))
    assert thr.workout_type == "tempo" and thr.title == "Threshold"


def test_materialize_honors_day_intent_over_garmin_run(db, user):
    # Garmin schedules a Threshold run today, but the athlete committed the day
    # to freediving. Even on an overwritable base, materialize must NOT stamp a
    # run — it coerces to cross_train (the intent lives in a separate table).
    _plan(db, user.id, tasks=[TASKS[0]])  # today = Threshold run
    db.add(DayIntent(user_id=user.id, date=TODAY, sport="freediving",
                     note="Freediving", source="chat"))
    db.commit()
    materialize_coach_plan(db, user.id, TODAY)
    day = db.get(PlanDay, (user.id, TODAY))
    assert day.workout_type == "cross_train"
    assert day.title == "Freediving"
    assert day.target_hr_low is None  # not the 172bpm threshold target


def test_materialize_no_plan_returns_empty(db, user):
    assert materialize_coach_plan(db, user.id, TODAY) == []
