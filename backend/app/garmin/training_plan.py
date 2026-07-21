"""Mirror the user's active Garmin Coach adaptive training plan.

Garmin Run Coach plans carry their own phase timeline (BASE/BUILD/PEAK/TAPER/
TARGET_EVENT_DAY) and week numbering. When one exists it is ground truth for
"which phase and week am I on" — the app reads it instead of deriving its own
timeline, so an athlete 8 weeks into a Garmin plan is never shown week 1.

weekId in Garmin's taskList is 0-indexed over Monday-aligned weeks from the
plan's start week; humans (and this module's payloads) count from week 1.
"""

from __future__ import annotations

import datetime as dt
import logging

from sqlalchemy.orm import Session

from ..models import TrainingPlan

log = logging.getLogger(__name__)

PHASE_MAP = {
    "BASE": "base",
    "BUILD": "build",
    "PEAK": "peak",
    "TAPER": "taper",
    "TARGET_EVENT_DAY": "race",
}
PHASE_LABELS = {
    "base": "Base",
    "build": "Build",
    "peak": "Peak",
    "taper": "Taper",
    "race": "Race day",
}
TASK_WINDOW_DAYS = 14


def _date(s) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(s)[:10])
    except (ValueError, TypeError):
        return None


def _week_of(plan_start: dt.date, day: dt.date) -> int:
    """1-indexed plan week for `day` (Monday-aligned, matching Garmin's weekId)."""
    monday0 = plan_start - dt.timedelta(days=plan_start.weekday())
    return max(1, (day - monday0).days // 7 + 1)


def _parse_phases(detail: dict) -> list[dict]:
    out = []
    for p in detail.get("adaptivePlanPhases") or []:
        phase = PHASE_MAP.get(p.get("trainingPhase"))
        start, end = _date(p.get("startDate")), _date(p.get("endDate"))
        if phase and start and end:
            out.append({
                "phase": phase,
                "label": PHASE_LABELS[phase],
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
            })
    return out


def _parse_tasks(detail: dict, today: dt.date) -> list[dict]:
    """Scheduled Garmin Coach workouts within +/- the mirror window."""
    out = []
    for t in detail.get("taskList") or []:
        date = _date(t.get("calendarDate"))
        if date is None or abs((date - today).days) > TASK_WINDOW_DAYS:
            continue
        w = t.get("taskWorkout") or {}
        secs = w.get("estimatedDurationInSecs")
        out.append({
            "date": date.isoformat(),
            "week": (t.get("weekId") or 0) + 1,
            "name": w.get("workoutName") or "",
            "description": w.get("workoutDescription") or "",
            "sport": ((w.get("sportType") or {}).get("sportTypeKey")) or "running",
            "duration_min": round(secs / 60) if secs else None,
            "training_effect": w.get("trainingEffectLabel"),
            "priority": w.get("priorityType"),
            "rest_day": bool(w.get("restDay")),
            "status": w.get("adaptiveCoachingWorkoutStatus"),
        })
    out.sort(key=lambda x: x["date"])
    return out


def sync_training_plan(db: Session, user_id: int, garmin) -> bool:
    """Fetch the active Garmin Coach plan into training_plans (one row/user).

    Returns True when an active plan was mirrored; deletes the row (and
    returns False) when Garmin no longer has one.
    """
    today = dt.date.today()
    listing = garmin.get_training_plans() or {}
    active = None
    for p in listing.get("trainingPlanList") or []:
        status = (p.get("trainingStatus") or {}).get("statusKey")
        end = _date(p.get("endDate"))
        if status != "Scheduled" or end is None or end < today:
            continue
        if active is None or (_date(p.get("startDate")) or today) > (
            _date(active.get("startDate")) or today
        ):
            active = p

    row = db.get(TrainingPlan, user_id)
    if active is None:
        if row is not None:
            db.delete(row)
            db.commit()
        return False

    detail = garmin.get_adaptive_training_plan_by_id(active["trainingPlanId"]) or {}
    row = row or TrainingPlan(user_id=user_id)
    row.garmin_plan_id = int(active["trainingPlanId"])
    row.name = active.get("name") or ""
    row.start_date = _date(active.get("startDate")) or today
    row.end_date = _date(active.get("endDate")) or today
    row.duration_weeks = active.get("durationInWeeks")
    row.avg_weekly_workouts = active.get("avgWeeklyWorkouts")
    row.phases = _parse_phases(detail)
    row.upcoming_tasks = _parse_tasks(detail, today)
    row.synced_at = dt.datetime.now(dt.timezone.utc)
    db.merge(row)
    db.commit()
    return True


# Coach taskList trainingEffectLabel values that impose real intensity. Base,
# recovery, long-easy, and rest days are not "hard" for structural spacing.
HARD_TE_LABELS = {"LACTATE_THRESHOLD", "VO2MAX", "ANAEROBIC_CAPACITY", "SPEED", "TEMPO"}


def task_is_hard(task: dict) -> bool:
    """True when a mirrored coach task is an intensity session (not base/rest).

    Rest days arrive blank (`rest_day=True`, `training_effect='INVALID'`); those
    are never hard. Used by the structural review to see hard-day clustering."""
    if task.get("rest_day"):
        return False
    return (task.get("training_effect") or "").upper() in HARD_TE_LABELS


def has_active_plan(db: Session, user_id: int, today: dt.date) -> bool:
    """True when the user has a mirrored Garmin Coach plan active on `today`.

    This is what flips Idaten from author to editor: an active plan means
    Garmin owns the base week and Idaten only reviews/diffs it."""
    row = db.get(TrainingPlan, user_id)
    return row is not None and row.start_date <= today <= row.end_date


def current_phase(phases: list[dict], today: dt.date) -> str | None:
    for p in phases or []:
        start, end = _date(p["start_date"]), _date(p["end_date"])
        if start and end and start <= today <= end:
            return p["phase"]
    return None


def plan_payload(row: TrainingPlan, today: dt.date) -> dict:
    """API shape for a mirrored Garmin plan; week/phase computed at read time."""
    return {
        "source": "garmin",
        "name": row.name,
        "start_date": row.start_date.isoformat(),
        "end_date": row.end_date.isoformat(),
        "total_weeks": row.duration_weeks,
        "current_week": min(
            _week_of(row.start_date, today), row.duration_weeks or 10_000
        ) if today >= row.start_date else None,
        "phase": current_phase(row.phases, today),
        "phases": row.phases,
        "upcoming_tasks": row.upcoming_tasks or [],
    }


def derived_payload(race_name: str, race_date: dt.date, today: dt.date) -> dict | None:
    """Fallback phase timeline for users without a Garmin Coach plan, derived
    from the primary race with the same boundaries as workout_library.phase_for
    (base > 84 days out, build 43-84, peak 14-42, taper 1-13, race day)."""
    if race_date < today:
        return None
    start = min(today, race_date - dt.timedelta(days=84))
    bounds = [
        ("base", start, race_date - dt.timedelta(days=85)),
        ("build", race_date - dt.timedelta(days=84), race_date - dt.timedelta(days=43)),
        ("peak", race_date - dt.timedelta(days=42), race_date - dt.timedelta(days=14)),
        ("taper", race_date - dt.timedelta(days=13), race_date - dt.timedelta(days=1)),
        ("race", race_date, race_date),
    ]
    phases = [
        {"phase": ph, "label": PHASE_LABELS[ph],
         "start_date": s.isoformat(), "end_date": e.isoformat()}
        for ph, s, e in bounds if s <= e and e >= start
    ]
    total_weeks = (race_date - start).days // 7 + 1
    return {
        "source": "derived",
        "name": race_name,
        "start_date": start.isoformat(),
        "end_date": race_date.isoformat(),
        "total_weeks": total_weeks,
        "current_week": min(_week_of(start, today), total_weeks),
        "phase": current_phase(phases, today),
        "phases": phases,
        "upcoming_tasks": [],
    }


def garmin_plan_context(db: Session, user_id: int, today: dt.date) -> dict | None:
    """Compact planner/chat-prompt context for an active mirrored plan."""
    row = db.get(TrainingPlan, user_id)
    if row is None or not (row.start_date <= today <= row.end_date):
        return None
    return {
        "name": row.name,
        "current_week": _week_of(row.start_date, today),
        "total_weeks": row.duration_weeks,
        "phase": current_phase(row.phases, today),
        "race_date": row.end_date.isoformat(),
        "scheduled_workouts": row.upcoming_tasks or [],
    }
