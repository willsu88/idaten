"""Sleep endpoints (API_CONTRACT v1.43): /api/sleep daily list + /api/sleep/{date}
per-night detail parsed from the archived payload."""

from __future__ import annotations

import datetime as dt

from app.models import DailyHealth, SleepDetail
from tests.test_sleep_sync import DATE, _gmt_ms, full_sleep_payload


def _login(client):
    assert client.post("/api/auth/login",
                       json={"username": "will", "password": "secret1"}).status_code == 200


def test_sleep_endpoints_require_auth(client, db):
    assert client.get("/api/sleep").status_code == 401
    assert client.get(f"/api/sleep/{DATE.isoformat()}").status_code == 401


def test_daily_list_serves_trend_columns(client, db, user):
    today = dt.date.today()
    db.add(DailyHealth(
        user_id=user.id, date=today,
        sleep_seconds=26280, sleep_score=82,
        deep_seconds=5400, light_seconds=14400, rem_seconds=4800, awake_seconds=1680,
        nap_seconds=1320, nap_count=2, sleep_need_min=495,
        sleep_start_ts=dt.datetime(2026, 8, 13, 22, 30),
        sleep_end_ts=dt.datetime(2026, 8, 14, 6, 15),
        awake_count=2, restless_moments=28,
        avg_sleep_stress=15.0, avg_respiration=14.0,
        hrv=55.0, resting_hr=52, body_battery_change=49,
    ))
    # a pre-backfill day: legacy columns only
    db.add(DailyHealth(user_id=user.id, date=today - dt.timedelta(days=1),
                       sleep_seconds=25200, sleep_score=75))
    db.commit()
    _login(client)

    body = client.get("/api/sleep?days=7").json()
    by_date = {d["date"]: d for d in body["daily"]}

    d = by_date[today.isoformat()]
    assert d["sleep_hours"] == 7.3
    assert d["sleep_score"] == 82
    assert d["deep_hours"] == 1.5
    assert d["light_hours"] == 4.0
    assert d["rem_hours"] == 1.3
    assert d["awake_hours"] == 0.5
    assert d["nap_hours"] == 0.4
    assert d["nap_count"] == 2
    assert d["need_hours"] == 8.2
    assert d["bedtime"] == "2026-08-13T22:30:00"
    assert d["wake_time"] == "2026-08-14T06:15:00"
    assert d["awake_count"] == 2
    assert d["restless_moments"] == 28
    assert d["hrv"] == 55.0
    assert d["body_battery_change"] == 49

    legacy = by_date[(today - dt.timedelta(days=1)).isoformat()]
    assert legacy["sleep_hours"] == 7.0
    assert legacy["deep_hours"] is None
    assert legacy["bedtime"] is None


def test_detail_parses_archived_payload(client, db, user):
    db.add(SleepDetail(user_id=user.id, date=DATE, raw=full_sleep_payload()))
    db.commit()
    _login(client)

    body = client.get(f"/api/sleep/{DATE.isoformat()}").json()
    assert body["available"] is True
    assert body["date"] == DATE.isoformat()
    assert body["bedtime_ms"] == _gmt_ms(2026, 8, 14, 5, 30)
    assert body["wake_ms"] == _gmt_ms(2026, 8, 14, 13, 15)

    assert body["score"]["overall"] == 82
    assert body["score"]["qualifier"] == "GOOD"
    comp = body["score"]["components"]
    assert comp["deep_percentage"] == {"value": 21, "qualifier": "EXCELLENT",
                                       "optimal_start": 16.0, "optimal_end": 33.0}
    assert comp["restlessness"]["value"] is None
    assert "overall" not in comp

    assert body["stages"] == {"deep_s": 5400, "light_s": 14400, "rem_s": 4800,
                              "awake_s": 1680, "unmeasurable_s": 0}
    assert body["need"] == {"baseline_min": 480, "actual_min": 495,
                            "feedback": "NO_CHANGE_BALANCED",
                            "training_feedback": "NO_CHANGE",
                            "history_adjustment": "INCREASING",
                            "hrv_adjustment": "NO_CHANGE",
                            "nap_adjustment": "DECREASING"}

    assert body["naps"] == [
        {"start_ms": _gmt_ms(2026, 8, 14, 18, 21, 8),
         "end_ms": _gmt_ms(2026, 8, 14, 18, 33, 8),
         "seconds": 720, "feedback": "IDEAL_DURATION_LOW_NEED"},
        {"start_ms": _gmt_ms(2026, 8, 14, 21, 10, 30),
         "end_ms": _gmt_ms(2026, 8, 14, 21, 20, 30),
         "seconds": 600, "feedback": "MULTIPLE_NAPS_DURING_DAY"},
    ]

    assert body["hypnogram"] == [
        {"start_ms": _gmt_ms(2026, 8, 14, 5, 30), "end_ms": _gmt_ms(2026, 8, 14, 6, 0),
         "level": 1},
        {"start_ms": _gmt_ms(2026, 8, 14, 6, 0), "end_ms": _gmt_ms(2026, 8, 14, 6, 45),
         "level": 0},
    ]

    assert body["series"]["heart_rate"] == [{"t": _gmt_ms(2026, 8, 14, 5, 30), "v": 52}]
    assert body["series"]["hrv"] == [{"t": _gmt_ms(2026, 8, 14, 5, 35), "v": 55.0}]
    assert body["series"]["respiration"] == [{"t": _gmt_ms(2026, 8, 14, 5, 30), "v": 13.0}]

    assert body["physio"] == {"avg_overnight_hrv": 55.0, "hrv_status": "BALANCED",
                              "resting_hr": 52, "body_battery_change": 49,
                              "avg_sleep_stress": 15.0,
                              "respiration": {"low": None, "avg": 14.0, "high": None}}
    assert body["awake_count"] == 2
    assert body["restless_moments"] == 28


def test_detail_unavailable_when_not_archived(client, db, user):
    _login(client)
    body = client.get(f"/api/sleep/{DATE.isoformat()}").json()
    assert body == {"date": DATE.isoformat(), "available": False}


def test_detail_rejects_bad_date(client, db, user):
    _login(client)
    assert client.get("/api/sleep/not-a-date").status_code == 422
