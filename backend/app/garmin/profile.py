"""Athlete profile from Garmin (gender, weight, height, LTHR, VO2max).

Refreshed during the daily sync into the internal `garmin_profile` settings key;
the Athlete card shows these read-only and the planner/chat prompts consume them
(LTHR anchors the HR zones used by hr/hybrid training modes).
"""

from __future__ import annotations

import datetime as dt
import logging

from sqlalchemy.orm import Session

from ..settings_store import GARMIN_PROFILE_KEY, put_internal

log = logging.getLogger(__name__)


def parse_user_data(user_data: dict) -> dict:
    weight = user_data.get("weight")  # grams
    gender = user_data.get("gender")
    return {
        "gender": gender.lower() if isinstance(gender, str) else None,
        "weight_kg": round(weight / 1000, 1) if weight else None,
        "height_cm": user_data.get("height"),
        "birth_date": user_data.get("birthDate"),
        "lthr": user_data.get("lactateThresholdHeartRate"),
        "vo2max_running": user_data.get("vo2MaxRunning"),
        "fetched_at": dt.date.today().isoformat(),
    }


def sync_profile(db: Session, user_id: int, garmin) -> None:
    """Best-effort profile refresh; never fails the surrounding sync."""
    try:
        user_data = (garmin.get_user_profile() or {}).get("userData") or {}
    except Exception as e:  # noqa: BLE001
        log.debug("profile fetch failed for user %d: %s", user_id, e)
        return
    if not user_data:
        return
    put_internal(db, user_id, GARMIN_PROFILE_KEY, parse_user_data(user_data))
