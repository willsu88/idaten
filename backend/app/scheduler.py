"""Daily job: for each Garmin-connected user, sync -> regenerate plan -> auto-push.

Runs at the configured local hour via APScheduler. Because this lives inside a
Docker container on a laptop, a catch-up check runs at startup and every 30
minutes: if today's run hasn't happened yet and the plan hour has passed
(machine was asleep / container was down), the job fires immediately.
"""

from __future__ import annotations

import datetime as dt
import logging
import threading
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .config import config
from .db import session
from .garmin.client import has_garmin
from .garmin.push import push_days
from .garmin.sync import run_sync
from .metrics import has_recovery_data
from .models import DailyHealth, DailyReview, SyncLog, User
from .planner import evaluate_today, materialize_coach_plan, plan_mode
from .settings_store import get_settings

log = logging.getLogger(__name__)

_TZ = ZoneInfo(config.timezone)

_lock = threading.Lock()
_running = False

# Self-healing morning sync: throttle per user so a Today page that polls every
# few seconds doesn't spawn a sync on every poll while Garmin finishes the night.
_ENSURE_COOLDOWN_S = 180
_last_ensure: dict[int, dt.datetime] = {}


def is_running() -> bool:
    return _running


def now_local() -> dt.datetime:
    """Current time in the household zone (the zone plan_hour is defined in)."""
    return dt.datetime.now(_TZ)


def _as_local(d: dt.datetime) -> dt.datetime:
    """SQLite hands datetimes back naive; treat them as the UTC they were stored
    in, then view them in the household zone."""
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone.utc)
    return d.astimezone(_TZ)


def _review_done(db: Session, user_id: int, today: dt.date) -> bool:
    review = db.get(DailyReview, (user_id, today))
    return review is not None and review.state in ("done_full", "done_structural")


def _eager_review(db: Session, user: User, today: dt.date) -> None:
    """Eager morning review (ROADMAP Idea C decision): generate the coach's
    daily call right after the sync lands, so it exists before the athlete
    opens the app. Same content gate as the lazy path — never reviews on
    absent data (`catch_up` retries every 30 min until the night lands) — and
    a review failure must never fail the sync job; the lazy Today-page path
    recovers on the next visit."""
    if _review_done(db, user.id, today):
        return
    if not has_recovery_data(db.get(DailyHealth, (user.id, today))):
        return
    try:
        evaluate_today(db, user.id, today)
    except Exception:  # noqa: BLE001
        log.exception("eager daily review failed for user %d", user.id)
        db.rollback()


def _job_for_user(db: Session, user: User, source: str) -> dict:
    """Scheduled work: Garmin data + (editor mode) refresh the coach-plan base
    + the eager daily review once recovery data is present.

    Editor users get Garmin's plan materialized into plan_days as the base
    (override-safe); author users' weeks are written by the review itself."""
    synced_through = run_sync(db, user)
    today = dt.date.today()
    changed = []
    if plan_mode(db, user.id, today) == "editor":
        changed = materialize_coach_plan(db, user.id, today)
        settings = get_settings(db, user.id)
        if settings.get("auto_push_workouts") and changed:
            push_days(db, changed)
    db.add(SyncLog(user_id=user.id, status="ok",
                   detail=f"synced through {synced_through}",
                   plan_updated=bool(changed)))
    db.commit()
    _eager_review(db, user, today)
    return {"ok": True, "synced_through": synced_through, "plan_updated": bool(changed)}


def daily_job(source: str = "daily_job", only_user_id: int | None = None) -> dict:
    """Sync + replan + push for every connected user (or just one).

    Serialized; concurrent triggers return immediately. One user failing never
    blocks the others — each gets their own SyncLog row either way.
    """
    global _running
    if not _lock.acquire(blocking=False):
        return {"ok": False, "detail": "already running"}
    _running = True
    db = session()
    results: dict[int, dict] = {}
    try:
        users = db.scalars(select(User).order_by(User.id)).all()
        for user in users:
            if only_user_id is not None and user.id != only_user_id:
                continue
            if not has_garmin(user):
                continue
            try:
                results[user.id] = _job_for_user(db, user, source)
            except Exception as e:  # noqa: BLE001
                log.exception("daily job failed for user %d", user.id)
                db.rollback()
                db.add(SyncLog(user_id=user.id, status="error", detail=str(e)[:2000]))
                db.commit()
                results[user.id] = {"ok": False, "detail": str(e)}
    finally:
        db.close()
        _running = False
        _lock.release()

    if only_user_id is not None:
        return results.get(only_user_id, {"ok": False, "detail": "user has no Garmin connection"})
    ok = all(r.get("ok") for r in results.values()) if results else True
    return {"ok": ok, "users": results}


