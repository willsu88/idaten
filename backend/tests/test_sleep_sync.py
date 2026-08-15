"""Sleep ingestion: sync_health_day widens the parse of get_sleep_data and
stores the payload verbatim in sleep_detail (ticket: .scratch/sleep-page)."""

from __future__ import annotations

import datetime as dt

import pytest

from app.garmin.sync import sync_health_day
from app.models import DailyHealth, SleepDetail
from tests.conftest import make_user

DATE = dt.date(2026, 8, 14)


def _local_ms(*args) -> int:
    """Garmin 'Local' timestamps: epoch ms whose UTC reading is local wall time."""
    return int(dt.datetime(*args, tzinfo=dt.timezone.utc).timestamp() * 1000)


def _gmt_ms(*args) -> int:
    return int(dt.datetime(*args, tzinfo=dt.timezone.utc).timestamp() * 1000)


def full_sleep_payload() -> dict:
    return {
        "dailySleepDTO": {
            "calendarDate": DATE.isoformat(),
            "sleepTimeSeconds": 26280,
            "napTimeSeconds": 1320,
            "sleepStartTimestampGMT": _gmt_ms(2026, 8, 14, 5, 30),
            "sleepEndTimestampGMT": _gmt_ms(2026, 8, 14, 13, 15),
            "sleepStartTimestampLocal": _local_ms(2026, 8, 13, 22, 30),
            "sleepEndTimestampLocal": _local_ms(2026, 8, 14, 6, 15),
            "unmeasurableSleepSeconds": 0,
            "deepSleepSeconds": 5400,
            "lightSleepSeconds": 14400,
            "remSleepSeconds": 4800,
            "awakeSleepSeconds": 1680,
            "awakeCount": 2,
            "avgSleepStress": 15.0,
            "averageRespirationValue": 14.0,
            "sleepScores": {
                "overall": {"value": 82, "qualifierKey": "GOOD"},
                "deepPercentage": {"value": 21, "qualifierKey": "EXCELLENT",
                                   "optimalStart": 16.0, "optimalEnd": 33.0},
                "remPercentage": {"value": 18, "qualifierKey": "FAIR",
                                  "optimalStart": 21.0, "optimalEnd": 31.0},
                "restlessness": {"qualifierKey": "FAIR",
                                 "optimalStart": 0.0, "optimalEnd": 5.0},
            },
            "sleepNeed": {"baseline": 480, "actual": 495,
                          "feedback": "NO_CHANGE_BALANCED",
                          "trainingFeedback": "NO_CHANGE",
                          "sleepHistoryAdjustment": "INCREASING",
                          "hrvAdjustment": "NO_CHANGE",
                          "napAdjustment": "DECREASING"},
            "dailyNapDTOS": [
                {"napTimeSec": 720, "napFeedback": "IDEAL_DURATION_LOW_NEED",
                 "napStartTimestampGMT": "2026-08-14T18:21:08",
                 "napEndTimestampGMT": "2026-08-14T18:33:08"},
                {"napTimeSec": 600, "napFeedback": "MULTIPLE_NAPS_DURING_DAY",
                 "napStartTimestampGMT": "2026-08-14T21:10:30",
                 "napEndTimestampGMT": "2026-08-14T21:20:30"},
            ],
        },
        "sleepLevels": [
            {"startGMT": "2026-08-14T05:30:00.0", "endGMT": "2026-08-14T06:00:00.0",
             "activityLevel": 1.0},
            {"startGMT": "2026-08-14T06:00:00.0", "endGMT": "2026-08-14T06:45:00.0",
             "activityLevel": 0.0},
        ],
        "sleepHeartRate": [{"value": 52, "startGMT": _gmt_ms(2026, 8, 14, 5, 30)}],
        "hrvData": [{"value": 55.0, "startGMT": _gmt_ms(2026, 8, 14, 5, 35)}],
        "sleepStress": [{"value": 12, "startGMT": _gmt_ms(2026, 8, 14, 5, 30)}],
        "sleepBodyBattery": [{"value": 40, "startGMT": _gmt_ms(2026, 8, 14, 5, 30)}],
        "wellnessEpochRespirationDataDTOList": [
            {"startTimeGMT": _gmt_ms(2026, 8, 14, 5, 30), "respirationValue": 13.0},
        ],
        "avgOvernightHrv": 55.0,
        "hrvStatus": "BALANCED",
        "restingHeartRate": 52,
        "restlessMomentsCount": 28,
        "bodyBatteryChange": 49,
    }


