"""One-way race import: Garmin Connect calendar -> app races.

Garmin race events live on the calendar service (probed live 2026-07-17): items
with `isRace: true` carry title, date, a `completionTarget` distance, and a
`primaryEvent` flag. There is no reverse direction — races created in the app
are never sent to Garmin.

Rules (ROADMAP decision #5):
- Dedupe by Garmin event UUID, falling back to (name, date) to adopt races the
  user had already entered manually.
- Existing rows are never updated: app-side edits win.
- Garmin's primary race becomes our primary unless the user manually chose one
  (the `race_primary_manual` internal setting, set by the make-primary API).
- Races deleted in the app are tombstoned by UUID so they don't resurrect.
"""

from __future__ import annotations

import datetime as dt
import logging

from garminconnect import GarminConnectTooManyRequestsError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Race
from ..races import ensure_primary, set_primary
from ..settings_store import (
    DELETED_GARMIN_RACES_KEY,
    RACE_PRIMARY_OVERRIDE_KEY,
    get_internal,
)

log = logging.getLogger(__name__)

MONTHS_AHEAD = 12

_UNIT_TO_KM = {"kilometer": 1.0, "meter": 0.001, "mile": 1.609344}


def _distance_km(item: dict) -> float | None:
    target = item.get("completionTarget") or {}
    if target.get("unitType") != "distance" or not target.get("value"):
        return None
    factor = _UNIT_TO_KM.get(target.get("unit"))
    return round(float(target["value"]) * factor, 2) if factor else None


def fetch_race_events(garmin, today: dt.date, months_ahead: int = MONTHS_AHEAD) -> list[dict]:
    """Race calendar items for the coming months. calendar-service months are 0-based."""
    events: list[dict] = []
    year, month = today.year, today.month
    for _ in range(months_ahead + 1):
        try:
            payload = garmin.connectapi(f"/calendar-service/year/{year}/month/{month - 1}")
        except GarminConnectTooManyRequestsError:
            log.warning("race calendar rate-limited at %d-%02d; stopping this pass", year, month)
            break
        except Exception as e:  # noqa: BLE001
            log.debug("race calendar fetch failed for %d-%02d: %s", year, month, e)
            month, year = (1, year + 1) if month == 12 else (month + 1, year)
            continue
        events.extend(
            it for it in (payload or {}).get("calendarItems") or []
            if it.get("isRace") and it.get("itemType") == "event"
        )
        month, year = (1, year + 1) if month == 12 else (month + 1, year)
    return events


def sync_races(db: Session, user_id: int, garmin) -> int:
    """Import upcoming Garmin races for one user. Returns how many were created."""
    today = dt.date.today()
    tombstones = set(get_internal(db, user_id, DELETED_GARMIN_RACES_KEY, []) or [])
    manual_primary = bool(get_internal(db, user_id, RACE_PRIMARY_OVERRIDE_KEY, False))

    created = 0
    garmin_primary: Race | None = None
    for item in fetch_race_events(garmin, today):
        uuid = item.get("shareableEventUuid")
        name = (item.get("title") or "").strip()
        try:
            date = dt.date.fromisoformat(item.get("date") or "")
        except ValueError:
            continue
        if not name or date < today or (uuid and uuid in tombstones):
            continue

        race = None
        if uuid:
            race = db.scalars(select(Race).where(Race.user_id == user_id,
                                                 Race.garmin_uuid == uuid)).first()
        if race is None:
            # Adopt a manually entered duplicate instead of creating a second row
            race = db.scalars(select(Race).where(Race.user_id == user_id,
                                                 Race.name == name,
                                                 Race.date == date)).first()
            if race is not None and uuid and not race.garmin_uuid:
                race.garmin_uuid = uuid

        if race is None:
            distance_km = _distance_km(item)
            if not distance_km:
                continue  # a race row is meaningless without a distance
            race = Race(user_id=user_id, name=name, date=date, distance_km=distance_km,
                        source="garmin", garmin_uuid=uuid)
            db.add(race)
            created += 1
        # Existing rows: no field updates — app-side edits win.

        if item.get("primaryEvent"):
            garmin_primary = race

    db.commit()
    if garmin_primary is not None and not manual_primary and not garmin_primary.is_primary:
        set_primary(db, garmin_primary)
    ensure_primary(db, user_id)
    if created:
        log.info("user %d: imported %d race(s) from Garmin", user_id, created)
    return created
