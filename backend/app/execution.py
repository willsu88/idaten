"""Execution scoring: judge how well a completed run matched the workout it was
attempting.

Two orthogonal decisions, neither of which names a device:

  1. Attribution - was this run an attempt at a planned workout at all? Tier-1
     (definitive) signals only here: a Garmin coach-plan run (the activity
     carries `metadataDTO.trainingPlanId`) or a day Idaten pushed a structured
     workout to. A free run is left unscored (Phase 3 adds the prompt for the
     ambiguous middle).

  2. Score source - `summaryDTO.directWorkoutComplianceScore` present ? PULL the
     watch's own score : COMPUTE ours. Field-presence, not watch model, so it is
     self-correcting for every watch (a 255 that scores our pushed workout is
     pulled; a 165 that scores nothing is computed).

Computed scores use metrics.execution_score against a prescription: our own
PlanDay steps for an Idaten-pushed run, or - when Garmin hides the coach targets
- bands DERIVED from each lap's own intensityType + the day's training-effect
label + the athlete's Garmin HR zones.
"""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from . import metrics
from .metrics import derive_hr_band, execution_score
from .models import Activity, PlanDay, TrainingPlan

# Half-width of the target band around a single prescribed pace (m/s), matching
# what push.py writes to the watch. execution_score adds decay beyond it.
PACE_BAND_MPS = 0.15


def _pace_band(pace: str | None) -> tuple[float, float] | None:
    mps = metrics.pace_to_mps(pace) if pace else None
    if not mps:
        return None
    return (mps - PACE_BAND_MPS, mps + PACE_BAND_MPS)


def _step_segment(hr_low, hr_high, pace, dur_min, dist_km, label) -> dict | None:
    """One prescription step -> a scoring segment ({axis, low, high, duration_s})."""
    dur = float(dur_min) * 60 if dur_min else None
    if hr_low and hr_high:
        axis, low, high = "hr", float(hr_low), float(hr_high)
    else:
        band = _pace_band(pace)
        if not band:
            return None  # no.target step - nothing to score against
        axis, (low, high) = "pace", band
        if not dur and dist_km:
            dur = float(dist_km) * 1000 / ((low + high) / 2)
    if not dur:
        return None
    return {"axis": axis, "low": low, "high": high, "duration_s": dur, "label": label}


def _idaten_segments(day: PlanDay, zones: dict | None) -> list[dict]:
    """Segments from an Idaten-authored prescription (structured or simple)."""
    segs: list[dict] = []
    if day.steps:
        for block in day.steps:
            for _ in range(int(block.get("repeat") or 1)):
                for s in (block.get("steps") or []):
                    seg = _step_segment(s.get("target_hr_low"), s.get("target_hr_high"),
                                        s.get("target_pace"), s.get("duration_min"),
                                        s.get("distance_km"), s.get("kind") or "work")
                    if seg:
                        segs.append(seg)
    else:
        seg = _step_segment(day.target_hr_low, day.target_hr_high, day.target_pace,
                            day.duration_min, day.distance_km, day.workout_type)
        if seg:
            segs.append(seg)
    return segs


def _coach_segments(splits, te_label, zones, a: Activity) -> list[dict]:
    """Segments for a Garmin coach run whose targets Garmin hides: derive each
    lap's band from its own intensityType + the day's training-effect label."""
    if not zones:
        return []
    # Only score per-lap when the laps actually carry their prescribed intensity;
    # otherwise every lap would be judged as "work" and a warmup/cooldown would
    # be unfairly zeroed. Laps cached before the intensity field existed fall
    # through to the whole-run estimate below.
    segs: list[dict] = []
    for lp in splits or []:
        if not lp.get("intensity"):
            continue
        band = derive_hr_band(lp.get("intensity"), te_label, zones)
        dur = lp.get("duration_s")
        if band and dur:
            segs.append({"axis": "hr", "low": band[0], "high": band[1],
                         "duration_s": dur, "label": lp.get("intensity")})
    if segs:
        return segs
    # Fallback (laps carry no structure): whole run vs the TE work zone.
    band = derive_hr_band("INTERVAL", te_label, zones)
    if band and a.duration_s:
        return [{"axis": "hr", "low": band[0], "high": band[1],
                 "duration_s": a.duration_s, "label": te_label or "run"}]
    return []


def mark_day_completed(db: Session, user_id: int, date) -> None:
    """Flip a matched plan day to 'completed' so the daily review, materialize,
    and revert-to-Garmin all leave it untouched (and the Week can show it done).
    Only ever planned -> completed; never touches a skipped/override history."""
    day = db.get(PlanDay, (user_id, date))
    if day is not None and day.status == "planned":
        day.status = "completed"
        db.add(day)


