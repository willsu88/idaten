"""Parse an archived Garmin sleep payload (sleep_detail.raw) into the
/api/sleep/{date} response shape (API_CONTRACT v1.43).

All instants come out as epoch ms GMT; the frontend renders browser-local.
Garmin mixes representations (epoch ms ints, ISO strings with and without
fractional seconds), so every timestamp goes through _ms().
"""

from __future__ import annotations

import datetime as dt
from typing import Any

_SCORE_COMPONENTS = {
    "totalDuration": "total_duration",
    "stress": "stress",
    "awakeCount": "awake_count",
    "restlessness": "restlessness",
    "remPercentage": "rem_percentage",
    "lightPercentage": "light_percentage",
    "deepPercentage": "deep_percentage",
}

_SERIES = {
    "heart_rate": ("sleepHeartRate", "startGMT", "value"),
    "hrv": ("hrvData", "startGMT", "value"),
    "stress": ("sleepStress", "startGMT", "value"),
    "body_battery": ("sleepBodyBattery", "startGMT", "value"),
    "respiration": ("wellnessEpochRespirationDataDTOList", "startTimeGMT", "respirationValue"),
}


def _ms(value: Any) -> int | None:
    """Epoch ms from any Garmin GMT timestamp representation."""
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        try:
            parsed = dt.datetime.fromisoformat(value)
        except ValueError:
            return None
        return int(parsed.replace(tzinfo=dt.timezone.utc).timestamp() * 1000)
    return None


def _points(raw: dict, key: str, t_key: str, v_key: str) -> list[dict]:
    out = []
    for p in raw.get(key) or []:
        t, v = _ms(p.get(t_key)), p.get(v_key)
        if t is not None and v is not None:
            out.append({"t": t, "v": v})
    return out


def detail_from_raw(date: dt.date, raw: dict) -> dict:
    dto = raw.get("dailySleepDTO") or {}
    scores = dto.get("sleepScores") or {}
    need = dto.get("sleepNeed") or {}

    components = {}
    for garmin_key, key in _SCORE_COMPONENTS.items():
        c = scores.get(garmin_key)
        if isinstance(c, dict):
            components[key] = {
                "value": c.get("value"),
                "qualifier": c.get("qualifierKey"),
                "optimal_start": c.get("optimalStart"),
                "optimal_end": c.get("optimalEnd"),
            }

    naps = []
    for n in dto.get("dailyNapDTOS") or []:
        naps.append({
            "start_ms": _ms(n.get("napStartTimestampGMT")),
            "end_ms": _ms(n.get("napEndTimestampGMT")),
            "seconds": n.get("napTimeSec"),
            "feedback": n.get("napFeedback"),
        })

    hypnogram = []
    for seg in raw.get("sleepLevels") or []:
        start, end = _ms(seg.get("startGMT")), _ms(seg.get("endGMT"))
        level = seg.get("activityLevel")
        if start is not None and end is not None and level is not None:
            hypnogram.append({"start_ms": start, "end_ms": end, "level": int(level)})

    return {
        "date": date.isoformat(),
        "available": True,
        "bedtime_ms": _ms(dto.get("sleepStartTimestampGMT")),
        "wake_ms": _ms(dto.get("sleepEndTimestampGMT")),
        "score": {
            "overall": (scores.get("overall") or {}).get("value"),
            "qualifier": (scores.get("overall") or {}).get("qualifierKey"),
            "components": components,
        },
        "stages": {
            "deep_s": dto.get("deepSleepSeconds"),
            "light_s": dto.get("lightSleepSeconds"),
            "rem_s": dto.get("remSleepSeconds"),
            "awake_s": dto.get("awakeSleepSeconds"),
            "unmeasurable_s": dto.get("unmeasurableSleepSeconds"),
        },
        "need": {
            "baseline_min": need.get("baseline"),
            "actual_min": need.get("actual"),
            "feedback": need.get("feedback"),
            "training_feedback": need.get("trainingFeedback"),
            "history_adjustment": need.get("sleepHistoryAdjustment"),
            "hrv_adjustment": need.get("hrvAdjustment"),
            "nap_adjustment": need.get("napAdjustment"),
        },
        "naps": naps,
        "hypnogram": hypnogram,
        "series": {name: _points(raw, *spec) for name, spec in _SERIES.items()},
        "physio": {
            "avg_overnight_hrv": raw.get("avgOvernightHrv"),
            "hrv_status": raw.get("hrvStatus"),
            "resting_hr": raw.get("restingHeartRate"),
            "body_battery_change": raw.get("bodyBatteryChange"),
            "avg_sleep_stress": dto.get("avgSleepStress"),
            "respiration": {
                "low": dto.get("lowestRespirationValue"),
                "avg": dto.get("averageRespirationValue"),
                "high": dto.get("highestRespirationValue"),
            },
        },
        "awake_count": dto.get("awakeCount"),
        "restless_moments": raw.get("restlessMomentsCount"),
    }
