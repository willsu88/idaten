"""Push planned workouts to the Garmin calendar so they appear on the watch.

Uses garminconnect's workout-service methods: `upload_workout` to create the
structured workout, `schedule_workout` to put it on a calendar date, and
`delete_workout` to remove a superseded version.

A plan day with `steps` maps to a multi-step workout: each block becomes
executable steps, repeat blocks become a RepeatGroupDTO with the block's steps
as children. Days without steps keep the legacy single-step shape (time or
distance end condition, optional pace/HR target). Rest and cross-train days
are not pushed.
"""

from __future__ import annotations

import datetime as dt
import logging

from sqlalchemy.orm import Session

from ..metrics import pace_to_mps
from ..models import PlanDay, User
from .client import get_garmin

log = logging.getLogger(__name__)

PACE_BAND_MPS = 0.15
PUSHABLE_TYPES = {"easy_run", "long_run", "tempo", "intervals", "recovery", "race"}

_RUNNING = {"sportTypeId": 1, "sportTypeKey": "running"}

# Garmin workout-service step types
_STEP_TYPES = {
    "warmup": (1, "warmup"),
    "cooldown": (2, "cooldown"),
    "work": (3, "interval"),
    "recovery": (4, "recovery"),
    "rest": (5, "rest"),
}
_REPEAT_TYPE = (6, "repeat")


class _Order:
    """stepOrder is globally sequential across the whole workout, including
    repeat-group containers and their children."""

    def __init__(self) -> None:
        self.n = 0

    def next(self) -> int:
        self.n += 1
        return self.n


def _end_condition(step: dict, distance_km, duration_min) -> None:
    if distance_km:
        step["endCondition"] = {"conditionTypeId": 3, "conditionTypeKey": "distance"}
        step["endConditionValue"] = float(distance_km) * 1000.0
    elif duration_min:
        step["endCondition"] = {"conditionTypeId": 2, "conditionTypeKey": "time"}
        step["endConditionValue"] = float(duration_min) * 60.0
    else:
        step["endCondition"] = {"conditionTypeId": 1, "conditionTypeKey": "lap.button"}
        step["endConditionValue"] = 1.0


def _target(step: dict, target_pace, hr_low, hr_high) -> None:
    """One target per step: pace when set, else a custom HR band."""
    mps = pace_to_mps(target_pace) if target_pace else None
    if mps:
        step["targetType"] = {"workoutTargetTypeId": 6, "workoutTargetTypeKey": "pace.zone"}
        step["targetValueOne"] = mps - PACE_BAND_MPS  # slow bound
        step["targetValueTwo"] = mps + PACE_BAND_MPS  # fast bound
    elif hr_low and hr_high:
        step["targetType"] = {"workoutTargetTypeId": 4, "workoutTargetTypeKey": "heart.rate.zone"}
        step["targetValueOne"] = float(hr_low)   # bpm bounds = custom band
        step["targetValueTwo"] = float(hr_high)


def _executable_step(s: dict, order: _Order) -> dict:
    type_id, type_key = _STEP_TYPES.get(s.get("kind") or "work", _STEP_TYPES["work"])
    step: dict = {
        "type": "ExecutableStepDTO",
        "stepOrder": order.next(),
        "stepType": {"stepTypeId": type_id, "stepTypeKey": type_key},
        "targetType": {"workoutTargetTypeId": 1, "workoutTargetTypeKey": "no.target"},
        "description": (s.get("note") or "")[:512],
    }
    _end_condition(step, s.get("distance_km"), s.get("duration_min"))
    _target(step, s.get("target_pace"), s.get("target_hr_low"), s.get("target_hr_high"))
    return step


def _structured_steps(blocks: list[dict], order: _Order) -> list[dict]:
    out: list[dict] = []
    for block in blocks:
        repeat = int(block.get("repeat") or 1)
        inner = block.get("steps") or []
        if repeat > 1:
            group: dict = {
                "type": "RepeatGroupDTO",
                "stepOrder": order.next(),
                "stepType": {"stepTypeId": _REPEAT_TYPE[0], "stepTypeKey": _REPEAT_TYPE[1]},
                "numberOfIterations": repeat,
                "smartRepeat": False,
                "endCondition": {"conditionTypeId": 7, "conditionTypeKey": "iterations"},
                "endConditionValue": float(repeat),
            }
            group["workoutSteps"] = [_executable_step(s, order) for s in inner]
            out.append(group)
        else:
            out.extend(_executable_step(s, order) for s in inner)
    return out


def _legacy_step(day: PlanDay, order: _Order) -> dict:
    step: dict = {
        "type": "ExecutableStepDTO",
        "stepOrder": order.next(),
        "stepType": {"stepTypeId": 3, "stepTypeKey": "interval"},
        "targetType": {"workoutTargetTypeId": 1, "workoutTargetTypeKey": "no.target"},
    }
    _end_condition(step, day.distance_km, day.duration_min)
    _target(step, day.target_pace, day.target_hr_low, day.target_hr_high)
    return step


def _workout_payload(day: PlanDay) -> dict:
    order = _Order()
    if day.steps:
        steps = _structured_steps(day.steps, order)
    else:
        steps = [_legacy_step(day, order)]

    return {
        "workoutName": f"{day.title} ({day.date.isoformat()})",
        "description": (day.description or "")[:1024],
        "sportType": _RUNNING,
        "workoutSegments": [
            {"segmentOrder": 1, "sportType": _RUNNING, "workoutSteps": steps}
        ],
    }


def push_day(db: Session, day: PlanDay) -> str | None:
    """Create + schedule the workout for one plan day. Returns the workout id."""
    if day.workout_type not in PUSHABLE_TYPES:
        return None

    garmin = get_garmin(db.get(User, day.user_id))

    # Replace any previously pushed version of this day
    if day.garmin_workout_id:
        try:
            garmin.delete_workout(day.garmin_workout_id)
        except Exception as e:  # noqa: BLE001
            log.warning("could not delete old workout %s: %s", day.garmin_workout_id, e)

    created = garmin.upload_workout(_workout_payload(day))
    workout_id = str(created["workoutId"])
    garmin.schedule_workout(workout_id, day.date.isoformat())

    day.garmin_workout_id = workout_id
    day.pushed_at = dt.datetime.now(dt.timezone.utc)
    db.add(day)
    db.commit()
    log.info("pushed %s '%s' as workout %s", day.date, day.title, workout_id)
    return workout_id


def unpush_day(db: Session, day: PlanDay) -> bool:
    """Remove this day's workout from the Garmin calendar. Returns True if one was removed."""
    if not day.garmin_workout_id:
        return False
    garmin = get_garmin(db.get(User, day.user_id))
    try:
        garmin.delete_workout(day.garmin_workout_id)
    except Exception as e:  # noqa: BLE001
        log.warning("delete of workout %s failed (may already be gone): %s",
                    day.garmin_workout_id, e)
    day.garmin_workout_id = None
    day.pushed_at = None
    db.add(day)
    db.commit()
    return True


def push_days(db: Session, days: list[PlanDay]) -> None:
    """Best-effort push of several days (used by auto-push after replans)."""
    for day in days:
        try:
            push_day(db, day)
        except Exception as e:  # noqa: BLE001
            log.error("push failed for %s: %s", day.date, e)
