"""Pull activities + daily health (sleep, HRV, RHR, body battery, stress) into SQLite.

Each metric is fetched defensively: Garmin's per-day endpoints vary in shape and
frequently return partial data, so one failing metric never aborts the sync.
"""

from __future__ import annotations

import datetime as dt
import logging

from garminconnect import GarminConnectTooManyRequestsError
from sqlalchemy.orm import Session

from ..config import config
from ..models import Activity, DailyHealth, User
from .client import get_garmin

log = logging.getLogger(__name__)


def _get(d: dict | None, *path, default=None):
    cur = d
    for p in path:
        if not isinstance(cur, dict) or p not in cur:
            return default
        cur = cur[p]
    return cur if cur is not None else default


def sync_activities(db: Session, user_id: int, garmin, start: dt.date, end: dt.date) -> int:
    acts = garmin.get_activities_by_date(start.isoformat(), end.isoformat()) or []
    n = 0
    for a in acts:
        aid = a.get("activityId")
        if aid is None:
            continue
        started = (a.get("startTimeLocal") or a.get("startTimeGMT") or "")[:10]
        try:
            date = dt.date.fromisoformat(started)
        except ValueError:
            continue
        row = db.get(Activity, int(aid)) or Activity(id=int(aid), user_id=user_id)
        row.user_id = user_id
        row.date = date
        row.type = _get(a, "activityType", "typeKey", default="running")
        row.name = a.get("activityName") or row.type
        row.distance_m = a.get("distance")
        row.duration_s = a.get("duration")
        row.avg_hr = a.get("averageHR")
        row.avg_speed_mps = a.get("averageSpeed")
        row.training_load = a.get("activityTrainingLoad")
        # Body-battery change is already in the summary payload — no extra call.
        row.body_battery_change = a.get("differenceBodyBattery")
        row.cadence = a.get("averageRunningCadenceInStepsPerMinute")
        row.start_lat = a.get("startLatitude")
        row.start_lon = a.get("startLongitude")
        row.raw = a
        db.merge(row)
        n += 1
    return n


def _parse_vo2max(payload) -> float | None:
    """get_max_metrics returns a list of daily entries with a 'generic' block."""
    items = payload if isinstance(payload, list) else [payload]
    for item in items or []:
        generic = _get(item, "generic", default={}) or {}
        v = generic.get("vo2MaxPreciseValue") or generic.get("vo2MaxValue")
        if v:
            return float(v)
    return None


def _parse_race_predictions(payload) -> dict | None:
    items = payload if isinstance(payload, list) else [payload]
    for item in items or []:
        if not isinstance(item, dict):
            continue
        out = {
            "time_5k_s": item.get("time5K"),
            "time_10k_s": item.get("time10K"),
            "time_half_s": item.get("timeHalfMarathon"),
            "time_marathon_s": item.get("timeMarathon"),
        }
        if any(v for v in out.values()):
            return out
    return None


def sync_fitness_day(db: Session, user_id: int, garmin, date: dt.date) -> None:
    """VO2max + race predictions for a day (stored on DailyHealth)."""
    row = db.get(DailyHealth, (user_id, date)) or DailyHealth(user_id=user_id, date=date)
    try:
        row.vo2max = _parse_vo2max(garmin.get_max_metrics(date.isoformat())) or row.vo2max
    except Exception as e:  # noqa: BLE001
        log.debug("max metrics failed for %s: %s", date, e)
    try:
        preds = _parse_race_predictions(garmin.get_race_predictions())
        if preds:
            row.race_predictions = preds
    except Exception as e:  # noqa: BLE001
        log.debug("race predictions failed for %s: %s", date, e)
    db.merge(row)


