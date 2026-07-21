"""Garmin gear (shoes): mirror, per-activity labels, swap writes, predictor.

Reads use the `garminconnect` wrappers. The link/unlink writes hit the same
endpoints the Garmin Connect web app uses — PUT /gear-service/gear/link/…
and PUT /gear-service/gear/unlink/… (DELETE is a 405; unlink is its own PUT
path). Per-activity labels are bulk-loaded with one get_gear_activities call
per shoe instead of one call per activity, so relabeling the whole history
costs about as many requests as the athlete owns shoes.

The predictor is a frequency table, not a model: Idaten planned the workout,
so P(shoe | workout_type) over the athlete's own history is the signal. Free
runs fall back to a pace band. Suggestions are one-tap, never auto-applied.
"""

from __future__ import annotations

import datetime as dt
import logging
import time
from collections import Counter, defaultdict

from garminconnect import GarminConnectTooManyRequestsError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Activity, Gear, PlanDay, utcnow

log = logging.getLogger(__name__)

RUN_TYPES = ("running", "trail_running", "track_running", "treadmill_running")
THROTTLE_S = 0.4

# Suggest only when the athlete's own history is emphatic about the bucket.
MIN_SAMPLES = 5
MIN_SHARE = 0.7
HISTORY_DAYS = 365
SUGGEST_WINDOW_DAYS = 21


# --- Garmin writes -----------------------------------------------------------

def _gear_request(garmin, verb: str, gear_uuid: str, activity_id: int):
    path = f"/gear-service/gear/{verb}/{gear_uuid}/activity/{int(activity_id)}"
    return garmin.client.request("PUT", "connectapi", path, api=True)


def set_activity_gear(db: Session, garmin, activity: Activity,
                      new_uuid: str | None) -> None:
    """Swap the shoe on a Garmin activity, then mirror locally.

    Garmin allows several gear items per activity; only Shoes-type entries are
    touched so a paired bike/watch band stays put. Garmin state is read live
    (not from our mirror) so a swap made in Garmin's UI since the last sync
    can't leave a second shoe linked.
    """
    current = garmin.get_activity_gear(activity.id) or []
    for g in current:
        if g.get("gearTypeName") == "Shoes" and g.get("uuid") != new_uuid:
            _gear_request(garmin, "unlink", g["uuid"], activity.id)
    if new_uuid and not any(g.get("uuid") == new_uuid for g in current):
        _gear_request(garmin, "link", new_uuid, activity.id)
    activity.gear_uuid = new_uuid
    db.commit()


# --- sync mirror -------------------------------------------------------------

def sync_gear(db: Session, user_id: int, garmin) -> int:
    """Mirror the gear list, per-shoe totals, and per-activity shoe labels.

    Overwrite-only on labels: an activity Garmin no longer lists for any shoe
    keeps its stale label until the athlete touches it — clearing safely would
    require knowing every shoe's full activity list is complete, which the
    paged endpoint can't promise.
    """
    profile_id = (garmin.get_user_profile() or {}).get("id")
    if not profile_id:
        log.warning("gear sync skipped for user %d: no Garmin profile id", user_id)
        return 0

    items = garmin.get_gear(profile_id) or []
    seen: set[str] = set()
    for item in items:
        uuid = item.get("uuid")
        if not uuid:
            continue
        seen.add(uuid)
        row = db.get(Gear, uuid) or Gear(uuid=uuid, user_id=user_id)
        row.user_id = user_id
        row.name = (item.get("customMakeModel") or item.get("displayName")
                    or f"{item.get('gearMakeName', '')} {item.get('gearModelName', '')}".strip())
        row.make = item.get("gearMakeName") or ""
        row.model = item.get("gearModelName") or ""
        row.gear_type = item.get("gearTypeName") or ""
        row.status = item.get("gearStatusName") or "active"
        row.maximum_meters = item.get("maximumMeters")
        begin = (item.get("dateBegin") or "")[:10]
        try:
            row.date_begin = dt.date.fromisoformat(begin)
        except ValueError:
            pass
        row.synced_at = utcnow()
        db.merge(row)

    # Gear deleted on Garmin's side disappears from the mirror too.
    for row in db.scalars(select(Gear).where(Gear.user_id == user_id)):
        if row.uuid not in seen:
            db.delete(row)
    db.commit()

    labeled = 0
    for uuid in seen:
        row = db.get(Gear, uuid)
        if row is None or row.gear_type != "Shoes":
            continue
        time.sleep(THROTTLE_S)
        try:
            stats = garmin.get_gear_stats(uuid) or {}
            row.total_distance_m = stats.get("totalDistance")
            row.total_activities = stats.get("totalActivities")
        except GarminConnectTooManyRequestsError:
            raise
        except Exception as e:  # noqa: BLE001
            log.debug("gear stats failed for %s: %s", uuid, e)

        time.sleep(THROTTLE_S)
        try:
            acts = garmin.get_gear_activities(uuid) or []
        except GarminConnectTooManyRequestsError:
            raise
        except Exception as e:  # noqa: BLE001
            log.debug("gear activities failed for %s: %s", uuid, e)
            continue
        ids = [a.get("activityId") for a in acts if a.get("activityId")]
        for chunk_start in range(0, len(ids), 500):
            chunk = ids[chunk_start:chunk_start + 500]
            for a in db.scalars(select(Activity).where(
                    Activity.user_id == user_id, Activity.id.in_(chunk))):
                if a.gear_uuid != uuid:
                    a.gear_uuid = uuid
                    labeled += 1
        db.commit()

    log.info("user %d: gear mirror %d items, %d activity labels updated",
             user_id, len(seen), labeled)
    return labeled


