"""The chat coach must see Garmin's predicted time but NOT Idaten's generated
prediction (the calibrated likely_s range the app deliberately hides)."""
from __future__ import annotations

from app.chat.agent import _chat_race


def _race_dict():
    return {
        "id": 1,
        "name": "Goal Half",
        "date": "2026-11-01",
        "distance_km": 21.0975,
        "goal_time": "2:28:00",
        "is_primary": True,
        "source": "manual",
        "days_to_race": 40,
        "prediction": {
            "source": "idaten",
            "likely_s": 8880,        # Idaten's calibrated number — must be withheld
            "low_s": 8700,
            "high_s": 9100,
            "confidence": "medium",
            "delta_s": 0,
            "likely_pace": "7:00",
            "goal_time_s": 8880,
            "goal_pace": "7:00",
            "garmin_time_s": 7920,   # Garmin's predictor — allowed
        },
    }


def test_chat_race_withholds_idaten_prediction():
    out = _chat_race(_race_dict())
    # Garmin's number and the goal survive.
    assert out["garmin_predicted_time_s"] == 7920
    assert out["goal_time_s"] == 8880
    assert out["goal_pace"] == "7:00"
    # Idaten's generated prediction is gone entirely.
    assert "prediction" not in out
    for leaked in ("likely_s", "low_s", "high_s", "confidence", "delta_s", "likely_pace"):
        assert leaked not in out


def test_chat_race_handles_missing_prediction():
    out = _chat_race({"id": 1, "name": "X", "distance_km": 10.0})
    assert out["garmin_predicted_time_s"] is None
    assert "prediction" not in out
