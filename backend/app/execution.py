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

import logging
from typing import NamedTuple

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from . import metrics
from .metrics import derive_hr_band, execution_score, pace_band_mps
from .models import Activity, PlanDay, PlanVersion, TrainingPlan
from .planner import QUALITY_TYPES

log = logging.getLogger(__name__)


def _step_segment(hr_low, hr_high, pace, dur_min, dist_km, label,
                  zones=None, quality=False, terrain="flat") -> dict | None:
    """One prescription step -> a scoring segment ({axis, low, high, duration_s}).

    Legacy days may still carry a degenerate stored band (ADR 0017 predates
    them); never score against one - widen it through the zone rule instead.
    """
    dur = float(dur_min) * 60 if dur_min else None
    if hr_low and hr_high:
        hr_low, hr_high = metrics.ensure_hr_band(hr_low, hr_high, zones, quality)
        axis, low, high = "hr", float(hr_low), float(hr_high)
    elif terrain == "uphill":
        # Uphill pace is the gradient, not the effort. A climb held at exactly
        # the right effort misses a flat-ground band by a wide margin, so
        # scoring it against one fails a correctly-executed repetition. Days
        # stored before the terrain guard can still carry a pace-only uphill
        # step; leave those unscored rather than score them wrongly.
        if pace:
            # Never silent (the ADR 0020 lesson): dropping a step from the
            # breakdown looks identical to the step having had no target.
            log.warning("uphill step prescribed only a pace target (%r) - left "
                        "out of the execution score", pace)
        return None
    else:
        # Scored against exactly the band push.py sent to the watch, so the
        # score always judges what the athlete was actually shown.
        band = pace_band_mps(pace)
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
    quality = day.workout_type in QUALITY_TYPES
    if day.steps:
        for block in day.steps:
            for _ in range(int(block.get("repeat") or 1)):
                for s in (block.get("steps") or []):
                    kind = s.get("kind") or "work"
                    seg = _step_segment(s.get("target_hr_low"), s.get("target_hr_high"),
                                        s.get("target_pace"), s.get("duration_min"),
                                        s.get("distance_km"), kind,
                                        zones, quality and kind == "work",
                                        metrics.step_terrain(s))
                    if seg:
                        segs.append(seg)
    else:
        seg = _step_segment(day.target_hr_low, day.target_hr_high, day.target_pace,
                            day.duration_min, day.distance_km, day.workout_type,
                            zones, quality)
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


# Climb below which a repetition did not happen on a hill. A 45-75s uphill
# effort covers roughly 150-250m; on any gradient worth calling a hill that is
# at least 10m of ascent, while a flat lap records 0-2m of GPS noise. 8m sits in
# the gap, well clear of both.
MIN_REP_ASCENT_M = 8.0


def _uphill_reps(day: PlanDay | None) -> int:
    """How many uphill repetitions the day prescribes, repeat blocks expanded."""
    if day is None or not day.steps:
        return 0
    total = 0
    for block in day.steps:
        uphill = [s for s in (block.get("steps") or [])
                  if metrics.step_terrain(s) == "uphill"]
        total += len(uphill) * int(block.get("repeat") or 1)
    return total


