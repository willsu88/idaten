"""The strength lane — planned support sessions beside the run plan.

Strength-only for now (the `kind` column leaves room for mobility/cross later).
The lane is deliberately separate from plan_days: editor-mode materialization,
watch push, and run execution scoring never touch it. The athlete's Settings
target (`strength.sessions_per_week`) settles WHETHER strength is wanted; the
coach only decides WHEN and WHAT — and the target is guidance, not a quota.
"""

from __future__ import annotations

import datetime as dt
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Activity, PendingEdit, SupportSession
from .settings_store import get_settings

log = logging.getLogger(__name__)

# How far back auto-matching looks for planned sessions left behind by a quiet
# week. Past-open sessions older than this stay planned/unmatched (harmless).
MATCH_WINDOW_DAYS = 14


def _monday(day: dt.date) -> dt.date:
    return day - dt.timedelta(days=day.weekday())


def session_dict(s: SupportSession) -> dict:
    return {
        "id": s.id,
        "date": s.date.isoformat(),
        "kind": s.kind,
        "duration_min": s.duration_min,
        "focus": s.focus,
        "rationale": s.rationale,
        "status": s.status,
        "source": s.source,
        "activity_id": s.activity_id,
    }


def _strength_activity_dates(db: Session, user_id: int,
                             start: dt.date, end: dt.date) -> dict[dt.date, int]:
    """date -> a strength activity id, for [start, end]."""
    acts = db.scalars(
        select(Activity).where(Activity.user_id == user_id,
                               Activity.date >= start, Activity.date <= end,
                               Activity.type.like("%strength%"))
        .order_by(Activity.id)
    ).all()
    return {a.date: a.id for a in acts}


def match_completed(db: Session, user_id: int, today: dt.date) -> int:
    """Auto-complete planned sessions whose date has a synced strength activity.

    Idempotent; called from the read paths (today/week/signal) so completion
    needs no sync hook. Returns the number of sessions completed."""
    start = today - dt.timedelta(days=MATCH_WINDOW_DAYS)
    open_sessions = db.scalars(
        select(SupportSession).where(
            SupportSession.user_id == user_id, SupportSession.status == "planned",
            SupportSession.date >= start, SupportSession.date <= today)
    ).all()
    if not open_sessions:
        return 0
    by_date = _strength_activity_dates(db, user_id, start, today)
    matched = 0
    for s in open_sessions:
        act_id = by_date.get(s.date)
        if act_id is not None:
            s.status = "completed"
            s.activity_id = act_id
            matched += 1
    if matched:
        db.commit()
    return matched


def week_sessions(db: Session, user_id: int, start: dt.date,
                  end: dt.date) -> list[SupportSession]:
    return db.scalars(
        select(SupportSession).where(SupportSession.user_id == user_id,
                                     SupportSession.date >= start,
                                     SupportSession.date <= end)
        .order_by(SupportSession.date, SupportSession.id)
    ).all()


def strength_signal(db: Session, user_id: int, today: dt.date,
                    settings: dict | None = None) -> dict | None:
    """The deterministic weekly-target signal for the coach.

    None when the athlete hasn't opted in (target 0) — absent from the snapshot
    entirely, same framing as cycle/niggles. `done_this_week` counts distinct
    days with strength work (a completed session OR an unplanned strength
    activity — unplanned work still honors the contract). `remaining_to_plan`
    is what the coach may still place this week."""
    settings = settings or get_settings(db, user_id)
    strength = settings.get("strength") or {}
    target = strength.get("sessions_per_week") or 0
    if not target:
        return None
    match_completed(db, user_id, today)
    monday = _monday(today)
    sunday = monday + dt.timedelta(days=6)
    sessions = week_sessions(db, user_id, monday, sunday)
    done_days = {s.date for s in sessions if s.status == "completed"}
    done_days |= set(_strength_activity_dates(db, user_id, monday, today))
    open_upcoming = [s for s in sessions
                     if s.status == "planned" and s.date >= today]
    return {
        "target_per_week": target,
        "focus_preference": strength.get("focus") or "coach",
        "done_this_week": len(done_days),
        "planned_upcoming": [
            {"date": s.date.isoformat(), "duration_min": s.duration_min,
             "focus": s.focus}
            for s in open_upcoming
        ],
        "remaining_to_plan": max(0, target - len(done_days) - len(open_upcoming)),
    }