def score_run(db: Session, a: Activity, full: dict | None,
              zones: dict | None) -> tuple[int | None, str | None, list | None]:
    """(score, source, breakdown) for a run, or (None, None, None) if it was not
    an attempt at a planned workout. `full` is the get_activity payload."""
    summary = (full or {}).get("summaryDTO") or {}
    meta = (full or {}).get("metadataDTO") or {}

    from .planner import _is_override

    is_coach = meta.get("trainingPlanId") is not None
    day = db.get(PlanDay, (a.user_id, a.date))
    non_rest_day = bool(day and day.workout_type != "rest")
    is_idaten_pushed = bool(non_rest_day and day.garmin_workout_id)
    # A day the athlete's ACTUAL plan is Idaten's, not Garmin's: an accepted
    # edit or author-mode day. Its prescription supersedes Garmin's even when the
    # run still carries a coach trainingPlanId (Garmin tags every run inside a
    # coach plan's window). Load-bearing: score against the FINAL plan they
    # followed, never Garmin's original.
    is_idaten_plan = bool(non_rest_day and _is_override(db, day))

    if not (is_coach or is_idaten_pushed or is_idaten_plan):
        return None, None, None  # free / ambiguous run - not scored here

    prefer_idaten = is_idaten_plan or (is_idaten_pushed and not is_coach)

    # Pull the watch's own compliance score only when the structured workout on
    # the watch WAS the plan being scored: a plain coach run, or an Idaten day we
    # actually pushed. For an Idaten edit we didn't push, the watch still holds
    # Garmin's workout, so its score is against the wrong target - compute ours.
    gscore = summary.get("directWorkoutComplianceScore")
    if gscore is not None and ((is_coach and not is_idaten_plan) or is_idaten_pushed):
        return int(gscore), "garmin", None

    segs = (_idaten_segments(day, zones) if prefer_idaten
            else _coach_segments(a.splits, summary.get("trainingEffectLabel"), zones, a))
    out = execution_score(a.series, segs)
    if not out:
        return None, None, None
    return out["score"], "idaten", out["breakdown"]


# --- Tier-3: the ambiguous middle -----------------------------------------
# A run auto-attribution didn't catch, on a day that DOES have a planned
# non-rest workout. We ask the athlete "was this your {workout}?" once, folded
# into the Today RPE moment; a Yes scores it, a No marks it a plain run forever.

def _coach_task(db: Session, user_id: int, date) -> dict | None:
    plan = db.get(TrainingPlan, user_id)
    for t in (plan.upcoming_tasks if plan else None) or []:
        if t.get("date") == date.isoformat() and not t.get("rest_day"):
            return t
    return None


def _planned_workout(db: Session, user_id: int, date) -> dict | None:
    """The planned non-rest workout for a date (Idaten's PlanDay, else the coach
    task), or None."""
    day = db.get(PlanDay, (user_id, date))
    if day and day.workout_type != "rest":
        return {"source": "idaten", "label": day.title or day.workout_type, "day": day}
    task = _coach_task(db, user_id, date)
    if task:
        return {"source": "coach", "label": task.get("name") or "workout",
                "te": task.get("training_effect")}
    return None


def prompt_label(db: Session, a: Activity) -> str | None:
    """Name of the workout to ask 'was this your {X}?', or None if this run is not
    eligible for the attribution prompt (already scored / already decided / no
    planned workout that day / another run that day already covers it)."""
    if "run" not in (a.type or "") or a.execution_score is not None \
            or a.execution_attributed is not None:
        return None
    pw = _planned_workout(db, a.user_id, a.date)
    if not pw:
        return None
    sibling = db.scalar(select(Activity).where(
        Activity.user_id == a.user_id, Activity.date == a.date, Activity.id != a.id,
        or_(Activity.execution_score.is_not(None),
            Activity.execution_attributed.is_(True))))
    return None if sibling else pw["label"]


def score_confirmed(db: Session, a: Activity,
                    zones: dict | None) -> tuple[int | None, list | None]:
    """Score a run the athlete confirmed WAS an attempt at that day's planned
    workout. Returns (score, breakdown)."""
    pw = _planned_workout(db, a.user_id, a.date)
    if not pw:
        return None, None
    segs = (_idaten_segments(pw["day"], zones) if pw["source"] == "idaten"
            else _coach_segments(a.splits, pw.get("te"), zones, a))
    out = execution_score(a.series, segs)
    return (out["score"], out["breakdown"]) if out else (None, None)
