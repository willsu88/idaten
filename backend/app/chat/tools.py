"""Chat agent tools: read training data / the plan, and propose plan edits.

`propose_plan_edit` is the only side-effecting tool, and its side effect is a
PENDING edit — nothing changes until the user accepts it in the UI (the same
approval-queue shape as practice-two's `refund`).
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import metrics
from ..models import Activity, DailyHealth, DayIntent, PendingEdit, PlanDay, PlanVersion
from ..planner import STEPS_SCHEMA, WORKOUT_TYPES, intent_dict, plan_day_dict

# Neutral (OpenAI-function) schemas — the seam translates for Anthropic.
TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_training_data",
            "description": (
                "Fetch the athlete's daily health (sleep, HRV, resting HR, body battery, "
                "stress), activities (with pace, HR, RPE), and computed load metrics "
                "(CTL fitness / ATL fatigue / TSB form) for a date range. Call this "
                "whenever a question depends on actual training or recovery data."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "YYYY-MM-DD inclusive"},
                    "end_date": {"type": "string", "description": "YYYY-MM-DD inclusive"},
                },
                "required": ["start_date", "end_date"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_current_plan",
            "description": "The training plan for the next 14 days, including each day's rationale and watch-push status.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_plan_history",
            "description": "Recent plan versions: when the plan changed, what changed, and why (source: daily_job or chat_edit).",
            "parameters": {
                "type": "object",
                "properties": {"limit": {"type": "integer", "description": "default 5"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_day_intent",
            "description": (
                "Mark a day as committed to another sport (surfing, hiking, freediving, "
                "cycling...) or as unavailable for running. The planner will never "
                "schedule a run on that day. Use when the athlete says they're doing "
                "another sport or can't run on a date. Usually follow up with "
                "propose_plan_edit to rebalance the surrounding week."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "YYYY-MM-DD"},
                    "sport": {"type": "string", "description": "e.g. 'surfing'; use 'unavailable' if just blocked"},
                    "note": {"type": "string"},
                    "duration_min": {"type": ["number", "null"], "description": "expected duration, for load estimation"},
                    "effort": {"type": ["string", "null"], "enum": ["easy", "moderate", "hard", None]},
                },
                "required": ["date", "sport"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "clear_day_intent",
            "description": "Remove an other-sport/unavailable marker from a day, making it plannable for running again.",
            "parameters": {
                "type": "object",
                "properties": {"date": {"type": "string"}},
                "required": ["date"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "log_niggle",
            "description": (
                "Record that the athlete has pain or an injury (a 'niggle'). Call this "
                "whenever they mention a sore/painful body part — it PERSISTS and the "
                "daily review eases the plan around it until it clears. Logging the "
                "same body part again updates the existing entry (e.g. it got worse). "
                "Usually follow up with propose_plan_edit if a hard session lands "
                "while it's open."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "body_part": {"type": "string", "description": "e.g. 'left knee', 'right achilles'"},
                    "severity": {"type": "integer", "description": "1 = niggle (minor, monitor), 2 = pain (real pain, protect), 3 = injury (can't train normally)"},
                    "note": {"type": "string", "description": "the athlete's own words about it"},
                    "onset_date": {"type": ["string", "null"], "description": "YYYY-MM-DD when it started, if they said; default today"},
                },
                "required": ["body_part", "severity"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "resolve_niggle",
            "description": (
                "Mark a previously logged niggle/pain/injury as resolved when the "
                "athlete says it's better or no longer bothering them. Use the id "
                "from the active niggles list in your context."
            ),
            "parameters": {
                "type": "object",
                "properties": {"id": {"type": "integer"}},
                "required": ["id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_plan_edit",
            "description": (
                "Propose changes to one or more upcoming plan days. The user sees a "
                "diff and must accept before anything changes — never claim the plan "
                "was updated; say the proposal is awaiting their approval. Include "
                "every field for each changed day, and only include days that change."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string", "description": "One line, e.g. 'Swap Thursday tempo for easy run'"},
                    "rationale": {"type": "string", "description": "Why, citing the athlete's data"},
                    "days": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "date": {"type": "string"},
                                "workout_type": {"type": "string", "enum": WORKOUT_TYPES},
                                "title": {"type": "string"},
                                "description": {"type": "string"},
                                "duration_min": {"type": ["number", "null"]},
                                "distance_km": {"type": ["number", "null"]},
                                "target_pace": {"type": ["string", "null"]},
                                "target_hr_low": {"type": ["integer", "null"], "description": "HR band lower bound (bpm); use per the athlete's training mode — never set both pace and HR"},
                                "target_hr_high": {"type": ["integer", "null"]},
                                "steps": STEPS_SCHEMA,
                                "rationale": {"type": "string"},
                            },
                            "required": ["date", "workout_type", "title", "description", "rationale"],
                        },
                    },
                },
                "required": ["summary", "rationale", "days"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_strength_sessions",
            "description": (
                "Propose strength-session placements for the next 7 days (the "
                "strength lane beside the run plan). Only when the athlete has "
                "opted in via Settings (see the strength block in your context). "
                "Same approval contract as propose_plan_edit: the user must "
                "accept before anything is scheduled — never claim it's placed."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string", "description": "One line, e.g. 'Two strength sessions: Tue & Fri'"},
                    "rationale": {"type": "string", "description": "Why these days/focus, citing the athlete's data"},
                    "sessions": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "date": {"type": "string", "description": "YYYY-MM-DD within the next 7 days"},
                                "duration_min": {"type": ["number", "null"], "description": "Typically 20-40"},
                                "focus": {"type": "string", "description": "e.g. 'hips & glutes', 'full body'"},
                                "rationale": {"type": "string", "description": "One line: why this day / this focus"},
                            },
                            "required": ["date", "duration_min", "focus", "rationale"],
                        },
                    },
                },
                "required": ["summary", "rationale", "sessions"],
            },
        },
    },
]


def edit_dict(e: PendingEdit) -> dict:
    return {
        "id": e.id,
        "created_at": e.created_at.isoformat(),
        "summary": e.summary,
        "rationale": e.rationale,
        "changes": e.changes,
        "current": e.current,
        "strength": e.strength,  # proposed strength sessions (null for run edits)
        "status": e.status,
    }


def dispatch(
    db: Session, user_id: int, name: str, args: dict[str, Any]
) -> tuple[str, PendingEdit | None]:
    """Run a tool. Returns (result_json_for_model, pending_edit_if_created).

    Tenant boundary: user_id comes from the authenticated session, never from
    the model — tool schemas have no user/account parameter, so the model
    cannot address another user's data even if prompted to.
    """
    if name == "get_training_data":
        start = dt.date.fromisoformat(args["start_date"])
        end = dt.date.fromisoformat(args["end_date"])
        # Cap the range so a curious model can't drag months of raw rows into context
        if (end - start).days > 92:
            start = end - dt.timedelta(days=92)
        health = [
            {
                "date": h.date.isoformat(),
                "sleep_hours": round(h.sleep_seconds / 3600, 1) if h.sleep_seconds else None,
                "sleep_score": h.sleep_score,
                "hrv": h.hrv,
                "hrv_baseline": h.hrv_baseline,
                "resting_hr": h.resting_hr,
                "body_battery": h.body_battery,
                "stress_avg": h.stress_avg,
            }
            for h in db.scalars(
                select(DailyHealth).where(DailyHealth.user_id == user_id,
                                          DailyHealth.date >= start,
                                          DailyHealth.date <= end).order_by(DailyHealth.date)
            )
        ]
        acts = [
            {
                "date": a.date.isoformat(),
                "type": a.type,
                "name": a.name,
                "distance_km": round((a.distance_m or 0) / 1000, 2),
                "duration_min": round((a.duration_s or 0) / 60, 1),
                "avg_hr": a.avg_hr,
                "avg_pace": metrics.pace_str(a.avg_speed_mps),
                "training_load": a.training_load,
                "rpe_1_to_10": a.rpe if a.rpe is not None else a.garmin_rpe,
                "rpe_note": a.rpe_note,
                "feel_1_to_5": a.feel,
                "body_battery_change": a.body_battery_change,
            }
            for a in db.scalars(
                select(Activity).where(Activity.user_id == user_id,
                                       Activity.date >= start,
                                       Activity.date <= end).order_by(Activity.date)
            )
        ]
        series = metrics.load_series(db, user_id, start, end)
        load = [
            {"date": m.date.isoformat(), "load": round(m.load, 1), "ctl": round(m.ctl, 1),
             "atl": round(m.atl, 1), "tsb": round(m.tsb, 1)}
            for m in series
        ]
        return json.dumps({"health": health, "activities": acts, "load_metrics": load}), None

    if name == "get_current_plan":
        today = dt.date.today()
        days = [
            plan_day_dict(p)
            for p in db.scalars(
                select(PlanDay).where(PlanDay.user_id == user_id,
                                      PlanDay.date >= today).order_by(PlanDay.date).limit(14)
            )
        ]
        intents = [
            intent_dict(i)
            for i in db.scalars(
                select(DayIntent).where(DayIntent.user_id == user_id,
                                        DayIntent.date >= today).order_by(DayIntent.date).limit(14)
            )
        ]
        return json.dumps({"days": days, "other_sport_days": intents}), None

    if name == "set_day_intent":
        try:
            date = dt.date.fromisoformat(args["date"])
        except (ValueError, KeyError):
            return json.dumps({"error": f"invalid date {args.get('date')!r}"}), None
        intent = db.get(DayIntent, (user_id, date)) or DayIntent(user_id=user_id, date=date)
        intent.sport = args["sport"]
        intent.note = args.get("note") or ""
        intent.duration_min = args.get("duration_min")
        intent.effort = args.get("effort")
        intent.source = "chat"
        db.merge(intent)
        db.commit()
        return json.dumps({"status": "set", "intent": intent_dict(intent),
                           "note": "Consider propose_plan_edit to rebalance the week."}), None

    if name == "clear_day_intent":
        try:
            date = dt.date.fromisoformat(args["date"])
        except (ValueError, KeyError):
            return json.dumps({"error": f"invalid date {args.get('date')!r}"}), None
        intent = db.get(DayIntent, (user_id, date))
        if intent is None:
            return json.dumps({"status": "nothing to clear"}), None
        db.delete(intent)
        db.commit()
        return json.dumps({"status": "cleared"}), None

    if name == "log_niggle":
        from .. import niggles as niggles_mod

        onset = None
        if args.get("onset_date"):
            try:
                onset = dt.date.fromisoformat(args["onset_date"])
            except ValueError:
                return json.dumps({"error": f"invalid onset_date {args.get('onset_date')!r}"}), None
        if not (args.get("body_part") or "").strip():
            return json.dumps({"error": "body_part is required"}), None
        n = niggles_mod.log_niggle(
            db, user_id, args["body_part"], args.get("severity"),
            note=args.get("note") or "", onset_date=onset, source="chat",
        )
        return json.dumps({
            "status": "logged", "niggle": niggles_mod.niggle_dict(n, dt.date.today()),
            "note": ("The coach's daily review will ease the plan around this until "
                     "it's resolved. Consider propose_plan_edit if a hard session is "
                     "imminent."),
        }), None

    if name == "resolve_niggle":
        from .. import niggles as niggles_mod

        try:
            niggle_id = int(args["id"])
        except (KeyError, TypeError, ValueError):
            return json.dumps({"error": f"invalid id {args.get('id')!r}"}), None
        n = niggles_mod.resolve_niggle(db, user_id, niggle_id)
        if n is None:
            return json.dumps({"error": f"no niggle with id {niggle_id}"}), None
        return json.dumps({"status": "resolved", "body_part": n.body_part}), None

    if name == "get_plan_history":
        limit = int(args.get("limit") or 5)
        versions = db.scalars(
            select(PlanVersion).where(PlanVersion.user_id == user_id)
            .order_by(PlanVersion.created_at.desc()).limit(limit)
        ).all()
        return json.dumps(
            [
                {"created_at": v.created_at.isoformat(), "source": v.source, "summary": v.summary}
                for v in versions
            ]
        ), None

    if name == "propose_plan_edit":
        # Shared with the daily review: identical pace grounding + supersession.
        from ..planner import create_pending_edit

        edit, error = create_pending_edit(
            db, user_id, args.get("days") or [],
            args.get("summary", ""), args.get("rationale", ""),
        )
        if error is not None:
            return json.dumps(error), None
        return (
            json.dumps({"status": "proposed", "edit_id": edit.id,
                        "note": "Awaiting user approval in the UI. Do not claim it is applied."}),
            edit,
        )

    if name == "propose_strength_sessions":
        from .. import support as support_mod

        edit, error = support_mod.create_strength_proposal(
            db, user_id, args.get("sessions") or [],
            args.get("summary", ""), args.get("rationale", ""),
        )
        if error is not None:
            return json.dumps(error), None
        return (
            json.dumps({"status": "proposed", "edit_id": edit.id,
                        "note": "Awaiting user approval in the UI. Do not claim it is scheduled."}),
            edit,
        )

    return json.dumps({"error": f"unknown tool {name}"}), None
