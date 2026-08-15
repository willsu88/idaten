"""Step 6 of the sleep ticket: the coach sees stages, sleep need, and naps —
in the planner snapshot's health window and in the chat get_training_data tool."""

from __future__ import annotations

import datetime as dt
import json

from app.chat.tools import dispatch
from app.models import DailyHealth
from app.planner import build_snapshot

TODAY = dt.date.today()

SLEEP_FIELDS = {"deep_hours", "rem_hours", "need_hours", "nap_hours"}


def _health_row(user_id: int, date: dt.date) -> DailyHealth:
    return DailyHealth(
        user_id=user_id, date=date,
        sleep_seconds=26280, sleep_score=82, hrv=55.0,
        deep_seconds=5400, rem_seconds=4800,
        sleep_need_min=495, nap_seconds=1320,
    )


def test_snapshot_health_carries_sleep_detail(db, user):
    db.add(_health_row(user.id, TODAY))
    db.commit()

    row = build_snapshot(db, user.id, TODAY)["last_7_days_health"][-1]
    assert row["deep_hours"] == 1.5
    assert row["rem_hours"] == 1.3
    assert row["need_hours"] == 8.2
    assert row["nap_hours"] == 0.4


def test_get_training_data_carries_sleep_detail(db, user):
    db.add(_health_row(user.id, TODAY))
    # legacy day: fields present but null, not absent (a stable shape for the model)
    db.add(DailyHealth(user_id=user.id, date=TODAY - dt.timedelta(days=1),
                       sleep_seconds=25200, sleep_score=75))
    db.commit()

    result, _ = dispatch(db, user.id, "get_training_data", {
        "start_date": (TODAY - dt.timedelta(days=2)).isoformat(),
        "end_date": TODAY.isoformat(),
    })
    health = {h["date"]: h for h in json.loads(result)["health"]}
    today_row = health[TODAY.isoformat()]
    assert today_row["deep_hours"] == 1.5
    assert today_row["need_hours"] == 8.2
    legacy = health[(TODAY - dt.timedelta(days=1)).isoformat()]
    assert SLEEP_FIELDS <= set(legacy)
    assert all(legacy[f] is None for f in SLEEP_FIELDS)
