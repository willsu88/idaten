"""Injury / niggle tracking — the fourth deterministic review signal.

The athlete reports pain (via chat tools or the UI), it persists as an open
`Niggle` row, and the open set is handed to the daily review as
`active_niggles` grounding so the coach biases the plan down until it clears.
The model SUGGESTS through the existing PendingEdit machinery; nothing here
gates the plan deterministically.

Check-in posture (decided with Will 2026-07-21): pain reporting is
athlete-initiated — the only prompt we ever show is a gentle check-in after a
severity-scaled quiet window (7 days for a minor niggle, 14 for pain/injury,
since real injuries take weeks and asking sooner is a nag). "Still sore"
re-arms the window; resolving via chat ("my knee is fine now") and tapping
Resolved on the card are the same row update.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Niggle

SEVERITY_LABELS = {1: "niggle", 2: "pain", 3: "injury"}
# Days of silence before the "still bothered?" check-in appears, per severity.
CHECKIN_DAYS = {1: 7, 2: 14, 3: 14}


def _clamp_severity(severity) -> int:
    try:
        return min(3, max(1, int(severity)))
    except (TypeError, ValueError):
        return 1


def niggle_dict(n: Niggle, today: dt.date) -> dict:
    days_open = max(0, (today - n.onset_date).days)
    anchor = max(n.onset_date, n.checkin_date or n.onset_date)
    show_checkin = (today - anchor).days >= CHECKIN_DAYS[_clamp_severity(n.severity)]
    return {
        "id": n.id,
        "body_part": n.body_part,
        "severity": _clamp_severity(n.severity),
        "severity_label": SEVERITY_LABELS[_clamp_severity(n.severity)],
        "onset_date": n.onset_date.isoformat(),
        "days_open": days_open,
        "note": n.note or "",
        "show_checkin": show_checkin,
    }


def open_niggles(db: Session, user_id: int) -> list[Niggle]:
    return list(db.scalars(
        select(Niggle)
        .where(Niggle.user_id == user_id, Niggle.resolved_date.is_(None))
        .order_by(Niggle.severity.desc(), Niggle.onset_date)
    ))


def active_niggles(db: Session, user_id: int, today: dt.date) -> list[dict] | None:
    """The open-niggle signal for snapshots and the Today payload.

    None (not []) when the athlete has nothing open, so the review prompt's
    'only present when reported' framing holds and the payload stays quiet."""
    rows = open_niggles(db, user_id)
    if not rows:
        return None
    return [niggle_dict(n, today) for n in rows]


def log_niggle(db: Session, user_id: int, body_part: str, severity,
               note: str = "", onset_date: dt.date | None = None,
               source: str = "chat") -> Niggle:
    """Open a niggle — or update the existing open one for the same body part
    (the athlete mentioning their knee twice is one knee, not two rows)."""
    today = dt.date.today()
    onset = onset_date or today
    if onset > today:
        onset = today
    part = " ".join(body_part.strip().lower().split())
    existing = next((n for n in open_niggles(db, user_id)
                     if n.body_part.lower() == part), None)
    if existing is not None:
        existing.severity = _clamp_severity(severity)
        if note:
            existing.note = note
        if onset < existing.onset_date:
            existing.onset_date = onset
        db.commit()
        return existing
    n = Niggle(user_id=user_id, body_part=part, severity=_clamp_severity(severity),
               onset_date=onset, note=note or "", source=source)
    db.add(n)
    db.commit()
    return n


def get_own(db: Session, user_id: int, niggle_id: int) -> Niggle | None:
    n = db.get(Niggle, niggle_id)
    if n is None or n.user_id != user_id:
        return None
    return n


def resolve_niggle(db: Session, user_id: int, niggle_id: int) -> Niggle | None:
    n = get_own(db, user_id, niggle_id)
    if n is None:
        return None
    n.resolved_date = dt.date.today()
    db.commit()
    return n


def checkin_niggle(db: Session, user_id: int, niggle_id: int) -> Niggle | None:
    """'Still sore' — keep it open and re-arm the check-in window."""
    n = get_own(db, user_id, niggle_id)
    if n is None:
        return None
    n.checkin_date = dt.date.today()
    db.commit()
    return n