def _valid_sessions(sessions: list[dict], start: dt.date, end: dt.date,
                    limit: int) -> list[tuple[dt.date, dict]]:
    """Parse/validate proposed session dicts: in-window dates, one per date,
    clamped count. Invalid entries are dropped with a log, never an error —
    same warn-don't-repair posture as check_week."""
    out: list[tuple[dt.date, dict]] = []
    seen: set[dt.date] = set()
    for raw in sessions or []:
        try:
            date = dt.date.fromisoformat(str(raw.get("date")))
        except (TypeError, ValueError):
            log.warning("strength session dropped (bad date): %r", raw)
            continue
        if not (start <= date <= end) or date in seen:
            log.warning("strength session dropped (out of window/dup): %r", raw)
            continue
        seen.add(date)
        out.append((date, raw))
        if len(out) >= limit:
            break
    return out


def apply_sessions(db: Session, user_id: int, sessions: list[dict], *,
                   source: str, today: dt.date, target: int,
                   replace: bool = False) -> list[SupportSession]:
    """Write coach-placed sessions for the upcoming week (author mode / an
    accepted proposal).

    Rules mirroring plan materialization: only rows that are still `planned`
    AND coach-authored are replaceable; a completed/skipped session or a
    manually added one is never touched. One session per date. Count clamped
    to the athlete's target. `replace=True` (author's daily re-plan) also
    drops coach placements the new set no longer includes; an accepted
    proposal upserts only its own dates."""
    window_end = today + dt.timedelta(days=6)
    valid = _valid_sessions(sessions, today, window_end, max(0, target))
    existing = {
        s.date: s
        for s in week_sessions(db, user_id, today, window_end)
    }
    written: list[SupportSession] = []
    wanted_dates = {d for d, _ in valid}
    if replace:
        # Drop superseded coach placements the new set no longer includes.
        for s in existing.values():
            if (s.status == "planned" and s.source in ("author", "chat_edit")
                    and s.date not in wanted_dates):
                db.delete(s)
    for date, raw in valid:
        row = existing.get(date)
        if row is not None and not (
                row.status == "planned" and row.source in ("author", "chat_edit")):
            continue  # completed/skipped/manual rows win over a re-plan
        if row is None:
            row = SupportSession(user_id=user_id, date=date)
            db.add(row)
        row.kind = "strength"
        row.duration_min = raw.get("duration_min")
        row.focus = str(raw.get("focus") or "")
        row.rationale = str(raw.get("rationale") or "")
        row.status = "planned"
        row.source = source
        written.append(row)
    db.commit()
    return written


def create_strength_proposal(
    db: Session, user_id: int, sessions: list[dict], summary: str, rationale: str,
    today: dt.date | None = None,
) -> tuple[PendingEdit | None, dict | None]:
    """A pending strength-placement proposal (editor mode / chat), riding the
    shared create_pending_edit queue (same validation + supersession) as a
    strength-only edit."""
    from .planner import create_pending_edit

    today = today or dt.date.today()
    settings = get_settings(db, user_id)
    target = (settings.get("strength") or {}).get("sessions_per_week") or 0
    if not target:
        return None, {"error": "the athlete has not opted into strength training "
                               "(sessions_per_week is 0); suggest enabling it in "
                               "Settings instead of proposing sessions"}
    if not _valid_sessions(sessions, today, today + dt.timedelta(days=6), target):
        return None, {"error": "no valid sessions provided (dates must fall in "
                               "the next 7 days, one session per day, at most "
                               f"{target} sessions)"}
    return create_pending_edit(db, user_id, [], summary, rationale, today,
                               strength=sessions)


def strength_proposal_muted(db: Session, user_id: int, today: dt.date) -> bool:
    """True when the athlete dismissed a strength-carrying proposal this week —
    the daily review must not re-propose placements until next week (anti-nag;
    the athlete can still ask in chat any time)."""
    monday = _monday(today)
    for e in db.scalars(
            select(PendingEdit).where(PendingEdit.user_id == user_id,
                                      PendingEdit.status == "dismissed")):
        if e.strength and e.created_at.date() >= monday:
            return True
    return False
