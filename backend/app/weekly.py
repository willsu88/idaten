"""The weekly summary — the coach's retrospective on a closed training week.

Fifth coach call site (CONTEXT.md), its own artifact beside the daily review
(docs/adr/0002). Retrospective ONLY: it never proposes plan changes and the
daily review never consumes it. Generated in Monday's daily job and lazily
from the API; always written once its week has closed, including for a week
with zero activities — no pending_data gate, because a closed week's data
already synced through the week.

All week-boundary math funnels through `week_start_of` so a future
user-configurable week anchor (Sunday vs Monday) is a settings read here,
not a repo-wide migration.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import threading

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import feedback as feedback_mod, support as support_mod
from .llm import make_client
from .models import Activity, Niggle, PlanDay, Race, Setting, WeeklySummary
from .settings_store import get_settings

log = logging.getLogger(__name__)

# Server-owned enabled flag (Idea G's seam, .scratch/coach-toggles): not in
# settings DEFAULTS, so the member-facing settings API can never read or write
# it. Absent = enabled. Checked at this module's generation choke point only.
ENABLED_KEY = "weekly_summary_enabled"


def app_today() -> dt.date:
    """The app clock (plain local date, matching the daily review's
    convention) — public so the API layer and tests share one seam."""
    return dt.date.today()


def week_start_of(date: dt.date) -> dt.date:
    """The Monday that anchors `date`'s summary week (fixed Mon-Sun for now;
    the single seam a configurable week anchor would change)."""
    return date - dt.timedelta(days=date.weekday())


def last_closed_week(today: dt.date) -> dt.date:
    """The start of the most recent summary week that has fully ended."""
    return week_start_of(today) - dt.timedelta(days=7)


def summaries_enabled(db: Session, user_id: int) -> bool:
    """Absent = enabled; any falsy stored value (False, 0, "") = disabled, so
    a future toggle can't accidentally write a value this reads as enabled."""
    row = db.get(Setting, (user_id, ENABLED_KEY))
    return row is None or bool(row.value)


WEEKLY_SUMMARY_SYSTEM_PROMPT = """\
You are an experienced running coach writing the athlete's weekly review —
a look back at the training week that just ended (Monday through Sunday).

Your job is retrospective ONLY. You are not planning the coming week, not
prescribing today's workout, and never proposing plan changes — the daily
review owns all of that. You are telling the athlete the honest story of
the week they just completed, in 2-4 short paragraphs.

Ground every claim in the snapshot:
- `week_aggregates` is the factual skeleton: planned vs completed minutes,
  running distance, easy-zone percentage, and strength sessions done vs the
  weekly target. Every judgment you make must be anchored in these facts,
  but express them in your own voice — quote a number only when your voice
  rules allow it and that number earns its place; otherwise convey the same
  truth qualitatively ('you hit nearly everything the week asked of you').
  Never state something the aggregates contradict.
- `activities` are the week's sessions, each with its execution score where
  one exists (0-100, how closely they hit the prescribed intensity). Call
  out the week's standout session by name and, when scores trend low across
  the week, name the pattern warmly ('the hard sessions turned into a grind
  by Thursday') — never scold.
- `plan_days` is what the week asked of them. Compliance is a story, not a
  grade: a skipped session with an open niggle was judgment, not failure.
- `active_niggles`: any issue open during the week shapes the whole
  retrospective. A zero-run week with an open severity-2 knee is a GOOD week
  if they rested it — say so by body part, warmly, never clinically. Never
  guilt the athlete for protecting their body.
- `previous_week_summary` (absent on the first ever summary): your own
  review of the prior week. Use it for trend — 'second week in a row the
  easy runs crept too fast', 'a real step up from last week's interrupted
  block'. Reference at most one or two threads; do not recap it.
- `upcoming_races` (when present): frame the week against what they're
  building toward ('six weeks out, this was exactly the week you needed'),
  but do not write a race plan.

An empty week — zero activities — still gets a real review. Read the
context: an open injury means the rest was right; illness or life getting
in the way means reset without judgment; no visible reason means one warm,
direct nudge toward getting back out, never a lecture.

Tone: honest, specific, and warm. Celebrate what deserves it with evidence,
name what slipped without euphemism, and close with one forward-looking
sentence — a thread to carry into the new week, not instructions for it.
Never invent data that is not in the snapshot, and never quote raw JSON
field names to the athlete.
"""

