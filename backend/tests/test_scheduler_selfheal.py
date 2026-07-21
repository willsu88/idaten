"""Morning self-heal: the scheduler runs in the household zone (not the UTC
container clock), and ensure_fresh_today kicks a deduped background sync so the
daily review never waits on a mistimed cron."""

from __future__ import annotations

import datetime as dt
import threading

from app import scheduler
from app.garmin import backfill as gc_backfill
from app.metrics import has_recovery_data
from app.models import DailyHealth


def test_has_recovery_data_needs_content():
    assert has_recovery_data(None) is False
    # A bare row (sync ran before Garmin processed the night) is NOT ready.
    assert has_recovery_data(DailyHealth(user_id=1, date=dt.date(2026, 7, 18))) is False
    assert has_recovery_data(
        DailyHealth(user_id=1, date=dt.date(2026, 7, 18), sleep_score=80)) is True
    assert has_recovery_data(
        DailyHealth(user_id=1, date=dt.date(2026, 7, 18), hrv=48)) is True


def _reset_ensure():
    scheduler._running = False
    scheduler._last_ensure.clear()


def test_ensure_fresh_today_spawns_once_then_cools_down(monkeypatch):
    _reset_ensure()
    calls: list[int] = []
    fired = threading.Event()

    def stub(user_id):
        calls.append(user_id)
        fired.set()

    monkeypatch.setattr(scheduler, "sync_only_job", stub)
    monkeypatch.setattr(gc_backfill, "any_running", lambda: False)

    assert scheduler.ensure_fresh_today(1) is True
    assert fired.wait(2.0)  # background thread ran the sync
    assert calls == [1]

    # A second call within the cooldown must NOT spawn another sync.
    scheduler.ensure_fresh_today(1)
    assert calls == [1]


def test_ensure_fresh_today_skips_while_a_sync_is_running(monkeypatch):
    _reset_ensure()
    calls: list[int] = []
    monkeypatch.setattr(scheduler, "sync_only_job", lambda uid: calls.append(uid))
    monkeypatch.setattr(gc_backfill, "any_running", lambda: False)
    scheduler._running = True  # a daily job is mid-flight

    scheduler.ensure_fresh_today(1)
    assert calls == []  # never piles on a running sync
    _reset_ensure()


def test_scheduler_uses_household_zone():
    # The cron must fire in the configured zone, not the container's UTC clock.
    from app.config import config

    assert str(scheduler._TZ) == config.timezone


def test_as_local_converts_naive_utc():
    # SQLite hands back naive UTC; _as_local views it in the household zone.
    naive_utc = dt.datetime(2026, 7, 18, 6, 0, 0)  # 06:00 UTC
    local = scheduler._as_local(naive_utc)
    assert local.tzinfo is not None
    # Asia/Taipei is UTC+8 → 14:00 local.
    if str(scheduler._TZ) == "Asia/Taipei":
        assert local.hour == 14
