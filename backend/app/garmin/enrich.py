"""Per-activity enrichment: HR zones, aerobic decoupling, cadence, weather.

Runs after sync for running activities that haven't been enriched yet. Each
activity costs ~3 extra Garmin calls (+1 Open-Meteo fallback), so enrichment is
throttled and capped per pass; leftovers are picked up on subsequent syncs.
"""

from __future__ import annotations

import datetime as dt
import logging
import time

import httpx
from garminconnect import GarminConnectTooManyRequestsError
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import metrics
from ..models import Activity
from ..settings_store import put_garmin_hr_zones

log = logging.getLogger(__name__)

RUN_TYPES = ("running", "trail_running", "track_running", "treadmill_running")


def _time_in_zones(payload: list) -> dict | None:
    out = {}
    for z in payload or []:
        n = z.get("zoneNumber")
        if n and 1 <= int(n) <= 5:
            out[f"z{int(n)}"] = round(z.get("secsInZone") or 0)
    return out or None


def _hr_drift(details: dict) -> float | None:
    """Aerobic decoupling: EF(first half) vs EF(second half), split by time.

    Positive drift means HR rose relative to pace late in the run; <5% is the
    classic 'aerobically coupled' threshold.
    """
    descriptors = details.get("metricDescriptors") or []
    idx = {d.get("key"): d.get("metricsIndex") for d in descriptors}
    hr_i, speed_i, t_i = idx.get("directHeartRate"), idx.get("directSpeed"), idx.get("sumDuration")
    if hr_i is None or speed_i is None or t_i is None:
        return None

    points = []
    for row in details.get("activityDetailMetrics") or []:
        m = row.get("metrics") or []
        try:
            t, hr, speed = m[t_i], m[hr_i], m[speed_i]
        except (IndexError, TypeError):
            continue
        if t is not None and hr and speed and speed > 0.5:  # moving, HR sensor live
            points.append((t, hr, speed))
    if len(points) < 40:
        return None

    mid = points[len(points) // 2][0]
    first = [(hr, s) for t, hr, s in points if t <= mid]
    second = [(hr, s) for t, hr, s in points if t > mid]
    if len(first) < 10 or len(second) < 10:
        return None

    def ef(chunk: list) -> float:
        return (sum(s for _, s in chunk) / len(chunk)) / (sum(h for h, _ in chunk) / len(chunk))

    ef1, ef2 = ef(first), ef(second)
    if ef2 <= 0:
        return None
    return round((ef1 / ef2 - 1) * 100, 1)


def _garmin_weather(garmin, activity_id: int) -> float | None:
    w = garmin.get_activity_weather(activity_id) or {}
    temp = w.get("temp")
    if temp is None:
        return None
    return round((float(temp) - 32) * 5 / 9, 1)  # Garmin's weather DTO is Fahrenheit


def _open_meteo(lat: float, lon: float, start_local: str) -> float | None:
    """Historical hourly temperature at the activity's start (free, keyless)."""
    try:
        date, hour = start_local[:10], int(start_local[11:13])
    except (ValueError, IndexError):
        return None
    try:
        r = httpx.get(
            "https://archive-api.open-meteo.com/v1/archive",
            params={
                "latitude": lat, "longitude": lon,
                "start_date": date, "end_date": date,
                "hourly": "temperature_2m",
            },
            timeout=10,
        )
        r.raise_for_status()
        temps = r.json().get("hourly", {}).get("temperature_2m") or []
        return round(float(temps[hour]), 1) if len(temps) > hour and temps[hour] is not None else None
    except Exception as e:  # noqa: BLE001
        log.debug("open-meteo failed: %s", e)
        return None


def _rpe_feel(summary: dict) -> tuple[int | None, int | None]:
    """Convert Garmin's raw RPE/feel to our 1-10 / 1-5 scales.

    Garmin stores RPE x10 (30 -> 3/10) and feel as 0/25/50/75/100
    (Very Weak..Very Strong -> 1..5). Absent/0 means the athlete didn't log it.
    """
    raw_rpe = summary.get("directWorkoutRpe")
    rpe = round(raw_rpe / 10) if raw_rpe else None
    raw_feel = summary.get("directWorkoutFeel")
    feel = round(raw_feel / 25) + 1 if raw_feel is not None else None
    return rpe, feel


def enrich_activity(db: Session, garmin, a: Activity) -> None:
    raw = a.raw or {}
    a.cadence = a.cadence or raw.get("averageRunningCadenceInStepsPerMinute")
    a.start_lat = a.start_lat or raw.get("startLatitude")
    a.start_lon = a.start_lon or raw.get("startLongitude")
    a.body_battery_change = raw.get("differenceBodyBattery") if a.body_battery_change is None else a.body_battery_change

    # RPE + feel live on the per-activity summary (get_activity_details lacks
    # them). Fetched for ALL activity types — the athlete can log effort/feel on
    # a walk or ride, not just runs. The full payload (summaryDTO + metadataDTO)
    # is reused below for execution scoring, so fetch it once.
    full: dict = {}
    try:
        full = garmin.get_activity(a.id) or {}
        a.garmin_rpe, a.feel = _rpe_feel(full.get("summaryDTO") or {})
    except GarminConnectTooManyRequestsError:
        raise
    except Exception as e:  # noqa: BLE001
        log.debug("rpe/feel failed for %s: %s", a.id, e)

    # The rest — zones, HR drift, chart series, splits, weather, execution score
    # — is run-specific analysis; skip it (and its Garmin calls) for non-runs.
    if a.type in RUN_TYPES:
        _enrich_run_metrics(db, garmin, a, raw, full)
        # If this run is the athlete's attempt at a scheduled race, fold its
        # actual time into the per-user prediction calibration (idempotent).
        from ..races import maybe_record_race_result
        maybe_record_race_result(db, a.user_id, a)

    a.enriched = True
    db.add(a)


def _enrich_run_metrics(db: Session, garmin, a: Activity, raw: dict,
                        full: dict) -> None:
    from .series import (ROUTE_MAX_POINTS, SERIES_MAX_POINTS, parse_route,
                         parse_series, parse_splits)

    try:
        # One HR-in-zones payload feeds both the per-activity time-in-zone
        # breakdown AND the athlete's cached Garmin zone boundaries (the basis
        # both the planner and the execution scorer use).
        hrz = garmin.get_activity_hr_in_timezones(a.id) or []
        a.time_in_zones = _time_in_zones(hrz)
        put_garmin_hr_zones(db, a.user_id, metrics.hr_zones_from_garmin(hrz),
                            a.date.isoformat())
    except GarminConnectTooManyRequestsError:
        raise  # 429s must reach enrich_pending so the pass aborts un-marked
    except Exception as e:  # noqa: BLE001
        log.debug("zones failed for %s: %s", a.id, e)
    try:
        # One details call feeds HR drift, the cached chart series, and the route
        details = garmin.get_activity_details(
            a.id, maxchart=SERIES_MAX_POINTS, maxpoly=ROUTE_MAX_POINTS)
        a.hr_drift_pct = _hr_drift(details)
        a.series = parse_series(details)
        a.route = parse_route(details)
    except GarminConnectTooManyRequestsError:
        raise
    except Exception as e:  # noqa: BLE001
        log.debug("details/series failed for %s: %s", a.id, e)
    try:
        a.splits = parse_splits(garmin.get_activity_splits(a.id))
    except GarminConnectTooManyRequestsError:
        raise
    except Exception as e:  # noqa: BLE001
        log.debug("splits failed for %s: %s", a.id, e)
    try:
        a.temperature_c = _garmin_weather(garmin, a.id)
    except GarminConnectTooManyRequestsError:
        raise
    except Exception as e:  # noqa: BLE001
        log.debug("garmin weather failed for %s: %s", a.id, e)
    if a.temperature_c is None and a.start_lat and a.start_lon:
        start_local = raw.get("startTimeLocal") or ""
        a.temperature_c = _open_meteo(a.start_lat, a.start_lon, start_local)

    # Execution score — needs series/splits (above) + the athlete's zones. Pulls
    # Garmin's compliance score or computes ours; leaves a free run unscored.
    try:
        from ..settings_store import hr_zones
        from .. import execution
        score, source, breakdown = execution.score_run(
            db, a, full, hr_zones(db, a.user_id))
        a.execution_score, a.execution_score_source, a.execution_breakdown = (
            score, source, breakdown)
        # A scored run WAS attributed to the day's plan → mark it completed so
        # the plan machinery leaves it alone and the Week shows it done.
        if score is not None:
            execution.mark_day_completed(db, a.user_id, a.date)
    except Exception as e:  # noqa: BLE001
        log.debug("execution score failed for %s: %s", a.id, e)


def enrich_pending(db: Session, user_id: int, garmin,
                   limit: int = 30, throttle_s: float = 0.4) -> int:
    """Enrich up to `limit` of the user's unenriched activities (newest first).

    All activity types are enriched (for RPE/feel/body-battery); run-specific
    metrics are gated inside `enrich_activity`."""
    runs = db.scalars(
        select(Activity)
        .where(Activity.user_id == user_id, Activity.enriched.is_(False))
        .order_by(Activity.date.desc())
        .limit(limit)
    ).all()
    done = 0
    for a in runs:
        try:
            enrich_activity(db, garmin, a)
        except GarminConnectTooManyRequestsError:
            # Do NOT mark enriched — abort the pass and let a later sync retry.
            # Returning done (< limit) also stops the backfill's batch loop.
            log.warning("enrichment rate-limited at activity %s; stopping this pass", a.id)
            db.rollback()
            break
        except Exception as e:  # noqa: BLE001
            log.warning("enrichment failed for %s: %s", a.id, e)
            db.rollback()  # discard any half-flushed state before marking
            a.enriched = True  # data genuinely unavailable; don't retry forever
            db.add(a)
        db.commit()
        done += 1
        time.sleep(throttle_s)
    return done


def backfill_rpe_feel_bb(db: Session, user_id: int, garmin,
                         days: int = 30, throttle_s: float = 0.4) -> int:
    """One-shot: populate garmin_rpe/feel/body_battery_change on recent activities.

    Body-battery change is read from the already-stored summary `raw` (no call);
    RPE/feel need one get_activity() per activity. Targeted so we don't re-run the
    whole enrichment (zones/series/splits) just to pick up three new fields.
    Covers ALL activity types (walks/rides too). Returns the number updated.
    """
    since = dt.date.today() - dt.timedelta(days=days)
    runs = db.scalars(
        select(Activity)
        .where(Activity.user_id == user_id, Activity.date >= since)
        .order_by(Activity.date.desc())
    ).all()
    done = 0
    for a in runs:
        if a.body_battery_change is None:
            a.body_battery_change = (a.raw or {}).get("differenceBodyBattery")
        try:
            summary = (garmin.get_activity(a.id) or {}).get("summaryDTO") or {}
            a.garmin_rpe, a.feel = _rpe_feel(summary)
        except GarminConnectTooManyRequestsError:
            log.warning("rpe/feel backfill rate-limited at %s; stopping", a.id)
            db.rollback()
            break
        except Exception as e:  # noqa: BLE001
            log.warning("rpe/feel backfill failed for %s: %s", a.id, e)
        db.add(a)
        db.commit()
        done += 1
        time.sleep(throttle_s)
    log.info("rpe/feel/bb backfill: updated %d runs for user %d", done, user_id)
    return done
