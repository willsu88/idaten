from __future__ import annotations

import datetime as dt

from app.garmin.push import PACE_BAND_MPS, PUSHABLE_TYPES, _workout_payload, push_day
from app.metrics import pace_to_mps
from app.models import PlanDay

TODAY = dt.date.today()


def _day(**kw):
    defaults = dict(user_id=1, date=TODAY, workout_type="easy_run", title="Easy run",
                    description="Keep it conversational")
    defaults.update(kw)
    return PlanDay(**defaults)


def _step(payload):
    return payload["workoutSegments"][0]["workoutSteps"][0]


def test_distance_end_condition_wins_over_time():
    step = _step(_workout_payload(_day(distance_km=8.0, duration_min=45)))
    assert step["endCondition"]["conditionTypeKey"] == "distance"
    assert step["endConditionValue"] == 8000.0


def test_time_end_condition():
    step = _step(_workout_payload(_day(duration_min=45)))
    assert step["endCondition"]["conditionTypeKey"] == "time"
    assert step["endConditionValue"] == 45 * 60.0


def test_lap_button_fallback():
    step = _step(_workout_payload(_day()))
    assert step["endCondition"]["conditionTypeKey"] == "lap.button"


def test_pace_target_band():
    step = _step(_workout_payload(_day(distance_km=10, target_pace="5:30")))
    mps = pace_to_mps("5:30")
    assert step["targetType"]["workoutTargetTypeKey"] == "pace.zone"
    assert abs(step["targetValueOne"] - (mps - PACE_BAND_MPS)) < 1e-9
    assert abs(step["targetValueTwo"] - (mps + PACE_BAND_MPS)) < 1e-9


def test_no_pace_means_no_target():
    step = _step(_workout_payload(_day(distance_km=10)))
    assert step["targetType"]["workoutTargetTypeKey"] == "no.target"


def test_workout_name_includes_date():
    payload = _workout_payload(_day(title="Tempo"))
    assert TODAY.isoformat() in payload["workoutName"]
    assert payload["sportType"]["sportTypeKey"] == "running"


def test_rest_and_cross_train_not_pushable(db):
    for wtype in ("rest", "cross_train"):
        assert wtype not in PUSHABLE_TYPES
        day = _day(workout_type=wtype)
        db.add(day)
        db.commit()
        # Returns None before ever touching Garmin
        assert push_day(db, day) is None
        db.delete(day)
        db.commit()
