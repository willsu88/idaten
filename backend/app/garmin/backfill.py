"""One-shot deep history backfill (e.g. 300 days), run as a background thread.

Per-user: state, lock, and thread are keyed by user id, so one household
member's onboarding backfill doesn't block another's. Writes oldest-first so
charts fill in progressively; throttled to stay clear of Garmin's rate limits.
Progress is exposed via `progress(user_id)` and surfaced on /api/sync/status.
"""

from __future__ import annotations

import datetime as dt
import logging
import threading
import time

from garminconnect import GarminConnectTooManyRequestsError

from ..db import session
from ..models import User
from .client import get_garmin
from .enrich import enrich_pending
from .sync import sync_activities, sync_fitness_day, sync_health_day

log = logging.getLogger(__name__)

_states: dict[int, dict] = {}
_locks: dict[int, threading.Lock] = {}
_registry_lock = threading.Lock()

ACTIVITY_CHUNK_DAYS = 30
HEALTH_THROTTLE_S = 1.0     # Garmin throttles wellness endpoints hard; stay gentle
VO2MAX_EVERY_DAYS = 7       # VO2max moves slowly; weekly samples are plenty
RATE_LIMIT_BACKOFF_S = 120  # wait when Garmin returns 429, then retry the same day
MAX_BACKOFFS_PER_DAY = 5


def _user_lock(user_id: int) -> threading.Lock:
    with _registry_lock:
        return _locks.setdefault(user_id, threading.Lock())


def progress(user_id: int) -> dict | None:
    state = _states.get(user_id)
    if state is None or (not state["running"] and state["done_days"] == 0):
        return None
    return dict(state)


def any_running() -> bool:
    return any(s.get("running") for s in _states.values())


def start(user_id: int, days: int) -> bool:
    """Kick off the backfill thread for a user. Returns False if one is running."""
    from .. import scheduler

    if scheduler.is_running():
        return False  # let the daily job finish; they'd contend for the DB
    lock = _user_lock(user_id)
    if not lock.acquire(blocking=False):
        return False
    _states[user_id] = {"running": True, "done_days": 0, "total_days": days}
    threading.Thread(target=_run, args=(user_id, days, lock), daemon=True).start()
    return True


def _run(user_id: int, days: int, lock: threading.Lock) -> None:
    state = _states[user_id]
    db = session()
    try:
        user = db.get(User, user_id)
        garmin = get_garmin(user)
        end = dt.date.today()
        start_date = end - dt.timedelta(days=days)

        # Activities in 30-day chunks, oldest first
        chunk_start = start_date
        while chunk_start < end:
            chunk_end = min(chunk_start + dt.timedelta(days=ACTIVITY_CHUNK_DAYS - 1), end)
            try:
                sync_activities(db, user_id, garmin, chunk_start, chunk_end)
                db.commit()
            except Exception as e:  # noqa: BLE001
                log.warning("backfill activities %s..%s failed: %s", chunk_start, chunk_end, e)
                db.rollback()
            chunk_start = chunk_end + dt.timedelta(days=1)
            time.sleep(1.0)

        # Daily health + weekly VO2max samples, oldest first.
        # On a 429 we back off and RETRY THE SAME DAY — advancing would silently
        # leave a hole for every day Garmin throttles us.
        d = start_date
        backoffs = 0
        while d <= end:
            try:
                sync_health_day(db, user_id, garmin, d)
                if (end - d).days % VO2MAX_EVERY_DAYS == 0:
                    sync_fitness_day(db, user_id, garmin, d)
                db.commit()
            except GarminConnectTooManyRequestsError:
                backoffs += 1
                if backoffs > MAX_BACKOFFS_PER_DAY:
                    log.error("backfill: persistent rate limiting at %s, giving up on health phase", d)
                    break
                log.warning("backfill: rate limited at %s, backing off %ds (attempt %d)",
                            d, RATE_LIMIT_BACKOFF_S, backoffs)
                db.rollback()
                time.sleep(RATE_LIMIT_BACKOFF_S)
                continue  # retry the same day
            except Exception as e:  # noqa: BLE001
                log.warning("backfill health %s failed: %s", d, e)
                db.rollback()  # a poisoned session would fail every later commit
            backoffs = 0
            state["done_days"] += 1
            d += dt.timedelta(days=1)
            time.sleep(HEALTH_THROTTLE_S)

        # Re-attempt runs whose earlier enrichment produced nothing (e.g. it was
        # rate-limited and marked done), then enrich everything outstanding.
        from sqlalchemy import update

        from ..models import Activity
        from .enrich import RUN_TYPES

        db.execute(
            update(Activity)
            .where(Activity.user_id == user_id,
                   Activity.type.in_(RUN_TYPES), Activity.enriched.is_(True),
                   Activity.time_in_zones.is_(None), Activity.hr_drift_pct.is_(None))
            .values(enriched=False)
        )
        db.commit()
        while enrich_pending(db, user_id, garmin, limit=25, throttle_s=0.8) == 25:
            log.info("backfill enrichment batch done, continuing")
        log.info("backfill of %d days complete for user %d", days, user_id)
    except Exception:  # noqa: BLE001
        log.exception("backfill failed for user %d", user_id)
    finally:
        db.close()
        state["running"] = False
        lock.release()
