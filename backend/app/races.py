"""Races: multiple upcoming races, one primary, per-race prediction.

The authoritative prediction is Idaten's own, computed from the athlete's
DEMONSTRATED performance (see metrics.demonstrated_anchor / race_prediction) and
a per-user calibration factor. Garmin's VO2max race predictor is kept only as a
labelled reference (`garmin_time_s`), Riegel-adjusted to each race's exact
distance with `t2 = t1 * (d2 / d1) ** 1.06` from the nearest predicted distance.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import metrics, settings_store
from .models import Activity, DailyHealth, Race

RIEGEL_EXP = 1.06
PREDICTION_ANCHORS = [  # (distance_km, race_predictions key)
    (5.0, "time_5k_s"),
    (10.0, "time_10k_s"),
    (21.0975, "time_half_s"),
    (42.195, "time_marathon_s"),
]


def parse_goal_time(goal_time: str | None) -> int | None:
    try:
        parts = [int(p) for p in goal_time.strip().split(":")]
        while len(parts) < 3:
            parts.insert(0, 0)
        h, m, s = parts[-3:]
        return h * 3600 + m * 60 + s
    except (ValueError, AttributeError):
        return None


def _pace_str_from_time(total_s: float | None, distance_km: float | None) -> str | None:
    if not total_s or not distance_km:
        return None
    sec_per_km = total_s / distance_km
    return f"{int(sec_per_km // 60)}:{int(sec_per_km % 60):02d}"


def latest_predictions(db: Session, user_id: int) -> dict | None:
    row = db.scalars(
        select(DailyHealth)
        .where(DailyHealth.user_id == user_id, DailyHealth.race_predictions.is_not(None))
        .order_by(DailyHealth.date.desc())
        .limit(1)
    ).first()
    return row.race_predictions if row else None


def riegel_predict(predictions: dict | None, distance_km: float) -> float | None:
    """Predicted time (s) for an arbitrary distance from the nearest anchor."""
    if not predictions or not distance_km:
        return None
    candidates = [
        (abs(d - distance_km), d, predictions.get(key))
        for d, key in PREDICTION_ANCHORS
        if predictions.get(key)
    ]
    if not candidates:
        return None
    _, anchor_d, anchor_t = min(candidates)
    return float(anchor_t) * (distance_km / anchor_d) ** RIEGEL_EXP


@dataclass
class PredictionContext:
    """Per-request inputs shared across every race so calibration + Garmin's
    predictions are read once, not per race."""
    garmin_predictions: dict | None
    k: float
    n_samples: int


def prediction_context(db: Session, user_id: int, today: dt.date | None = None) -> PredictionContext:
    cal = settings_store.get_race_calibration(db, user_id)
    return PredictionContext(
        garmin_predictions=latest_predictions(db, user_id),
        k=cal["k"],
        n_samples=len(cal["samples"]),
    )


def race_prediction_block(r: Race, ctx: PredictionContext) -> dict:
    """The v1.20 `prediction` object: Idaten's calibrated number + Garmin ref."""
    goal_s = parse_goal_time(r.goal_time)
    garmin_s = riegel_predict(ctx.garmin_predictions, r.distance_km)
    core = metrics.race_prediction(garmin_s, ctx.k, ctx.n_samples)
    likely_s = core["likely_s"]
    return {
        "source": core["source"],
        "likely_s": likely_s,
        "low_s": core["low_s"],
        "high_s": core["high_s"],
        "confidence": core["confidence"],
        "delta_s": round(likely_s - goal_s) if likely_s and goal_s else None,
        "likely_pace": _pace_str_from_time(likely_s, r.distance_km),
        "goal_time_s": goal_s,
        "goal_pace": _pace_str_from_time(goal_s, r.distance_km),
        "garmin_time_s": round(garmin_s) if garmin_s else None,
    }


def race_dict(r: Race, ctx: PredictionContext) -> dict:
    today = dt.date.today()
    return {
        "id": r.id,
        "name": r.name,
        "date": r.date.isoformat(),
        "distance_km": r.distance_km,
        "goal_time": r.goal_time,
        "is_primary": r.is_primary,
        "source": r.source or "manual",
        "days_to_race": (r.date - today).days,
        "prediction": race_prediction_block(r, ctx),
        "course": r.course,
    }


# Match tolerance for treating a finished activity as "the athlete ran this race":
# same day (±1) and distance within 5%.
RESULT_DIST_TOL = 0.05
RESULT_DATE_TOL_DAYS = 1


def maybe_record_race_result(db: Session, user_id: int, a: Activity) -> None:
    """If activity `a` looks like the athlete's run of a scheduled race, fold its
    actual finish time into the per-user calibration (idempotent per race).

    Compares the actual time against GARMIN's predicted time for the race, so `k`
    learns this athlete's systematic optimism/pessimism vs Garmin's predictor.
    No-op when nothing matches or Garmin has no prediction for the distance.
    """
    if not a.distance_m or not a.duration_s or "running" not in (a.type or ""):
        return
    today = dt.date.today()
    predictions = latest_predictions(db, user_id)
    for r in db.scalars(select(Race).where(Race.user_id == user_id)):
        if abs((a.date - r.date).days) > RESULT_DATE_TOL_DAYS:
            continue
        if not r.distance_km or abs(a.distance_m / 1000 - r.distance_km) / r.distance_km > RESULT_DIST_TOL:
            continue
        garmin_pred = riegel_predict(predictions, r.distance_km)
        settings_store.update_race_calibration(db, user_id, r.id, garmin_pred, a.duration_s, today)
        return


def upcoming_races(db: Session, user_id: int, include_past: bool = False) -> list[Race]:
    q = select(Race).where(Race.user_id == user_id).order_by(Race.date)
    if not include_past:
        q = q.where(Race.date >= dt.date.today())
    return list(db.scalars(q))


def primary_race(db: Session, user_id: int) -> Race | None:
    return db.scalars(
        select(Race).where(Race.user_id == user_id, Race.is_primary.is_(True)).limit(1)
    ).first()


def set_primary(db: Session, race: Race) -> None:
    for r in db.scalars(select(Race).where(Race.user_id == race.user_id)):
        r.is_primary = r.id == race.id
    db.commit()


def ensure_primary(db: Session, user_id: int) -> None:
    """After deletes/edits: if no primary remains, promote the next upcoming race."""
    if primary_race(db, user_id) is not None:
        return
    nxt = db.scalars(
        select(Race).where(Race.user_id == user_id, Race.date >= dt.date.today())
        .order_by(Race.date).limit(1)
    ).first()
    if nxt:
        nxt.is_primary = True
        db.commit()