# --- shoe predictor ----------------------------------------------------------

def _pace_band(avg_speed_mps: float | None) -> str:
    """Coarse effort proxy for free runs (no planned workout to key on)."""
    if not avg_speed_mps or avg_speed_mps <= 0:
        return "unknown"
    pace_s_per_km = 1000 / avg_speed_mps
    if pace_s_per_km < 285:      # faster than 4:45/km
        return "fast"
    if pace_s_per_km < 330:      # 4:45–5:30/km
        return "steady"
    return "easy"


# Workout labels recognized in activity names ("Xindian District - Tempo",
# bare "Base", ...). Both Garmin Coach and Idaten-pushed workouts stamp these,
# which matters because plan_days only keeps a rolling window — for history,
# the name is the only surviving record of what the run was.
_NAME_LABELS = {
    "base": "base", "tempo": "tempo", "threshold": "threshold",
    "long run": "long_run", "recovery": "recovery", "anaerobic": "anaerobic",
    "sprint": "sprint", "easy": "easy_run", "easy run": "easy_run",
    "intervals": "intervals", "race": "race",
}


def _name_label(name: str) -> str | None:
    tail = (name or "").rsplit(" - ", 1)[-1].strip().lower()
    return _NAME_LABELS.get(tail)


def _bucket(a: Activity, plan_types: dict[dt.date, str]) -> str:
    # Name label first: it exists for history AND recent runs, so buckets stay
    # keyed consistently; the plan window only covers days plan_days retains.
    wt = _name_label(a.name) or plan_types.get(a.date)
    return f"plan:{wt}" if wt else f"pace:{_pace_band(a.avg_speed_mps)}"


def _history(db: Session, user_id: int) -> tuple[list[Activity], dict[dt.date, str]]:
    since = dt.date.today() - dt.timedelta(days=HISTORY_DAYS)
    acts = list(db.scalars(
        select(Activity).where(
            Activity.user_id == user_id,
            Activity.date >= since,
            Activity.type.in_(RUN_TYPES),
            Activity.gear_uuid.is_not(None),
        )
    ))
    plan_types = {
        p.date: p.workout_type
        for p in db.scalars(select(PlanDay).where(
            PlanDay.user_id == user_id, PlanDay.date >= since))
        if p.workout_type not in ("rest", None)
    }
    return acts, plan_types


def gear_suggestions(db: Session, user_id: int) -> list[dict]:
    """Recent runs whose shoe disagrees with the athlete's own strong habit.

    Frequency table P(shoe | bucket) over the last year; a suggestion needs
    MIN_SAMPLES runs in the bucket and MIN_SHARE agreement. Dismissed ones
    never come back.
    """
    acts, plan_types = _history(db, user_id)
    active_shoes = {
        g.uuid: g for g in db.scalars(select(Gear).where(
            Gear.user_id == user_id, Gear.gear_type == "Shoes",
            Gear.status == "active"))
    }

    counts: dict[str, Counter] = defaultdict(Counter)
    for a in acts:
        if a.gear_uuid in active_shoes:
            counts[_bucket(a, plan_types)][a.gear_uuid] += 1

    window = dt.date.today() - dt.timedelta(days=SUGGEST_WINDOW_DAYS)
    out = []
    for a in sorted(acts, key=lambda x: x.date, reverse=True):
        if a.date < window or a.gear_suggestion_dismissed:
            continue
        bucket = _bucket(a, plan_types)
        tally = counts[bucket]
        n = sum(tally.values())
        if n < MIN_SAMPLES:
            continue
        top_uuid, top_count = tally.most_common(1)[0]
        if top_uuid == a.gear_uuid or top_uuid not in active_shoes:
            continue
        # Exclude this activity's own vote: its (possibly wrong) label
        # shouldn't dilute the habit it deviates from.
        own = 1 if a.gear_uuid in active_shoes else 0
        share = top_count / max(n - own, 1)
        if share < MIN_SHARE:
            continue
        current = db.get(Gear, a.gear_uuid) if a.gear_uuid else None
        out.append({
            "activity_id": a.id,
            "date": a.date.isoformat(),
            "activity_name": a.name,
            "bucket": bucket,
            "current": {"uuid": a.gear_uuid,
                        "name": current.name if current else None},
            "suggested": {"uuid": top_uuid,
                          "name": active_shoes[top_uuid].name},
            "confidence": round(share, 2),
            "sample_size": n,
        })
    return out