def hill_check(day: PlanDay | None, splits) -> dict | None:
    """Did the prescribed uphill work actually happen on a hill? None if the day
    prescribed no uphill work, or the run has no laps to check.

    Deliberately BESIDE the execution score, never inside it. The score is a
    continuous time-in-band measure over HR and pace; whether the ground went up
    is a yes/no fact, and folding a boolean into a continuous score would
    corrupt both. Garmin has no grade trigger or target, so it cannot enforce
    that a repetition happened on a hill - this is the only place the
    prescription is ever checked against the ground.

    Laps are matched to repetitions by CLIMB, not by `wktStepIndex`. Index
    alignment depends on how a given watch laps a structured workout (and breaks
    entirely under auto-lap), whereas "the prescribed climbs are the laps that
    climbed the most" holds however the run was recorded.
    """
    reps = _uphill_reps(day)
    if not reps:
        return None
    gains = [lp.get("elevation_gain_m") or 0.0 for lp in splits or []]
    if not gains:
        return None
    hardest = sorted(gains, reverse=True)[:reps]
    climbed = [g for g in hardest if g >= MIN_REP_ASCENT_M]
    return {
        "prescribed_reps": reps,
        "climbed_reps": len(climbed),
        # Climb over ALL the matched repetitions, not only the qualifying ones -
        # otherwise a failed check reports 0m and cannot say how flat the ground
        # actually was, which is the one number that makes the verdict legible.
        "ascent_m": round(sum(hardest)),
        # A majority is enough: an athlete who cuts the set short still ran the
        # session on a hill, and the execution score already judges the
        # shortfall. This flag answers terrain, and only terrain.
        "verified": len(climbed) >= (reps + 1) // 2,
    }


def mark_day_completed(db: Session, user_id: int, date) -> None:
    """Flip a matched plan day to 'completed' so the daily review, materialize,
    and revert-to-Garmin all leave it untouched (and the Week can show it done).
    Only ever planned -> completed; never touches a skipped/override history."""
    day = db.get(PlanDay, (user_id, date))
    if day is not None and day.status == "planned":
        day.status = "completed"
        db.add(day)


class ScoreResult(NamedTuple):
    """score_run's verdict plus its ADR 0018 provenance: the prescription the
    score judged (frozen onto the activity by the caller) and the executed-vs-
    planned divergence when the run didn't execute the current PlanDay."""

    score: int | None = None
    source: str | None = None
    breakdown: list | None = None
    prescription: dict | None = None
    mismatch: dict | None = None
    # ADR 0021: terrain verification, set only when the prescription judged was
    # OUR plan day (the only kind that carries step terrain) and the run
    # actually executed it. Null everywhere else.
    hill: dict | None = None


NOT_SCORED = ScoreResult()


def _norm_name(name: str | None) -> str:
    """Workout-name equality is strip+casefold exact match, in one place."""
    return (name or "").strip().casefold()


def _executed_coach_workout(db: Session, a: Activity) -> dict | None:
    """The Garmin coach prescription this run executed, identified by workout
    name - the only reliable executed-workout evidence (the detail payload
    carries no associatedWorkoutId for coach runs; ADR 0018). Checks the live
    mirrored taskList first, then the day's PlanVersion mirror history."""
    name = _norm_name(a.name)
    if not name:
        return None
    task = _coach_task(db, a.user_id, a.date)
    if task and _norm_name(task.get("name")) == name:
        return {"title": task.get("name"),
                "training_effect": task.get("training_effect")}
    date_iso = a.date.isoformat()
    versions = db.scalars(
        select(PlanVersion)
        .where(PlanVersion.user_id == a.user_id,
               PlanVersion.source == "garmin_mirror")
        .order_by(PlanVersion.id.desc())).all()
    for v in versions:
        for d in v.snapshot or []:
            if d.get("date") == date_iso and _norm_name(d.get("name")) == name:
                return {"title": d.get("name"),
                        "training_effect": d.get("training_effect"),
                        "version_id": v.id}
    return None


def _plan_day_prescription(day: PlanDay) -> dict:
    return {"source": "plan_day", "version_id": day.version_id,
            "title": day.title, "workout_type": day.workout_type,
            "targets": {"hr_low": day.target_hr_low, "hr_high": day.target_hr_high,
                        "pace": day.target_pace, "duration_min": day.duration_min,
                        "distance_km": day.distance_km},
            "steps": day.steps}


def _coach_prescription(executed: dict | None, a: Activity,
                        te_label: str | None) -> dict:
    out = {"source": "garmin_coach",
           "title": (executed or {}).get("title") or a.name,
           "training_effect": (executed or {}).get("training_effect") or te_label}
    if executed and executed.get("version_id"):
        out["version_id"] = executed["version_id"]
    return out