WEEKLY_SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {"summary": {"type": "string"}},
    "required": ["summary"],
    "additionalProperties": False,
}


def build_weekly_snapshot(db: Session, user_id: int, week_start: dt.date) -> dict:
    """The frozen inputs for one week's summary. Computed in code, not by the
    model — same philosophy as build_review_snapshot."""
    week_end = week_start + dt.timedelta(days=6)
    after_week = week_start + dt.timedelta(days=7)

    acts = db.scalars(
        select(Activity).where(
            Activity.user_id == user_id, Activity.date >= week_start,
            Activity.date < after_week).order_by(Activity.date, Activity.id)
    ).all()
    activities = [
        {
            "date": a.date.isoformat(),
            "type": a.type,
            "name": a.name,
            "distance_km": round((a.distance_m or 0) / 1000, 2),
            "duration_min": round((a.duration_s or 0) / 60, 1),
            "execution_score": a.execution_score,
            "rpe_1_to_10": a.rpe if a.rpe is not None else a.garmin_rpe,
            "feel_1_to_5": a.feel,
        }
        for a in acts
    ]

    days = db.scalars(
        select(PlanDay).where(
            PlanDay.user_id == user_id, PlanDay.date >= week_start,
            PlanDay.date < after_week).order_by(PlanDay.date)
    ).all()
    plan_days = [
        {
            "date": d.date.isoformat(),
            "workout_type": d.workout_type,
            "title": d.title,
            "duration_min": d.duration_min,
            "status": d.status,
        }
        for d in days
    ]

    planned_min = sum(
        d.duration_min for d in days
        if d.workout_type != "rest" and d.duration_min is not None)
    done_min = sum(a.duration_s / 60 for a in acts if a.duration_s)
    run_km = sum(
        a.distance_m / 1000 for a in acts
        if a.distance_m and "run" in (a.type or ""))
    easy_s = total_s = 0.0
    for a in acts:
        z = a.time_in_zones or {}
        total = sum(z.values())
        if total:
            easy_s += z.get("z1", 0) + z.get("z2", 0)
            total_s += total
    strength = None
    target = (get_settings(db, user_id).get("strength") or {}).get("sessions_per_week") or 0
    if target:
        done_days = {
            s.date for s in support_mod.week_sessions(db, user_id, week_start, week_end)
            if s.status == "completed"
        }
        done_days |= {a.date for a in acts if "strength" in (a.type or "")}
        strength = {"target": target, "done": len(done_days)}
    aggregates = {
        "planned_min": round(planned_min) if planned_min else None,
        "done_min": round(done_min) if done_min else 0,
        "run_km": round(run_km, 1) if run_km else None,
        "easy_pct": round(100 * easy_s / total_s) if total_s else None,
        "strength": strength,
    }

    niggles = [
        {
            "body_part": n.body_part,
            "severity": n.severity,
            "opened": n.onset_date.isoformat(),
            "resolved": n.resolved_date.isoformat() if n.resolved_date else None,
            "note": n.note,
        }
        for n in db.scalars(
            select(Niggle).where(
                Niggle.user_id == user_id, Niggle.onset_date <= week_end,
                (Niggle.resolved_date.is_(None)) | (Niggle.resolved_date >= week_start)
            ).order_by(Niggle.onset_date)
        )
    ]

    races = [
        {
            "name": r.name,
            "date": r.date.isoformat(),
            "weeks_out": max(0, (r.date - week_end).days) // 7,
            "distance_km": r.distance_km,
            "goal_time": r.goal_time or None,
        }
        for r in db.scalars(
            select(Race).where(Race.user_id == user_id, Race.date > week_end)
            .order_by(Race.date).limit(3)
        )
    ]

    prev = db.get(WeeklySummary, (user_id, week_start - dt.timedelta(days=7)))

    snap: dict = {
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "week_aggregates": aggregates,
        "activities": activities,
        "plan_days": plan_days,
    }
    if niggles:
        snap["active_niggles"] = niggles
    if races:
        snap["upcoming_races"] = races
    if prev is not None and prev.coach_note:
        snap["previous_week_summary"] = prev.coach_note
    return snap