def sync_health_day(db: Session, user_id: int, garmin, date: dt.date) -> None:
    """Fetch one day's wellness metrics.

    Individual metrics fail independently (partial data is normal), but a 429
    ALWAYS propagates — swallowing it writes empty rows for every subsequent
    day while Garmin throttles us, which looks like missing data.
    """
    row = db.get(DailyHealth, (user_id, date)) or DailyHealth(user_id=user_id, date=date)

    try:
        sleep = garmin.get_sleep_data(date.isoformat())
        dto = _get(sleep, "dailySleepDTO", default={}) or {}
        row.sleep_seconds = dto.get("sleepTimeSeconds")
        row.sleep_score = _get(dto, "sleepScores", "overall", "value")
    except GarminConnectTooManyRequestsError:
        raise
    except Exception as e:  # noqa: BLE001
        log.debug("sleep fetch failed for %s: %s", date, e)

    try:
        hrv = garmin.get_hrv_data(date.isoformat())
        summary = _get(hrv, "hrvSummary", default={}) or {}
        row.hrv = summary.get("lastNightAvg")
        row.hrv_baseline = _get(summary, "baseline", "balancedLow") or summary.get("weeklyAvg")
    except GarminConnectTooManyRequestsError:
        raise
    except Exception as e:  # noqa: BLE001
        log.debug("hrv fetch failed for %s: %s", date, e)

    try:
        rhr = garmin.get_rhr_day(date.isoformat())
        metrics = _get(rhr, "allMetrics", "metricsMap", default={}) or {}
        values = metrics.get("WELLNESS_RESTING_HEART_RATE") or []
        if values:
            row.resting_hr = values[0].get("value")
    except GarminConnectTooManyRequestsError:
        raise
    except Exception as e:  # noqa: BLE001
        log.debug("rhr fetch failed for %s: %s", date, e)

    try:
        bb = garmin.get_body_battery(date.isoformat()) or []
        if bb and isinstance(bb, list):
            charged = bb[0].get("charged")
            if isinstance(charged, (int, float)):
                row.body_battery = charged
    except GarminConnectTooManyRequestsError:
        raise
    except Exception as e:  # noqa: BLE001
        log.debug("body battery fetch failed for %s: %s", date, e)

    try:
        stress = garmin.get_stress_data(date.isoformat())
        row.stress_avg = _get(stress, "avgStressLevel")
    except GarminConnectTooManyRequestsError:
        raise
    except Exception as e:  # noqa: BLE001
        log.debug("stress fetch failed for %s: %s", date, e)

    db.merge(row)


def run_sync(db: Session, user: User, lookback_days: int | None = None) -> str:
    """Sync the trailing window for one user. Returns the end date synced through (ISO)."""
    garmin = get_garmin(user)
    end = dt.date.today()
    start = end - dt.timedelta(days=lookback_days or config.sync_lookback_days)

    n = sync_activities(db, user.id, garmin, start, end)
    d = start
    while d <= end:
        sync_health_day(db, user.id, garmin, d)
        d += dt.timedelta(days=1)
    sync_fitness_day(db, user.id, garmin, end)
    db.commit()

    from .profile import sync_profile
    from .races_import import sync_races

    sync_profile(db, user.id, garmin)
    try:
        sync_races(db, user.id, garmin)
    except Exception as e:  # noqa: BLE001
        db.rollback()  # import writes nothing on failure; never poison the session
        log.warning("race import failed for user %d: %s", user.id, e)

    from .training_plan import sync_training_plan

    try:
        sync_training_plan(db, user.id, garmin)
    except Exception as e:  # noqa: BLE001
        db.rollback()
        log.warning("training plan sync failed for user %d: %s", user.id, e)

    from .gear import sync_gear

    try:
        sync_gear(db, user.id, garmin)
    except GarminConnectTooManyRequestsError:
        db.rollback()
        log.warning("gear sync rate-limited for user %d; will retry next sync", user.id)
    except Exception as e:  # noqa: BLE001
        db.rollback()
        log.warning("gear sync failed for user %d: %s", user.id, e)

    from .enrich import enrich_pending

    enriched = enrich_pending(db, user.id, garmin)
    log.info("user %d: synced %d activities, health %s..%s, enriched %d",
             user.id, n, start, end, enriched)
    return end.isoformat()