class FakeGarmin:
    """Only the sleep endpoint answers; every other metric fails (partial data
    is normal and swallowed per-metric)."""

    def __init__(self, sleep):
        self._sleep = sleep

    def get_sleep_data(self, cdate):
        return self._sleep

    def __getattr__(self, name):
        def boom(*a, **k):
            raise RuntimeError(f"{name} unavailable")
        return boom


def test_full_payload_populates_columns_and_detail(db):
    user = make_user(db)
    sync_health_day(db, user.id, FakeGarmin(full_sleep_payload()), DATE)
    db.commit()

    row = db.get(DailyHealth, (user.id, DATE))
    assert row.sleep_seconds == 26280
    assert row.sleep_score == 82
    assert row.deep_seconds == 5400
    assert row.light_seconds == 14400
    assert row.rem_seconds == 4800
    assert row.awake_seconds == 1680
    assert row.awake_count == 2
    assert row.restless_moments == 28
    assert row.avg_sleep_stress == 15.0
    assert row.avg_respiration == 14.0
    assert row.nap_seconds == 1320
    assert row.nap_count == 2
    assert row.sleep_need_min == 495
    assert row.sleep_start_ts == dt.datetime(2026, 8, 13, 22, 30)
    assert row.sleep_end_ts == dt.datetime(2026, 8, 14, 6, 15)
    assert row.body_battery_change == 49

    detail = db.get(SleepDetail, (user.id, DATE))
    assert detail is not None
    assert detail.raw == full_sleep_payload()


def test_partial_payload_leaves_missing_fields_null(db):
    user = make_user(db)
    partial = {"dailySleepDTO": {"sleepTimeSeconds": 20000}}
    sync_health_day(db, user.id, FakeGarmin(partial), DATE)
    db.commit()

    row = db.get(DailyHealth, (user.id, DATE))
    assert row.sleep_seconds == 20000
    for field in ("sleep_score", "deep_seconds", "awake_count", "nap_count",
                  "sleep_need_min", "sleep_start_ts", "restless_moments",
                  "body_battery_change"):
        assert getattr(row, field) is None, field
    # dto was non-empty, so the payload is still archived verbatim
    assert db.get(SleepDetail, (user.id, DATE)).raw == partial


def test_no_sleep_data_stores_no_detail_row(db):
    """An empty payload (watch not worn) writes nulls and no archive row."""
    user = make_user(db)
    sync_health_day(db, user.id, FakeGarmin({}), DATE)
    db.commit()

    row = db.get(DailyHealth, (user.id, DATE))
    assert row is not None
    assert row.sleep_seconds is None
    assert db.get(SleepDetail, (user.id, DATE)) is None


def test_failed_fetch_stores_no_detail_row(db):
    user = make_user(db)
    garmin = FakeGarmin({})
    garmin._sleep = None  # get_sleep_data returning None must not crash the day
    sync_health_day(db, user.id, garmin, DATE)
    db.commit()
    assert db.get(SleepDetail, (user.id, DATE)) is None


def test_resync_overwrites_detail(db):
    user = make_user(db)
    sync_health_day(db, user.id, FakeGarmin(full_sleep_payload()), DATE)
    db.commit()
    updated = full_sleep_payload()
    updated["restlessMomentsCount"] = 30
    sync_health_day(db, user.id, FakeGarmin(updated), DATE)
    db.commit()

    assert db.get(DailyHealth, (user.id, DATE)).restless_moments == 30
    assert db.get(SleepDetail, (user.id, DATE)).raw["restlessMomentsCount"] == 30