# One summary LLM call per user per week even when the scheduler's Monday pass
# and the page's lazy trigger race — same lock pattern as planner._eval_lock.
_week_locks: dict[int, threading.Lock] = {}
_week_locks_guard = threading.Lock()


def _week_lock(user_id: int) -> threading.Lock:
    with _week_locks_guard:
        return _week_locks.setdefault(user_id, threading.Lock())


def evaluate_week(
    db: Session, user_id: int, week_start: dt.date, *, today: dt.date | None = None,
) -> WeeklySummary | None:
    """Write (or return) the summary for one closed week. Idempotent: an
    existing row is returned without an LLM call.

    Policy (ADR 0002): only the most recently closed week is generatable —
    the running week isn't over, and older weeks are never backfilled. Any
    date within the week is accepted and normalized to its Monday. Returns
    None when the member's summaries are disabled (Idea G seam)."""
    today = today or app_today()
    week_start = week_start_of(week_start)
    generatable = last_closed_week(today)
    if week_start != generatable:
        existing = db.get(WeeklySummary, (user_id, week_start))
        if existing is not None:
            return existing
        raise ValueError(
            f"week {week_start.isoformat()} is not generatable "
            f"(only {generatable.isoformat()} is; forward-only, no backfill)")
    with _week_lock(user_id):
        existing = db.get(WeeklySummary, (user_id, week_start))
        if existing is not None:
            db.refresh(existing)
            return existing
        if not summaries_enabled(db, user_id):
            log.info("weekly summary disabled (user %s); skipping", user_id)
            return None
        return _evaluate_week_locked(db, user_id, week_start)


def _evaluate_week_locked(db: Session, user_id: int, week_start: dt.date) -> WeeklySummary:
    from .planner import clean_llm_text, log_persona_lint, style_prompt

    settings = get_settings(db, user_id)
    snapshot = build_weekly_snapshot(db, user_id, week_start)
    client = make_client(settings.get("llm_provider"), user_id=user_id,
                         call_site="weekly_summary")
    system = WEEKLY_SUMMARY_SYSTEM_PROMPT + style_prompt(settings)
    messages = [{
        "role": "user",
        "content": "Week snapshot (JSON):\n" + json.dumps(snapshot, indent=1)
        + f"\n\nWrite the weekly review for {week_start.isoformat()} - "
        f"{(week_start + dt.timedelta(days=6)).isoformat()}.",
    }]
    result = client.complete_structured(
        system=system, messages=messages, schema=WEEKLY_SUMMARY_SCHEMA,
        name="weekly_summary",
    )
    coach = settings.get("coach_style") or "default"
    note = clean_llm_text(result.get("summary", "")) or ""
    log_persona_lint(coach, note, "weekly_summary")
    row = WeeklySummary(
        user_id=user_id, week_start=week_start, coach_note=note, coach=coach,
        snapshot=snapshot, prompt_version=feedback_mod.prompt_version(system),
    )
    db.merge(row)
    db.commit()
    log.info("weekly summary written (user %s, week %s)", user_id, week_start)
    return db.get(WeeklySummary, (user_id, week_start))