def _version_source(db: Session, day: PlanDay) -> str | None:
    v = db.get(PlanVersion, day.version_id) if day.version_id else None
    return v.source if v else None


def score_run(db: Session, a: Activity, full: dict | None,
              zones: dict | None) -> ScoreResult:
    """Score a run against the prescription it executed, or NOT_SCORED if it was
    not an attempt at a planned workout. `full` is the get_activity payload."""
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
        return NOT_SCORED  # free / ambiguous run - not scored here

    # ADR 0018: a non-pushed edit leaves Garmin's workout on the watch. When a
    # coach run's name resolves to that original workout rather than the edited
    # day, the athlete ran the original - score the prescription they executed
    # and record the divergence, instead of grading the wrong homework.
    mismatch = executed = None
    if is_idaten_plan and is_coach and not is_idaten_pushed:
        executed = _executed_coach_workout(db, a)
        if executed and _norm_name(day.title) != _norm_name(executed["title"]):
            mismatch = {"executed": executed["title"], "planned": day.title,
                        "planned_source": _version_source(db, day)}
        else:
            executed = None  # names agree (or no evidence): the edit was followed

    prefer_idaten = mismatch is None and (
        is_idaten_plan or (is_idaten_pushed and not is_coach))

    # The training-effect label driving coach-band derivation: the executed
    # prescription's own label when resolved, else Garmin's summary label.
    te = (executed or {}).get("training_effect") or summary.get("trainingEffectLabel")

    # Pull the watch's own compliance score only when the structured workout on
    # the watch WAS the prescription being scored: a plain coach run, an Idaten
    # day we actually pushed, or a mismatch (the athlete ran the watch's
    # workout). For a followed non-pushed edit, the watch's score is against
    # the wrong target - compute ours.
    # Terrain verification follows attribution, exactly as the score does
    # (ADR 0018): only our own plan day carries step terrain, and a run that
    # executed some other workout is no evidence about this day's hills.
    hill = (hill_check(day, a.splits)
            if mismatch is None and (is_idaten_pushed or prefer_idaten) else None)

    gscore = summary.get("directWorkoutComplianceScore")
    if gscore is not None and ((is_coach and not is_idaten_plan)
                               or is_idaten_pushed or mismatch is not None):
        # Stamp guard differs from prefer_idaten on purpose: a pushed day's
        # watch score judged Idaten's own workout even on a coach-tagged run.
        prescription = (_plan_day_prescription(day) if is_idaten_pushed
                        else _coach_prescription(executed, a, te))
        return ScoreResult(int(gscore), "garmin", None, prescription, mismatch, hill)
    segs = (_idaten_segments(day, zones) if prefer_idaten
            else _coach_segments(a.splits, te, zones, a))
    out = execution_score(a.series, segs)
    if not out:
        return NOT_SCORED
    prescription = (_plan_day_prescription(day) if prefer_idaten
                    else _coach_prescription(executed, a, te))
    return ScoreResult(out["score"], "idaten", out["breakdown"],
                       prescription, mismatch, hill)


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
                    zones: dict | None) -> tuple[int | None, list | None, dict | None]:
    """Score a run the athlete confirmed WAS an attempt at that day's planned
    workout. Returns (score, breakdown, hill_check).

    The athlete's Yes IS the attribution here, so the terrain check applies on
    the same terms as the score - but only to our own plan day, since a Garmin
    coach task carries no step terrain to check against.
    """
    pw = _planned_workout(db, a.user_id, a.date)
    if not pw:
        return None, None, None
    is_idaten = pw["source"] == "idaten"
    segs = (_idaten_segments(pw["day"], zones) if is_idaten
            else _coach_segments(a.splits, pw.get("te"), zones, a))
    out = execution_score(a.series, segs)
    if not out:
        return None, None, None
    hill = hill_check(pw["day"], a.splits) if is_idaten else None
    return out["score"], out["breakdown"], hill