def sync_only_job(user_id: int) -> dict:
    """Manual 'Sync now': Garmin data + enrichment only — NO plan regeneration,
    no LLM call, no auto-push. Plan changes are the nightly job's (or the
    coach-in-chat's) business. Logged with kind='data' so catch-up still knows
    the day's real replan hasn't happened."""
    global _running
    if not _lock.acquire(blocking=False):
        return {"ok": False, "detail": "already running"}
    _running = True
    db = session()
    try:
        user = db.get(User, user_id)
        if user is None or not has_garmin(user):
            return {"ok": False, "detail": "user has no Garmin connection"}
        try:
            synced_through = run_sync(db, user)
            db.add(SyncLog(user_id=user_id, status="ok", kind="data",
                           detail=f"synced through {synced_through}"))
            db.commit()
            return {"ok": True, "synced_through": synced_through}
        except Exception as e:  # noqa: BLE001
            log.exception("manual sync failed for user %d", user_id)
            db.rollback()
            db.add(SyncLog(user_id=user_id, status="error", kind="data",
                           detail=str(e)[:2000]))
            db.commit()
            return {"ok": False, "detail": str(e)}
    finally:
        db.close()
        _running = False
        _lock.release()


def onboard_user(user_id: int) -> None:
    """Two-stage onboarding after Connect Garmin: a quick sync (first plan in
    ~a minute), then the deep-history backfill in the background."""
    from .garmin import backfill

    def run() -> None:
        result = daily_job(source="onboarding", only_user_id=user_id)
        if not result.get("ok"):
            log.error("onboarding quick sync failed for user %d: %s", user_id, result)
            return
        # daily_job holds the lock until it returns, so start() may briefly refuse
        for _ in range(30):
            if backfill.start(user_id, config.backfill_days):
                return
            threading.Event().wait(2.0)
        log.error("onboarding backfill could not start for user %d", user_id)

    threading.Thread(target=run, daemon=True).start()


def _ran_today_for_all(db: Session, now_local: dt.datetime) -> bool:
    users = db.scalars(select(User)).all()
    for user in users:
        if not has_garmin(user):
            continue
        # kind is NULL on pre-column rows — those were all full syncs
        last = db.scalars(
            select(SyncLog).where(SyncLog.user_id == user.id, SyncLog.status == "ok",
                                  or_(SyncLog.kind != "data", SyncLog.kind.is_(None)))
            .order_by(SyncLog.ran_at.desc()).limit(1)
        ).first()
        if last is None or _as_local(last.ran_at).date() < now_local.date():
            return False
    return True


def catch_up() -> None:
    from .garmin import backfill

    if backfill.any_running():
        return  # don't contend with a backfill; next interval check will catch up
    now_local = dt.datetime.now(_TZ)
    db = session()
    try:
        plan_hour = int(config.plan_hour)
        done = _ran_today_for_all(db, now_local)
    finally:
        db.close()
    if now_local.hour < plan_hour:
        return
    if not done:
        log.info("catch-up: daily job missed, running now")
        daily_job()
        return
    _retry_pending_reviews()


def _retry_pending_reviews() -> None:
    """Late-data retry, once per catch_up tick: the plan-hour sync ran but a
    review is still pending because Garmin hadn't processed the night (late
    sync, or a night that ends mid-day). Re-sync and evaluate once recovery
    data lands. Deliberately no cutoff — a rough night slept off in the
    afternoon still gets its review, and while data stays absent each tick
    costs one Garmin data sync and zero LLM calls (`_eager_review` gates)."""
    today = dt.date.today()
    db = session()
    try:
        users = db.scalars(select(User).order_by(User.id)).all()
        pending = [u.id for u in users
                   if has_garmin(u) and not _review_done(db, u.id, today)]
    finally:
        db.close()
    for user_id in pending:
        sync_only_job(user_id)
        db = session()
        try:
            user = db.get(User, user_id)
            if user is not None:
                _eager_review(db, user, today)
        finally:
            db.close()


def ensure_fresh_today(user_id: int) -> bool:
    """Self-healing data pull for the Today page: if today's recovery data hasn't
    landed yet, kick a background sync so the daily review is never left waiting
    on a mistimed cron (or a laptop that slept through it).

    Non-blocking and deduped: at most one sync per user per `_ENSURE_COOLDOWN_S`,
    and never while a sync/backfill is already running. Returns True when a sync
    is in flight or was just started (the caller can show "syncing…")."""
    from .garmin import backfill

    if _running or backfill.any_running():
        return True
    now = dt.datetime.now(dt.timezone.utc)
    last = _last_ensure.get(user_id)
    if last is not None and (now - last).total_seconds() < _ENSURE_COOLDOWN_S:
        return True
    _last_ensure[user_id] = now
    threading.Thread(target=sync_only_job, args=(user_id,), daemon=True).start()
    return True


def start_scheduler() -> BackgroundScheduler:
    # Explicit household zone so `hour=plan_hour` means local morning regardless
    # of the container clock (the UTC-container bug that fired the job at 2pm).
    sched = BackgroundScheduler(timezone=_TZ)
    sched.add_job(daily_job, "cron", hour=config.plan_hour, minute=5, id="daily")
    sched.add_job(catch_up, "interval", minutes=30, id="catch_up")
    sched.start()
    # Catch up shortly after boot without blocking startup
    threading.Timer(5.0, catch_up).start()
    return sched
