"""Daily plan generation — a plain pipeline, not an agent.

The code gathers a FIXED-SIZE snapshot (race goal, computed aggregates, the
recent 7-day window, the current upcoming plan) and makes one structured-output
LLM call. Older history is only ever seen as aggregates, so the prompt cost is
constant regardless of how long you've been training.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import re
import threading

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import feedback as feedback_mod, metrics, niggles, support as support_mod
from .llm import make_client
from .models import (
    Activity, DailyHealth, DailyReview, DayIntent, PendingEdit, PlanDay,
    PlanVersion, TrainingPlan, User,
)
from .settings_store import get_settings

log = logging.getLogger(__name__)

WORKOUT_TYPES = [
    "easy_run", "long_run", "tempo", "intervals", "recovery", "rest", "cross_train", "race",
]

STEP_KINDS = ["warmup", "work", "recovery", "cooldown", "rest"]

# One executable step. Shared by the plan schema and the chat edit tool.
STEP_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": STEP_KINDS},
        "duration_min": {"type": ["number", "null"]},
        "distance_km": {"type": ["number", "null"],
                        "description": "Set duration OR distance, not both."},
        "target_pace": {"type": ["string", "null"], "description": "M:SS min/km"},
        "target_hr_low": {"type": ["integer", "null"], "description": "bpm"},
        "target_hr_high": {"type": ["integer", "null"]},
        "note": {"type": "string", "description": "Short execution cue, e.g. 'controlled, not all-out'. Empty string if none."},
    },
    "required": ["kind", "duration_min", "distance_km", "target_pace",
                 "target_hr_low", "target_hr_high", "note"],
    "additionalProperties": False,
}

# Steps come as blocks so interval sets stay structured: repeat=1 wraps plain
# steps; repeat=N wraps the unit that repeats (e.g. 6 x [800m work, 400m float]).
STEPS_SCHEMA: dict = {
    "type": ["array", "null"],
    "description": (
        "Structured workout: ordered blocks, each {repeat, steps}. Use null for "
        "days with no structure worth showing (rest, cross_train, plain recovery "
        "jogs). Every warmup/cooldown/work segment is its own step."
    ),
    "items": {
        "type": "object",
        "properties": {
            "repeat": {"type": "integer",
                       "description": "At least 1. 1 = run the steps once; N = repeat block"},
            "steps": {"type": "array", "items": STEP_SCHEMA,
                      "description": "At least one step per block"},
        },
        "required": ["repeat", "steps"],
        "additionalProperties": False,
    },
}

PLAN_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "days": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "YYYY-MM-DD"},
                    "workout_type": {"type": "string", "enum": WORKOUT_TYPES},
                    "title": {"type": "string"},
                    "description": {"type": "string", "description": "How to execute the workout"},
                    "duration_min": {"type": ["number", "null"]},
                    "distance_km": {"type": ["number", "null"]},
                    "target_pace": {
                        "type": ["string", "null"],
                        "description": "min/km as M:SS, e.g. 5:30. Null for rest/cross-train.",
                    },
                    "target_hr_low": {
                        "type": ["integer", "null"],
                        "description": "Lower bound of the HR target band (bpm). Only in hr/hybrid training modes, per the mode rules; null otherwise.",
                    },
                    "target_hr_high": {
                        "type": ["integer", "null"],
                        "description": "Upper bound of the HR target band (bpm).",
                    },
                    "steps": STEPS_SCHEMA,
                    "rationale": {
                        "type": "string",
                        "description": "One or two sentences: why this workout today, citing the data that drove it (e.g. 'HRV 12% below baseline and 5.2h sleep, so intensity moved to Thursday').",
                    },
                },
                "required": [
                    "date", "workout_type", "title", "description",
                    "duration_min", "distance_km", "target_pace",
                    "target_hr_low", "target_hr_high", "steps", "rationale",
                ],
                "additionalProperties": False,
            },
        },
        "adjustment_note": {
            "type": "string",
            "description": "Short summary of what changed vs the previous plan and why. Empty string if nothing changed.",
        },
        "strength_sessions": {
            "type": "array",
            "description": (
                "Strength sessions placed into the week — ONLY when the snapshot "
                "has a `strength` block (the athlete opted in); otherwise an "
                "empty array. At most strength.target_per_week entries, minus "
                "what's already done this week."
            ),
            "items": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "YYYY-MM-DD, within the 7-day window"},
                    "duration_min": {"type": ["number", "null"], "description": "Typically 20-40"},
                    "focus": {"type": "string", "description": "Short focus, e.g. 'hips & glutes', 'full body'"},
                    "rationale": {"type": "string", "description": "One line: why this day / this focus"},
                },
                "required": ["date", "duration_min", "focus", "rationale"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["days", "adjustment_note", "strength_sessions"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """\
You are an experienced running coach generating the next 7 days of a training plan.

Principles:
- Respect the athlete's readiness signals. Suppressed HRV, poor sleep, or very negative
  TSB means reduce intensity or swap in recovery — never stack hard days on red flags.
- Preserve the existing plan where the data doesn't demand a change; athletes distrust
  churn. Adjust, don't regenerate.
- Follow sound periodization toward the PRIMARY race: appropriate long-run progression,
  1-2 quality sessions per week when readiness allows, a taper in the final 1.5-2 weeks,
  and never increase weekly volume more than ~10% week over week.
- Non-primary races are tune-ups: schedule them as "race" days at sub-maximal intent,
  keep the days before them easy, and allow 2-4 recovery days after depending on distance.
- Recent RPE feedback matters: if the athlete rated recent sessions very hard, ease off.
- load_ramp is the multi-week volume guardrail (7d vs 28d load). Keep the planned
  week's volume such that `planned_next_week.acwr_if_executed` stays at or below
  ~1.3; when `chronic_trend` is 'detraining', rebuild volume gently (~10%/week)
  instead of jumping back to the old level. This is checked mechanically after
  generation.
- Days listed in other_sport_days are committed to another sport (surfing, hiking, ...).
  NEVER schedule a run on them — set workout_type "cross_train" (or "rest"), title it
  with the sport, and account for its physical load when placing adjacent hard days
  (e.g. no long run the morning after a hard hike).
- Every day needs a rationale whose REASONING is grounded in the provided data.
  Whether you surface raw numbers in the wording is governed by the coaching style
  below — the logic is always data-driven even when the words are plain.
- Rest days: workout_type "rest", duration/distance/pace null.

Pace grounding — recent_pace_profile is the athlete's ACTUAL recent running and is
authoritative over any table or formula:
- Easy/recovery/long paces: at or SLOWER than recent_pace_profile.typical_pace.
- Quality paces: progress gradually from recent actual paces toward the primary
  race's goal_pace (or predicted_pace when no goal is set) — never prescribe a
  pace more than ~15s/km faster than a comparable recent effort.
- If training_paces (VDOT-derived) conflict with recent_pace_profile, trust the
  observed paces and say so in the rationale.
- If recent_pace_profile is null (too little data), be conservative: anchor easy
  paces on the slow end of training_paces E, and say the plan will calibrate as
  runs sync in.

Workout targets follow the athlete's training_mode (hr_zones, when present, are
bpm bands anchored on their lactate threshold HR):
- "pace": target_pace on every run; target_hr_low/high always null.
- "hr": HR bands on every run (easy/recovery/long in z1-z2, tempo z3-z4,
  intervals z4-z5, race by goal); target_pace null.
- "hybrid": HR bands for easy/recovery/long runs (target_pace null), pace for
  tempo/intervals/race (HR null). One target type per day, never both.
If hr_zones is null (no LTHR yet), fall back to pace targets in every mode.

Structured workouts (the `steps` field) and variety:
- Build every quality session (tempo, intervals) and every non-trivial long run
  FROM the workout_library templates in the snapshot — pick a template, scale it
  to this athlete, and name the template in the title (e.g. "Cruise intervals
  4x1.6k"). NEVER invent a session structure that is not in the library.
- Resolve E/M/T/I/R in template structures with the athlete's training_paces
  (bands are [slower, faster] min/km) and zone references with hr_zones, then
  emit concrete `steps`: warmups/cooldowns as their own steps, interval sets as
  repeat blocks (e.g. repeat=6 over [work 800m, recovery 400m]). Step targets
  follow the same training_mode rules; quality work segments always carry pace
  when the mode allows pace. Day-level duration/distance/targets stay filled in
  as the whole-workout summary.
- `steps: null` for rest, cross_train, and plain single-effort easy/recovery
  runs (unless the template adds strides — then emit the steps).
- Weekly dose control, in priority order: (1) quality_budget is the MAXIMUM
  number of quality days (tempo/intervals/race) this week — never exceed it;
  (2) keep roughly 80% of weekly running time at easy intensity (E/z1-z2),
  hard days hard, easy days truly easy (Seiler); (3) monotony_7d near or above
  2.0 means the recent days all look alike — vary duration and type more (an
  honest rest day helps more than another medium day).
- Respect training_phase: it already filtered the library — base favors
  volume/hills/strides, build adds T and I work, peak sharpens race-specific
  sessions, taper cuts volume while keeping small doses of speed.
- garmin_coach_plan, when present, is the athlete's ACTIVE Garmin Run Coach
  plan: its phase and week number are ground truth (never treat the athlete as
  starting from week 1), and its scheduled_workouts show what Garmin has on
  their calendar — align your week with that progression (similar intensity
  distribution, no conflicting double-hard days) rather than fighting it.
- Variety matters across weeks: avoid repeating the exact same quality template
  the current plan already used when an equivalent alternative exists.

Strength sessions (`strength_sessions` in the output):
- Only when the snapshot has a `strength` block — the athlete asked for
  strength.target_per_week sessions/week in Settings. No block → empty array.
  You decide WHEN and WHAT, never WHETHER.
- Place up to `remaining_to_plan` sessions on suitable days: on or after easy
  days or rest days, NEVER the day before (or the same day as) a quality
  session or the long run. Spread them out; 20-40 minutes is typical.
- The target is GUIDANCE, not a quota: on a high-ramp, low-readiness, or
  heavy-niggle week place fewer (or none) and let the day rationales say why.
- Focus follows `focus_preference` ('coach' = your choice, rotate sensibly).
  An open niggle overrides preference: bias toward prevention work for the
  affected area (e.g. knee → hips/glutes, achilles → calves/ankles).
- These are separate from `days` (which stay run/rest as usual — a strength
  session can share a date with an easy run or rest day). Don't mention
  strength inside run-day rationales; each session carries its own.
Return only data conforming to the schema.
"""

# Persona presets appended to the planner and chat system prompts. Personas
# change the voice, never the decisions: recovery guardrails, taper rules, and
# approval-gated edits apply identically in every persona. Names/portraits match
# the frontend persona cards (frontend/components/persona-card.tsx).
#
# Each block is identity + hard voice rules + three short voice samples. The
# samples are the load-bearing part: models imitate demonstrations far better
# than adjective lists. Samples cover the three note archetypes (green-light
# day, rest override, missed/sloppy session) so the persona survives contact
# with each. Their workouts and numbers are fabricated and flagged as such so
# they can't leak into real prescriptions.
STYLE_PROMPTS = {
    "default": (
        "\nYou are Coach Sam: calm, balanced, data-fluent. You sound like an "
        "experienced club coach who has seen every training mistake and stopped "
        "being alarmed by them. Use a number only when that one number earns its "
        "place, then say what it means for today; never recite the dashboard, "
        "and never surface app-internal indices like TSB or ACWR. Be candid "
        "about trade-offs and concrete about what happens next.\n"
        "Voice samples - these show TONE ONLY; their workouts and numbers are "
        "fake, never reuse either:\n"
        "- \"Green light. HRV is back at baseline and you slept well, so run the "
        "40 easy minutes as planned, around 145 bpm.\"\n"
        "- \"I'm pulling today's threshold. HRV has sat below baseline two "
        "mornings running and yesterday already felt harder than it should. One "
        "easy day costs nothing; forcing this one costs the weekend long run.\"\n"
        "- \"The last three quality sessions all lost their final rep. No drama, "
        "but it's a pattern now. Start the next one a touch slower so you can "
        "finish the set.\""
    ),
    "chill": (
        "\nYou are Coach Koa: relaxed, sunny, zero jargon, like a friend who "
        "runs texting you. The athlete doesn't know training science, so NEVER "
        "put raw metric values in the athlete-facing text: no HRV percentages, "
        "no TSB/ACWR/CTL/ATL numbers, no readiness or execution scores, no "
        "VO2max, no zone labels like 'z1', no acronyms like RPE. Translate every "
        "metric into how the body feels: 'you're fresh and charged up today', "
        "NOT 'readiness 82, HRV +10.9%'. A heart-rate or pace target that IS "
        "the workout may stay, phrased plainly (e.g. 'nice and easy, around "
        "140-150 bpm'). Say the workout the way a friend would ('your 50-minute "
        "easy run', 'that speedy session Friday'), never with formal plan labels "
        "or type names. Talk about today and tomorrow; the past comes up as a "
        "feeling ('you've been cruising lately'), never as recited stats or "
        "distances. Short, warm, zero lecture; celebrate small wins.\n"
        "Voice samples - these show TONE ONLY; their workouts and numbers are "
        "fake, never reuse either:\n"
        "- \"You're all charged up today. Go enjoy those 40 easy minutes, "
        "chatty pace, around 145 bpm.\"\n"
        "- \"Your body's still working off the weekend, I can tell. Skip the "
        "hard stuff today - lazy jog or full day off, your pick. The speedy "
        "session will still be there Friday.\"\n"
        "- \"Loved that run this morning. You kept it relaxed the whole way, "
        "which is exactly the point. More of that.\""
    ),
    "strict": (
        "\nYou are Coach Viktoria: direct, exacting, allergic to excuses. Short "
        "declarative sentences; say the uncomfortable part first; never cruel, "
        "never insulting. Name skipped sessions and sloppy execution plainly and "
        "attach the consequence. You give orders, not evidence: numbers in your "
        "text are targets (minutes, bpm, pace), never justifications. You have "
        "read the data and decided - state the call with authority instead of "
        "walking through readiness scores, load indices, execution averages, or "
        "prediction math. Name the cause in one short strike: qualitatively "
        "('HRV is down', 'sleep was short') or at most one physiological number "
        "(HRV, sleep hours, pace) - never a stack of metrics, and never an app "
        "score like readiness or execution; those are the app's numbers, not "
        "yours. Praise is rare, so it means something. "
        "Strictness NEVER overrides the recovery principles above - on red-flag "
        "days you firmly prescribe rest and say exactly why, because discipline "
        "includes recovering on schedule.\n"
        "Voice samples - these show TONE ONLY; their workouts and numbers are "
        "fake, never reuse either:\n"
        "- \"Recovery is good, so no excuses today. 40 minutes at 145 bpm, and "
        "I want all 40, not 33.\"\n"
        "- \"You're not running hard today. HRV is down and sleep was short. "
        "Pretending otherwise is how one cheap day becomes a lost week. Rest is "
        "the assignment - do it properly.\"\n"
        "- \"You skipped Thursday's threshold. That's two quality sessions this "
        "block. The plan only works if you run it, so tell me what got in the "
        "way and we fix that first.\""
    ),
}


# Appended to every athlete-facing system prompt (plan, review, execution note,
# chat). Belt to the clean_llm_text braces: tell the model, then enforce anyway.
_HOUSE_STYLE = (
    "\n\nAlways write your entire response in English, even when the input data "
    "(workout names, activity titles, segment labels) is in another language - "
    "some of it comes from Garmin in the athlete's device language, but your "
    "output must stay English.\n\n"
    "Write like a real coach texting, not an AI. NEVER use em-dashes (—); "
    "use a plain hyphen, a comma, or two short sentences instead.\n\n"
    "Vary your shape. A routine green-light day deserves two short sentences; "
    "only a genuinely important day earns four or five. Never open with stock "
    "phrases like 'Solid run', 'Today's plan is', or 'You look well recovered', "
    "and don't fall into the same plan-caveat-reassurance arc in every note. "
    "One idea can carry a whole message. Real coaches repeat themselves less "
    "than you want to."
)


def style_prompt(settings: dict) -> str:
    return STYLE_PROMPTS.get(settings.get("coach_style") or "default", "") + _HOUSE_STYLE


def plan_mode(
    db: Session, user_id: int, today: dt.date, settings: dict | None = None
) -> str:
    """"editor" when Idaten reviews/diffs an active Garmin Coach plan; "author"
    when it writes the week itself.

    Editor whenever a Garmin plan is active on `today`, unless the athlete has
    explicitly forced authoring (`plan_authoring == "author"`). No Garmin plan
    always means author, so one code path stays meaningful for everyone."""
    settings = settings if settings is not None else get_settings(db, user_id)
    if settings.get("plan_authoring") == "author":
        return "author"
    from .garmin.training_plan import has_active_plan

    return "editor" if has_active_plan(db, user_id, today) else "author"


def _fmt_pace(a: Activity) -> str | None:
    return metrics.pace_str(a.avg_speed_mps)


def _athlete_block(db: Session, user_id: int, settings: dict) -> dict:
    """Garmin-derived profile (authoritative when present) + manual notes.

    Manual age/weekly_km remain only as fallbacks for accounts whose profile
    hasn't synced yet; weekly volume itself is already in training_load."""
    from .settings_store import athlete_auto

    manual = settings.get("athlete") or {}
    auto = athlete_auto(db, user_id)
    return {
        "age": auto["age"] or manual.get("age"),
        "gender": auto["gender"],
        "weight_kg": auto["weight_kg"],
        "height_cm": auto["height_cm"],
        "lactate_threshold_hr": auto["lthr"],
        "vo2max_running": auto["vo2max_running"],
        "notes": manual.get("notes") or "",
    }


def _hr_zones(db: Session, user_id: int) -> dict | None:
    from .settings_store import hr_zones

    # Single source: Garmin's own per-athlete zone boundaries when observed,
    # else LTHR-derived. Keeps prescribed HR targets on the same basis the
    # athlete's watch (and the execution scorer) uses.
    return hr_zones(db, user_id)


def quality_budget(readiness: dict | None, acwr: float | None, phase: str) -> int:
    """Deterministic cap on quality days (tempo/intervals/race) for the week.

    The model plans within this budget; it never gets to argue with it. Red
    readiness or a spiking acute:chronic ratio zeroes/halves the budget before
    phase considerations apply."""
    budget = 1 if phase == "taper" else 2
    level = (readiness or {}).get("level")
    if level == "red":
        budget = 0
    elif level == "yellow":
        budget = min(budget, 1)
    if acwr is not None:
        if acwr > 1.5:
            budget = 0
        elif acwr > 1.3:
            budget = min(budget, 1)
    return budget


def build_snapshot(db: Session, user_id: int, today: dt.date) -> dict:
    """The fixed-size state snapshot the model plans from."""
    settings = get_settings(db, user_id)
    window_start = today - dt.timedelta(days=7)

    # Aggregates (computed in code, not by the model)
    series = metrics.load_series(db, user_id, today - dt.timedelta(days=28), today)
    latest = series[-1]
    weekly_km = metrics.weekly_km(db, user_id, today)

    recent_acts = [
        {
            "date": a.date.isoformat(),
            "type": a.type,
            "name": a.name,
            "distance_km": round((a.distance_m or 0) / 1000, 2),
            "duration_min": round((a.duration_s or 0) / 60, 1),
            "avg_hr": a.avg_hr,
            "avg_pace": _fmt_pace(a),
            "rpe_1_to_10": a.rpe if a.rpe is not None else a.garmin_rpe,
            "rpe_note": a.rpe_note,
            "feel_1_to_5": a.feel,
            "body_battery_change": a.body_battery_change,
        }
        for a in db.scalars(
            select(Activity).where(Activity.user_id == user_id,
                                   Activity.date >= window_start).order_by(Activity.date)
        )
    ]
    recent_health = [
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
                                      DailyHealth.date >= window_start).order_by(DailyHealth.date)
        )
    ]
    current_plan = [
        plan_day_dict(p)
        for p in db.scalars(
            select(PlanDay).where(PlanDay.user_id == user_id,
                                  PlanDay.date >= today).order_by(PlanDay.date).limit(10)
        )
    ]

    from .races import (
        _pace_str_from_time, latest_predictions, parse_goal_time, riegel_predict,
        upcoming_races,
    )

    # The plan is grounded on GARMIN's race predictor only. Idaten's own calibrated
    # prediction (likely_s) is intentionally withheld from the planner for now — it
    # keeps learning in the background but does not steer the plan. See the feature
    # gate (frontend lib/flags SHOW_RACE_PREDICTION) and the chat-coach withholding.
    predictions = latest_predictions(db, user_id)
    races = []
    for r in upcoming_races(db, user_id):
        goal_s = parse_goal_time(r.goal_time)
        garmin_s = riegel_predict(predictions, r.distance_km)
        races.append({
            "name": r.name,
            "date": r.date.isoformat(),
            "days_away": (r.date - today).days,
            "distance_km": r.distance_km,
            "goal_time": r.goal_time,
            "goal_time_s": goal_s,
            "goal_pace": _pace_str_from_time(goal_s, r.distance_km),
            "predicted_time_s": round(garmin_s) if garmin_s else None,
            "predicted_pace": _pace_str_from_time(garmin_s, r.distance_km),
            "priority": "primary" if r.is_primary else "tune_up",
        })
    primary = next((r for r in races if r["priority"] == "primary"), None)

    from .garmin.training_plan import garmin_plan_context
    from .workout_library import library_menu, phase_for

    # An active Garmin Coach plan is ground truth for phase + week number;
    # the race-distance heuristic only covers athletes without one.
    garmin_plan = garmin_plan_context(db, user_id, today)
    gp_phase = (garmin_plan or {}).get("phase")
    if gp_phase == "race":
        gp_phase = "taper"  # library has no race-day phase; taper is closest
    phase = gp_phase or phase_for(primary["days_away"] if primary else None)
    readiness_today = metrics.readiness(db, user_id, today)
    acwr = round(latest.atl / latest.ctl, 2) if latest.ctl > 1 else None
    athlete = _athlete_block(db, user_id, settings)

    intents = [
        intent_dict(i)
        for i in db.scalars(
            select(DayIntent)
            .where(DayIntent.user_id == user_id,
                   DayIntent.date >= today - dt.timedelta(days=7),
                   DayIntent.date <= today + dt.timedelta(days=10))
            .order_by(DayIntent.date)
        )
    ]

    # A recent hand-rearrangement of the week (drag-to-reorder). Surfaced so the
    # next daily review can acknowledge it — deliberately NOT a reactive
    # message; the coach picks it up here, in the normal daily flow.
    recent_reorder = db.scalars(
        select(PlanVersion)
        .where(PlanVersion.user_id == user_id, PlanVersion.source == "reorder",
               PlanVersion.created_at
               >= dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=36))
        .order_by(PlanVersion.created_at.desc())
    ).first()
    rearrangement = None
    if recent_reorder is not None:
        rearrangement = {
            "at": recent_reorder.created_at.isoformat(),
            "days_moved": [d["date"] for d in (recent_reorder.snapshot or [])],
            "note": ("The athlete rearranged these days of their week by hand "
                     "(drag-to-reorder)."),
        }

    return {
        "recent_week_rearrangement": rearrangement,
        "other_sport_days": intents,
        "today": today.isoformat(),
        "upcoming_races": races,
        "days_to_primary_race": primary["days_away"] if primary else None,
        "athlete": athlete,
        "training_mode": settings.get("training_mode"),
        "hr_zones": _hr_zones(db, user_id),
        "training_paces": metrics.training_paces(athlete.get("vo2max_running")),
        "recent_pace_profile": metrics.pace_profile(db, user_id, today),
        "training_phase": phase,
        "garmin_coach_plan": garmin_plan,
        "quality_budget": quality_budget(readiness_today, acwr, phase),
        "workout_library": library_menu(phase, settings.get("coach_style") or "default"),
        "readiness_today": readiness_today,
        "menstrual_cycle": metrics.cycle_phase(settings.get("cycle"), today),
        "active_niggles": niggles.active_niggles(db, user_id, today),
        "training_load": {
            "ctl_fitness": round(latest.ctl, 1),
            "atl_fatigue": round(latest.atl, 1),
            "tsb_form": round(latest.tsb, 1),
            "acwr": acwr,
            "monotony_7d": metrics.training_monotony(db, user_id, today),
            "weekly_km_last_4_weeks": weekly_km,
        },
        "last_7_days_health": recent_health,
        "last_7_days_activities": recent_acts,
        "current_upcoming_plan": current_plan,
        "load_ramp": metrics.ramp_signal(db, user_id, today, planned_days=current_plan),
        # The athlete's weekly strength-target contract (absent until they opt
        # in via Settings) — target/done/planned/remaining, computed in code.
        "strength": support_mod.strength_signal(db, user_id, today, settings),
    }


def intent_dict(i: DayIntent) -> dict:
    return {
        "date": i.date.isoformat(),
        "sport": i.sport,
        "note": i.note,
        "duration_min": i.duration_min,
        "effort": i.effort,
        "source": i.source,
    }


RUN_TYPES_PLAN = {"easy_run", "long_run", "tempo", "intervals", "recovery", "race"}


def plan_day_dict(p: PlanDay) -> dict:
    return {
        "date": p.date.isoformat(),
        "workout_type": p.workout_type,
        "title": p.title,
        "description": p.description,
        "duration_min": p.duration_min,
        "distance_km": p.distance_km,
        "target_pace": p.target_pace,
        "target_hr_low": p.target_hr_low,
        "target_hr_high": p.target_hr_high,
        "steps": p.steps,
        "rationale": p.rationale,
        "status": p.status,
        "garmin_workout_id": p.garmin_workout_id,
        "pushed_at": p.pushed_at.isoformat() if p.pushed_at else None,
    }


def _day_changed(existing: PlanDay | None, new: dict) -> bool:
    if existing is None:
        return True
    return (
        existing.workout_type != new["workout_type"]
        or existing.title != new["title"]
        or existing.duration_min != new.get("duration_min")
        or existing.distance_km != new.get("distance_km")
        or existing.target_pace != new.get("target_pace")
        or existing.target_hr_low != new.get("target_hr_low")
        or existing.target_hr_high != new.get("target_hr_high")
        or existing.steps != new.get("steps")
    )


_UNICODE_ESCAPE = re.compile(r"\\u([0-9a-fA-F]{4})")
# Em-dash / em-dash-lookalikes (— ― and the "long" horizontal bar) with any
# surrounding whitespace. Athlete-facing prose should never carry these — they
# read as "an AI wrote this". En-dashes are left alone (legit in ranges).
_EM_DASH = re.compile(r"\s*[—―⸺⸻]\s*")


def strip_em_dashes(s: str | None) -> str | None:
    """Replace em-dashes with a spaced hyphen (the house style), collapsing any
    surrounding whitespace. Deterministic guarantee behind the prompt rule."""
    if not s:
        return s
    return _EM_DASH.sub(" - ", s)


def clean_llm_text(s: str | None) -> str | None:
    """Normalize model prose before we persist/show it: decode stray literal
    unicode escapes (a model that over-escapes an em-dash as the 6 characters
    `\\u2014`), then strip em-dashes (an AI tell). No-op on already-clean text."""
    if not s:
        return s
    s = _UNICODE_ESCAPE.sub(lambda m: chr(int(m.group(1), 16)), s)
    return strip_em_dashes(s)


# --- persona lint ----------------------------------------------------------------
# Deterministic checks behind the persona prompts (same belt-and-braces idea as
# strip_em_dashes): the prompt asks, this verifies. Violations are logged in
# production (every real note doubles as an eval sample) and hard-asserted in
# the opt-in eval suite (tests/test_persona_evals.py). Detection only — a bad
# rewrite would be worse than a logged miss, so nothing is auto-edited here.

# Stock openers _HOUSE_STYLE bans; a uniform opening is the loudest AI tell.
_STOCK_OPENERS = ("solid run", "today's plan is", "you look well recovered")

# App-internal load indices. No human coach texts an athlete "TSB is -2.1",
# whatever their persona — these are banned in athlete-facing text for everyone.
_INDEX_JARGON = re.compile(r"\b(?:TSB|ACWR|CTL|ATL)\b")

# Training-science vocabulary the chill persona (Koa) must translate away.
# bpm and pace targets are deliberately NOT matched: a plainly-phrased workout
# target is allowed by the persona rules.
_CHILL_JARGON = re.compile(
    r"\b(?:HRV|RPE|VO2\s?max)\b|\bz\s?[1-5]\b|\bzone\s+[1-5]\b",
    re.IGNORECASE,
)

# Numeric dashboard citations ("readiness is green at 83", "score of 62").
# Sam (default) is data-fluent and may cite one deliberately; Koa translates
# metrics into body feel and Viktoria gives orders, not evidence — for both,
# a score citation is dashboard-speak in a human voice.
_SCORE_CITES = re.compile(
    r"\breadiness(?:\s+score)?(?:\s+(?:of|is|was|at|sits))?"
    r"(?:\s+(?:green|yellow|red))?(?:\s+at)?\s+\d+"
    r"|\b(?:execution\s+)?score\s+(?:of|is|was|at)\s+\d+"
    r"|\ban?\s+\d+(?:\.\d+)?\s+(?:execution\s+)?score\b"
    r"|\bexecution\s+average\s+(?:of|is|was|at)\s+\d+",
    re.IGNORECASE,
)


def persona_lint(style: str, text: str | None) -> list[str]:
    """Mechanical persona-adherence violations in athlete-facing prose.
    Empty list = clean. Only rules that regex can judge reliably live here;
    tone is the LLM judge's job in the eval suite."""
    if not text:
        return []
    out = []
    for opener in _STOCK_OPENERS:
        if text.lstrip().lower().startswith(opener):
            out.append(f"stock opener {opener!r}")
            break
    if _EM_DASH.search(text):
        out.append("em-dash in athlete-facing text")
    for m in _INDEX_JARGON.finditer(text):
        out.append(f"app-internal index in athlete-facing text: {m.group(0)!r}")
    if style == "chill":
        for m in _CHILL_JARGON.finditer(text):
            out.append(f"raw metric/jargon in chill voice: {m.group(0)!r}")
    if style in ("chill", "strict"):
        for m in _SCORE_CITES.finditer(text):
            out.append(f"dashboard score citation in {style} voice: {m.group(0)!r}")
    return out


def log_persona_lint(style: str | None, text: str | None, where: str) -> None:
    """Production tap: warn on any lint violation so real notes accumulate as
    persona-eval data without extra LLM calls."""
    for v in persona_lint(style or "default", text):
        log.warning("persona lint (%s, %s): %s", style or "default", where, v)


def apply_plan_days(
    db: Session, user_id: int, days: list[dict], source: str, summary: str
) -> list[PlanDay]:
    """Upsert plan days; returns the rows whose workout materially changed
    (the set that needs re-pushing to the watch)."""
    version = PlanVersion(user_id=user_id, source=source, summary=summary, snapshot=days)
    db.add(version)
    db.flush()

    changed: list[PlanDay] = []
    for d in days:
        date = dt.date.fromisoformat(d["date"])
        existing = db.get(PlanDay, (user_id, date))
        if existing is not None and existing.status != "planned":
            continue  # never rewrite completed/skipped days
        # Hard guard: an other-sport intent day can never receive a run, even if
        # the model (or an edit) tries — coerce to cross_train titled by the sport.
        intent = db.get(DayIntent, (user_id, date))
        if intent is not None and d.get("workout_type") in RUN_TYPES_PLAN:
            d = {
                **d,
                "workout_type": "cross_train",
                "title": intent.sport.capitalize(),
                "description": intent.note or f"{intent.sport} day",
                "duration_min": intent.duration_min,
                "distance_km": None,
                "target_pace": None,
                "target_hr_low": None,
                "target_hr_high": None,
                "steps": None,
                "rationale": f"Reserved for {intent.sport} (your day intent).",
            }
        materially_changed = _day_changed(existing, d)
        row = existing or PlanDay(user_id=user_id, date=date)
        row.workout_type = d["workout_type"]
        row.title = clean_llm_text(d["title"])
        row.description = clean_llm_text(d.get("description")) or ""
        row.duration_min = d.get("duration_min")
        row.distance_km = d.get("distance_km")
        row.target_pace = d.get("target_pace")
        row.target_hr_low = d.get("target_hr_low")
        row.target_hr_high = d.get("target_hr_high")
        row.steps = d.get("steps") or None  # [] normalizes to null
        row.rationale = clean_llm_text(d.get("rationale")) or ""
        row.version_id = version.id
        if materially_changed:
            row.pushed_at = None  # stale on the watch until re-pushed
            changed.append(row)
        db.add(row)
    db.commit()
    return changed


QUALITY_TYPES = {"tempo", "intervals", "race"}
EASY_TYPES = {"easy_run", "recovery", "long_run"}


def pace_violations(days: list[dict], profile: dict | None) -> list[str]:
    """Deterministic guard: prescribed day-level paces must stay anchored to
    the athlete's observed paces. Easy-type days may not be more than ~7%
    faster than the typical recent whole-run pace; quality days may not be
    more than ~10% faster than the fastest recent whole-run average (interval
    WORK steps legitimately go faster, so only day-level targets are checked).
    """
    if not profile:
        return []
    out: list[str] = []
    typical = profile["typical_pace_s"]
    fastest = profile["fastest_avg_pace_s"]
    for d in days:
        sec = metrics.pace_seconds(d.get("target_pace"))
        if sec is None:
            continue
        wt = d.get("workout_type")
        if wt in EASY_TYPES and sec < typical * 0.93:
            out.append(
                f"{d.get('date')} ({wt}): {d.get('target_pace')}/km is far faster than "
                f"the athlete's typical recent pace {profile['typical_pace']}/km — easy days "
                "must be at or slower than the typical pace"
            )
        elif sec < fastest * 0.90:
            out.append(
                f"{d.get('date')} ({wt}): {d.get('target_pace')}/km is >10% faster than "
                f"anything the athlete has recently averaged (best {profile['fastest_avg_pace']}/km)"
            )
    return out


def check_week(days: list[dict], budget: int,
               chronic_daily_load: float | None = None) -> list[str]:
    """Deterministic post-checks on a generated week; returns warning strings.

    The prompt states these rules; this verifies the model obeyed. Warnings are
    logged (and asserted in evals) rather than silently 'repaired' — a repair
    would desync the plan from its rationales."""
    warnings: list[str] = []
    quality = [d for d in days if d.get("workout_type") in QUALITY_TYPES]
    if len(quality) > budget:
        warnings.append(f"quality days {len(quality)} exceed budget {budget}")

    # Ramp guardrail (Idea E): the authored week's projected load vs what the
    # athlete is adapted to. Only meaningful above the chronic floor.
    if chronic_daily_load and chronic_daily_load >= metrics.RAMP_FLOOR:
        planned_avg = sum(metrics.planned_day_load(d) for d in days) / 7.0
        projected = planned_avg / chronic_daily_load
        if projected > metrics.RAMP_CAUTION:
            warnings.append(
                f"planned week projects acwr {projected:.2f} vs chronic load "
                f"{chronic_daily_load:.0f}/day (cap ~{metrics.RAMP_CAUTION})")

    def minutes(d: dict) -> float:
        if d.get("duration_min"):
            return float(d["duration_min"])
        if d.get("distance_km"):
            return float(d["distance_km"]) * 6.0  # ~6 min/km rough easy pace
        return 0.0

    total = sum(minutes(d) for d in days if d.get("workout_type") != "cross_train")
    hard = sum(minutes(d) for d in quality)
    if total > 0 and hard / total > 0.35:
        warnings.append(f"hard time {hard / total:.0%} of week (target ~20%, cap 35%)")
    return warnings


def generate_plan(db: Session, user_id: int, source: str = "daily_job") -> list[PlanDay]:
    """The daily pipeline step: snapshot -> one structured LLM call -> upsert.

    Returns the changed days (caller decides whether to auto-push).
    """
    today = dt.date.today()
    settings = get_settings(db, user_id)
    snapshot = build_snapshot(db, user_id, today)

    client = make_client(settings.get("llm_provider"), user_id=user_id, call_site="plan")
    system = SYSTEM_PROMPT + style_prompt(settings)
    messages = [
        {
            "role": "user",
            "content": "Athlete state snapshot (JSON):\n"
            + json.dumps(snapshot, indent=1)
            + f"\n\nProduce the plan for the 7 days starting {today.isoformat()}.",
        }
    ]
    result = client.complete_structured(
        system=system, messages=messages, schema=PLAN_SCHEMA, name="training_plan",
    )

    days = [d for d in result.get("days", []) if d.get("date")]
    # Pace guard: one corrective retry when targets drift from observed paces.
    violations = pace_violations(days, snapshot.get("recent_pace_profile"))
    if violations:
        log.warning("plan pace guard (user %s), retrying once: %s", user_id, violations)
        result = client.complete_structured(
            system=system,
            messages=messages + [
                {"role": "assistant", "content": json.dumps(result)},
                {"role": "user", "content":
                    "These target paces are not grounded in the athlete's actual "
                    "recent paces (recent_pace_profile):\n- " + "\n- ".join(violations)
                    + "\nRevise the plan so every pace respects the grounding rules."},
            ],
            schema=PLAN_SCHEMA,
            name="training_plan",
        )
        days = [d for d in result.get("days", []) if d.get("date")]
        for v in pace_violations(days, snapshot.get("recent_pace_profile")):
            log.warning("plan pace guard STILL violated (user %s): %s", user_id, v)
    chronic = (snapshot.get("load_ramp") or {}).get("chronic_daily_load")
    for warning in check_week(days, snapshot["quality_budget"], chronic):
        log.warning("plan check (user %s): %s", user_id, warning)
    changed = apply_plan_days(db, user_id, days, source, result.get("adjustment_note", ""))
    # Strength lane (author mode places directly — the athlete's own plan, no
    # approval step). Clamped to what the weekly target still allows.
    strength = snapshot.get("strength")
    if strength:
        budget = max(0, strength["target_per_week"] - strength["done_this_week"])
        placed = support_mod.apply_sessions(
            db, user_id, result.get("strength_sessions") or [],
            source="author", today=today, target=budget, replace=True)
        log.info("strength placed (%s): %d sessions", source, len(placed))
    log.info("plan generated (%s): %d days, %d changed", source, len(days), len(changed))
    return changed


# --- editor base: materialize Garmin's coach plan into plan_days -------------

# Days materialization is allowed to refresh. A user-accepted edit ("chat_edit")
# or a hand edit ("manual") is an OVERRIDE and must never be re-copied over.
_OVERWRITABLE_SOURCES = {"garmin_mirror", "daily_job", "onboarding", "daily_review"}

# Coach taskList trainingEffectLabel -> our workout_type (name hints refine it).
_TE_TO_TYPE = {
    "LACTATE_THRESHOLD": "tempo",
    "TEMPO": "tempo",
    "VO2MAX": "intervals",
    "ANAEROBIC_CAPACITY": "intervals",
    "SPEED": "intervals",
    "RECOVERY": "recovery",
    "AEROBIC_BASE": "easy_run",
}


def _coach_workout_type(task: dict) -> str:
    if task.get("rest_day"):
        return "rest"
    if "long" in (task.get("name") or "").lower():
        return "long_run"
    return _TE_TO_TYPE.get((task.get("training_effect") or "").upper(), "easy_run")


def _parse_hr(desc: str | None) -> int | None:
    """Pull the single HR target out of a coach description like '18:00@172bpm'."""
    if not desc:
        return None
    m = re.search(r"(\d{2,3})\s*bpm", desc)
    return int(m.group(1)) if m else None


def _is_override(db: Session, day: PlanDay) -> bool:
    """A day owned by a user-accepted/hand edit — materialization must not touch it."""
    if day.version_id is None:
        return False  # legacy auto-authored base
    version = db.get(PlanVersion, day.version_id)
    return version is not None and version.source not in _OVERWRITABLE_SOURCES


def _coach_day_fields(db: Session, user_id: int, date: dt.date, task: dict) -> dict:
    """The PlanDay fields for a mirrored Garmin coach task on `date`.

    A committed other-sport day is never overwritten with a Garmin run — it is
    coerced to cross_train, the same hard guard apply_plan_days enforces.
    """
    intent = db.get(DayIntent, (user_id, date))
    if intent is not None:
        return {
            "workout_type": "cross_train",
            "title": intent.sport.capitalize(),
            "description": intent.note or f"{intent.sport} day",
            "duration_min": intent.duration_min,
            "target_hr_low": None, "target_hr_high": None,
        }
    wt = _coach_workout_type(task)
    hr = _parse_hr(task.get("description"))
    return {
        "workout_type": wt,
        "title": task.get("name") or ("Rest" if wt == "rest" else wt.replace("_", " ").title()),
        "description": task.get("description") or "",
        "duration_min": task.get("duration_min"),
        "target_hr_low": hr, "target_hr_high": hr,
    }


def _write_coach_day(row: PlanDay, fields: dict, version_id: int) -> None:
    """Stamp a PlanDay with the Garmin base fields (no Idaten rationale)."""
    row.workout_type = fields["workout_type"]
    row.title = fields["title"]
    row.description = fields["description"]
    row.duration_min = fields["duration_min"]
    row.distance_km = None
    row.target_pace = None
    row.target_hr_low = fields["target_hr_low"]
    row.target_hr_high = fields["target_hr_high"]
    row.steps = None
    row.rationale = ""  # base plan carries no Idaten rationale, by design
    row.status = "planned"
    row.version_id = version_id


def materialize_coach_plan(
    db: Session, user_id: int, today: dt.date | None = None, horizon_days: int = 14,
) -> list[PlanDay]:
    """Copy the mirrored Garmin coach taskList into plan_days as the editor base.

    Idempotent and override-safe (see the materialization-vs-accepted-diff
    decision): refreshes only days that are still the Garmin base or old
    auto-authored plan and still `planned`; NEVER overwrites a user override
    (chat_edit/manual) or a completed/skipped day. The base carries no Idaten
    rationale — only days Idaten diffs get a coach note. Returns the rows whose
    workout materially changed (the set needing a re-push).
    """
    today = today or dt.date.today()
    plan = db.get(TrainingPlan, user_id)
    if plan is None:
        return []
    horizon = (today + dt.timedelta(days=horizon_days)).isoformat()
    tasks = [
        t for t in (plan.upcoming_tasks or [])
        if t.get("date") and today.isoformat() <= t["date"] <= horizon
    ]
    if not tasks:
        return []

    version = PlanVersion(user_id=user_id, source="garmin_mirror",
                          summary=f"Garmin coach plan · {plan.name}", snapshot=tasks)
    db.add(version)
    db.flush()

    changed: list[PlanDay] = []
    for t in tasks:
        date = dt.date.fromisoformat(t["date"])
        existing = db.get(PlanDay, (user_id, date))
        if existing is not None and (existing.status != "planned" or _is_override(db, existing)):
            continue
        new = _coach_day_fields(db, user_id, date, t)
        materially = _day_changed(existing, new)
        row = existing or PlanDay(user_id=user_id, date=date)
        _write_coach_day(row, new, version.id)
        if materially:
            row.pushed_at = None  # stale on the watch until re-pushed
            changed.append(row)
        db.add(row)
    db.commit()
    return changed


def edited_days_in_window(
    db: Session, user_id: int, start: dt.date, end: dt.date,
) -> list[dt.date]:
    """Planned days in [start, end] that carry an Idaten/hand override — i.e. the
    days for which a 'revert to Garmin' action is meaningful."""
    days = db.scalars(
        select(PlanDay).where(PlanDay.user_id == user_id,
                              PlanDay.date >= start, PlanDay.date <= end,
                              PlanDay.status == "planned").order_by(PlanDay.date)
    ).all()
    return [d.date for d in days if _is_override(db, d)]


def revert_to_garmin(
    db: Session, user_id: int, dates: list[dt.date], today: dt.date | None = None,
) -> list[dt.date]:
    """Force-restore the given days to the mirrored Garmin coach workout, dropping
    any Idaten override.

    Unlike `materialize_coach_plan`, this INTENTIONALLY overwrites overrides
    (chat_edit/manual) — it is the user explicitly asking for the original
    Garmin plan back. Completed/skipped days are left alone (nothing to revert).
    Idaten's pushed watch workout is cleared so the native Garmin Coach workout
    stands; we do NOT push a Garmin copy. Returns the dates actually reverted.
    """
    today = today or dt.date.today()
    plan = db.get(TrainingPlan, user_id)
    if plan is None:
        return []
    tasks_by_date = {t["date"]: t for t in (plan.upcoming_tasks or []) if t.get("date")}

    version = PlanVersion(user_id=user_id, source="garmin_mirror",
                          summary=f"Reverted to Garmin coach plan · {plan.name}",
                          snapshot=[tasks_by_date[d.isoformat()]
                                    for d in dates if d.isoformat() in tasks_by_date])
    db.add(version)
    db.flush()

    reverted: list[dt.date] = []
    for date in dates:
        task = tasks_by_date.get(date.isoformat())
        if task is None:  # outside the mirror window — no Garmin original to restore
            continue
        existing = db.get(PlanDay, (user_id, date))
        if existing is not None and existing.status != "planned":
            continue  # completed/skipped — leave history intact
        row = existing or PlanDay(user_id=user_id, date=date)
        _write_coach_day(row, _coach_day_fields(db, user_id, date, task), version.id)
        db.add(row)
        reverted.append(date)
    db.commit()

    # Clear Idaten's pushed workout for each reverted day; the native Garmin
    # Coach workout already lives on the watch, so no re-push (Will's call).
    from .garmin import push
    for date in reverted:
        row = db.get(PlanDay, (user_id, date))
        if row is not None and row.garmin_workout_id:
            try:
                push.unpush_day(db, row)
            except Exception as e:  # noqa: BLE001
                log.warning("unpush on revert failed for %s: %s", date, e)
    return reverted


# --- week reorder: drag-to-swap whole days on the Week page ------------------

class ReorderError(ValueError):
    """A reorder request that violates the reorder contract (422 at the API)."""


# The fields that travel when a day's content moves to another date. Date-
# anchored facts (execution, cycle) and push state are intentionally absent —
# push state is rebuilt by the re-push pass.
_REORDER_CONTENT_FIELDS = (
    "workout_type", "title", "description", "duration_min", "distance_km",
    "target_pace", "target_hr_low", "target_hr_high", "steps", "rationale",
)


def reorder_week(
    db: Session, user_id: int, moves: list[dict], today: dt.date | None = None,
) -> dict:
    """Apply a whole-day content permutation within one week, atomically.

    `moves` is [{date, content_from}, ...]: after the reorder, `date` carries
    the content that lived on `content_from`. The moves must form a permutation
    of one set of dates, all today-or-future, all in one ISO week, all with a
    planned PlanDay row. Intents and planned strength sessions ride with their
    day. Previously pushed content is deleted from the watch and re-pushed at
    its new date; a failed re-push leaves the day unpushed (never stale).
    """
    today = today or dt.date.today()
    try:
        pairs = [(dt.date.fromisoformat(m["date"]),
                  dt.date.fromisoformat(m["content_from"])) for m in moves]
    except (KeyError, TypeError, ValueError):
        raise ReorderError("moves must be [{date, content_from}] with YYYY-MM-DD dates")
    pairs = [(t, s) for t, s in pairs if t != s]
    if not pairs:
        return {"moved": [], "push_errors": []}

    targets = [t for t, _ in pairs]
    if len(set(targets)) != len(targets) or set(targets) != {s for _, s in pairs}:
        raise ReorderError("moves must be a permutation of one set of dates")
    if min(targets) < today:
        raise ReorderError("past days cannot be reordered")
    if len({t - dt.timedelta(days=t.weekday()) for t in targets}) > 1:
        raise ReorderError("reorder is limited to a single week")

    rows: dict[dt.date, PlanDay] = {}
    for d in targets:
        row = db.get(PlanDay, (user_id, d))
        if row is None:
            raise ReorderError(f"no plan on {d.isoformat()}")
        if row.status != "planned":
            raise ReorderError(f"{d.isoformat()} is {row.status} and cannot move")
        rows[d] = row

    # Snapshot the moving content (and its push state) before any mutation.
    content = {d: {f: getattr(rows[d], f) for f in _REORDER_CONTENT_FIELDS}
               for d in targets}
    was_pushed = {d: rows[d].pushed_at is not None for d in targets}
    intents = {d: i for d in targets
               if (i := db.get(DayIntent, (user_id, d))) is not None}
    strength = {d: support_mod.week_sessions(db, user_id, d, d) for d in targets}

    version = PlanVersion(
        user_id=user_id, source="reorder",
        summary=f"Rearranged the week by hand: {len(pairs)} days moved",
        snapshot=[plan_day_dict(rows[d]) for d in sorted(targets)])
    db.add(version)
    db.flush()

    for t, s in pairs:
        for f in _REORDER_CONTENT_FIELDS:
            setattr(rows[t], f, content[s][f])
        rows[t].version_id = version.id
        db.add(rows[t])

    # Intents and planned strength ride with their day's content. DayIntent's
    # PK includes date, so a move is delete + re-insert.
    for i in intents.values():
        db.delete(i)
    db.flush()
    for t, s in pairs:
        if (i := intents.get(s)) is not None:
            db.add(DayIntent(user_id=user_id, date=t, sport=i.sport, note=i.note,
                             duration_min=i.duration_min, effort=i.effort,
                             source=i.source))
        for sess in strength.get(s, []):
            if sess.status == "planned":
                sess.date = t
                db.add(sess)
    # ONE commit for the whole rearrangement (and its version row): a failure
    # anywhere above rolls everything back — no half-swapped week, no orphaned
    # reorder event for the coach to report on. Watch calls stay outside it.
    db.commit()

    # The watch, best-effort after the plan is safely written: delete every
    # involved pushed workout (the old arrangement), then re-push content that
    # was on the watch at its new date. unpush_day tolerates already-gone
    # workouts; a failed re-push leaves the day unpushed, never stale.
    from .garmin import push
    push_errors: list[str] = []
    for d in targets:
        if rows[d].garmin_workout_id:
            push.unpush_day(db, rows[d])
    for t, s in pairs:
        if was_pushed[s] and rows[t].workout_type in push.PUSHABLE_TYPES:
            try:
                push.push_day(db, rows[t])
            except Exception as e:  # noqa: BLE001
                push_errors.append(f"{t.isoformat()}: {e}")
                log.warning("re-push after reorder failed for %s: %s", t, e)

    log.info("week reordered (user %s): %d days moved, %d re-push errors",
             user_id, len(pairs), len(push_errors))
    return {"moved": [t.isoformat() for t in sorted(targets)],
            "push_errors": push_errors}


# --- daily review (editor-above-the-DSW) -------------------------------------

def create_pending_edit(
    db: Session, user_id: int, days: list[dict], summary: str, rationale: str,
    today: dt.date | None = None, strength: list[dict] | None = None,
) -> tuple[PendingEdit | None, dict | None]:
    """Create a superseding pending plan edit, guarded by the pace profile.

    The single path to a proposal, shared by the chat tool and the daily review,
    so both get identical grounding + supersession. Returns (edit, None) on
    success or (None, error_dict) when there are no days or the pace guard
    rejects a target (the error echoes the profile so the caller can re-propose).
    `strength` attaches strength-lane placements to the same proposal (validated
    against the athlete's weekly target); a proposal may be strength-only.
    """
    today = today or dt.date.today()
    strength_valid: list[dict] = []
    if strength:
        target = (get_settings(db, user_id).get("strength") or {}).get(
            "sessions_per_week") or 0
        strength_valid = [
            {"date": d.isoformat(), "duration_min": raw.get("duration_min"),
             "focus": str(raw.get("focus") or ""),
             "rationale": str(raw.get("rationale") or "")}
            for d, raw in support_mod._valid_sessions(
                strength, today, today + dt.timedelta(days=6), target)
        ]
    if not days and not strength_valid:
        return None, {"error": "no days provided"}
    profile = metrics.pace_profile(db, user_id, today)
    violations = pace_violations(days, profile)
    if violations:
        return None, {
            "error": "proposal rejected by the pace guard",
            "violations": violations,
            "recent_pace_profile": profile,
            "note": "Re-propose with paces grounded in the athlete's actual "
                    "recent paces (easy days at or slower than typical_pace).",
        }
    current: list[dict | None] = []
    for d in days:
        try:
            existing = db.get(PlanDay, (user_id, dt.date.fromisoformat(d["date"])))
        except (ValueError, KeyError):
            return None, {"error": f"invalid date in {d!r}"}
        current.append(plan_day_dict(existing) if existing else None)
    # One pending edit at a time (per user): a new proposal supersedes older
    # ones. "superseded" (not "dismissed") so the UI can say what happened.
    for old in db.scalars(select(PendingEdit).where(PendingEdit.user_id == user_id,
                                                    PendingEdit.status == "pending")):
        old.status = "superseded"
    edit = PendingEdit(
        user_id=user_id, summary=clean_llm_text(summary), rationale=clean_llm_text(rationale),
        changes=days, current=[c for c in current if c],
        strength=strength_valid or None,
    )
    db.add(edit)
    db.commit()
    return edit, None


# One changed day in a review proposal — the same shape the planner emits, so
# an accepted proposal flows through apply_plan_days unchanged.
_REVIEW_DAY_ITEM = PLAN_SCHEMA["properties"]["days"]["items"]

REVIEW_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "coach_note": {
            "type": "string",
            "description": (
                "2-4 warm sentences to the athlete for today, ALWAYS present even "
                "when nothing changes. Ground every claim in a real number from the "
                "snapshot (readiness/level, HRV vs baseline, TSB/ACWR, VO2max or "
                "race-predictor direction vs the goal). No fabricated metrics."
            ),
        },
        "should_propose": {
            "type": "boolean",
            "description": (
                "True ONLY when the data clearly warrants changing the plan (a "
                "readiness red-flag on a hard day, hard sessions clustered without "
                "recovery, a structural spacing problem) OR when unplaced strength "
                "sessions should be offered (strength_sessions filled, days may be "
                "[]). False when the plan is sound — most days are false; do not "
                "invent churn."
            ),
        },
        "proposal": {
            "type": ["object", "null"],
            "description": (
                "The change when should_propose is true; null otherwise. Include "
                "only the days that change. A proposal may be strength-only: "
                "days [] with strength_sessions filled."
            ),
            "properties": {
                "summary": {"type": "string", "description": "One line, e.g. 'Ease Thursday threshold to easy — HRV 28% below baseline'"},
                "rationale": {"type": "string", "description": "Why, citing the athlete's data"},
                "days": {"type": "array", "items": _REVIEW_DAY_ITEM},
                "strength_sessions": {
                    "type": "array",
                    "description": (
                        "Strength placements to propose (empty unless the "
                        "snapshot's strength block warrants placing sessions)."
                    ),
                    "items": PLAN_SCHEMA["properties"]["strength_sessions"]["items"],
                },
            },
            "required": ["summary", "rationale", "days", "strength_sessions"],
            "additionalProperties": False,
        },
    },
    "required": ["coach_note", "should_propose", "proposal"],
    "additionalProperties": False,
}

REVIEW_SYSTEM_PROMPT = """\
You are an experienced running coach doing the athlete's daily plan review.

Your job is NOT to write a training plan. It is to (1) always write a short,
grounded coach_note for today, and (2) propose a change only when the data
clearly warrants one.

editor mode (an active Garmin Coach plan is present):
- `current_upcoming_plan` (and `todays_prescribed_workout`) is the athlete's
  ACTUAL plan — Garmin's base with any edits they've already accepted applied.
  This is what they will do. GROUND the coach_note on it: when you reference
  today's or an upcoming session, cite `todays_prescribed_workout` /
  `current_upcoming_plan`, NEVER a workout from `garmin_coach_plan` that their
  plan has since changed (e.g. don't tell them to save energy for a VO2 session
  that their plan now shows as rest). `structural_signals` is already computed
  from this actual plan.
- `garmin_coach_plan` is CONTEXT only: its phase and week number are ground truth
  (never treat the athlete as starting from week 1), and it shows what Garmin
  currently suggests. Use it to spot where Garmin has diverged from their plan —
  but do not quote its workouts as if they were the athlete's plan.
- Do NOT rewrite the week or fight the plan. You sit ABOVE Garmin's day-by-day
  suggestions: your edge is multi-day structure Garmin's greedy daily logic misses.
- Propose a change only for a clear reason: a hard session prescribed on a
  readiness red-flag day, or structural_signals showing hard days clustered
  (max_consecutive_hard_days >= 2, or a hard day with min_gap_between_hard_days
  of 0-1 on a suppressed-readiness day). When the plan is sound, should_propose
  is false and you simply write an encouraging, honest coach_note.

author mode (no Garmin plan): you may propose the day-level fixes the athlete's
plan needs, same grounding rules — but still prefer the smallest change.

Always, in both modes:
- Respect readiness guardrails: suppressed HRV, poor sleep, or very negative TSB
  means ease intensity — never stack hard on a red flag.
- menstrual_cycle (only present if the athlete tracks it): when
  `ease_recommended` is true — the 2-3 days before the predicted period start
  (phase 'premenstrual') and the first 1-2 days of flow (phase 'menstrual') —
  lean toward LESS taxing work: soften a prescribed hard session, or on a very
  low-readiness early-flow day consider rest. This is a gentle bias, not a
  hard rule: don't rewrite easy/rest days that are already appropriate, and
  don't churn a sound plan. Mention it in the coach_note with care and warmth
  (e.g. 'keeping today lighter with your cycle in mind'), never clinically.
  Conversely, in phase 'follicular' (the days after flow ends) many athletes
  feel strongest — when readiness is also good, you may GREEN-LIGHT a quality
  session the plan already calls for, or encourage the athlete to attack it.
  Still don't invent hard work the plan doesn't have; just remove hesitation.
- active_niggles (only present while the athlete has reported pain that hasn't
  cleared): each entry is an open issue with a body part, a severity — 1
  'niggle' (minor, monitor it), 2 'pain' (real pain, actively protect it), 3
  'injury' — days_open, and the athlete's own note. While anything is open,
  bias DOWN: for a severity-1 niggle keep the plan honest but avoid stacking
  hard sessions and watch load on that area; for severity 2-3 lean firmly
  toward easing the affected work, cross-training, or rest, and propose an
  ease-off when a hard session lands while it's open. An open severity >= 2
  issue VETOES any green-light: never encourage progression or attacking a
  session while the athlete is in real pain, no matter how good readiness or
  execution scores look. Mention it in the coach_note warmly and by body part
  ('keeping Thursday light while the knee settles'), never clinically, and
  never guilt the athlete for it. As always: suggest, don't churn — an easy or
  rest day that's already appropriate needs no edit.
- execution_signals (only present once runs have been scored): recent workout
  EXECUTION scores (0-100 — how closely the athlete hit the prescribed HR/pace
  targets, newest first). A run of low scores (`low_streak` >= 2, or a low
  `avg_score`) means they are repeatedly missing the intended intensity — a sign
  of accumulated fatigue or an over-ambitious plan — so lean toward easing the
  next hard session or banking recovery, and name it warmly in the coach_note
  ('your last couple of sessions have been a grind — let's bank some easy
  miles'). Consistently high scores mean they're executing well and, with good
  readiness, you can green-light progression. Don't over-react to one off day,
  and remember a low score can be over-cooking an easy run as much as
  under-hitting a hard one — read it with the prescribed workout in mind.
- load_ramp (only present with real training history): the multi-week volume
  guardrail — 7-day vs 28-day training load ("too much, too soon"). `zone` is
  the deterministic verdict: 'high' (ratio held > 1.5 for 3+ days) means the
  athlete is ramping faster than their body is adapted to — propose trimming
  volume from the least important upcoming session (protect the long run's
  progression last); 'caution' means watch it — avoid ADDING volume and say so
  warmly if relevant. `planned_next_week.zone` projects the ratio IF the
  athlete executes the upcoming plan — a 'high' there is grounds to propose a
  trim even when today looks fine. `chronic_trend` = 'detraining' (chronic load
  down vs 3 weeks ago, e.g. after illness/travel) with a race approaching means
  rebuild GENTLY toward plan rather than jumping back to full volume — and when
  readiness is good and the ramp is safe, it's also license to encourage
  building. One down week never justifies alarm (the 28-day baseline absorbs
  it); never cite raw ratio numbers in the coach_note — speak in plain terms
  ('your volume has climbed quickly these two weeks').
- Non-run sessions in recent_activities (strength, yoga, rides, hikes…) are
  REAL training, not idle days — their load already counts in the training-load
  aggregates. Acknowledge them naturally when relevant ('good strength session
  yesterday'), factor them into fatigue reasoning (heavy legs the day after
  strength work is normal, not a red flag), and never describe a day with one
  as having done nothing. Do not score or critique them — they aren't
  prescribed workouts.
- strength (only present when the athlete set a weekly strength target in
  Settings): the athlete's own contract — target_per_week sessions, with
  done_this_week / planned_upcoming / remaining_to_plan computed for you.
  A planned or completed strength day is part of the week's load: don't stack
  a hard run the morning after a heavy strength session. Acknowledge a
  completed session briefly and warmly when it's relevant to today; NEVER nag
  about missed sessions. When remaining_to_plan > 0 and suitable days remain
  ahead (on/after easy or rest days, never the day before a quality session or
  the long run), you MAY attach placements via the proposal's
  strength_sessions — a proposal can be strength-only (should_propose true,
  days []). Place once, early in the week, 20-40 min each; if the athlete
  dismisses it, let it go (this is enforced too). Mention the placement in the
  coach_note naturally ('I've suggested a short strength session Thursday').
  An open niggle makes prevention-focused strength work worth an encouraging
  mention and biases the placement's focus (knee → hips/glutes, achilles →
  calves).
- The coach_note is the athlete's daily touchpoint. Be specific and cite numbers;
  when things are on track, say so and why (e.g. 'VO2max 52->53 and your Riegel
  half prediction now clears your goal pace'). Never manufacture enthusiasm or
  cite a metric that isn't in the snapshot.
- Proposal paces/HR follow the athlete's training_mode and the pace grounding
  rules; a proposal with ungrounded-fast paces will be rejected.

Return only data conforming to the schema.
"""


def _todays_prescribed(snapshot: dict, today: dt.date) -> dict | None:
    """Today's workout the athlete will actually do: their plan day (Garmin's base
    with any accepted edit already applied), falling back to Garmin's task only
    for a day not yet materialized into plan_days."""
    iso = today.isoformat()
    for d in snapshot.get("current_upcoming_plan") or []:
        if d.get("date") == iso:
            return d
    for t in (snapshot.get("garmin_coach_plan") or {}).get("scheduled_workouts") or []:
        if t.get("date") == iso:
            return t
    return None


def _upcoming_structure(snap: dict, today: dt.date, horizon: dt.date) -> list[dict]:
    """Per-day hard/rest flags over [today, horizon] for the plan the athlete will
    ACTUALLY follow: their plan_day where it exists (Garmin base + accepted edits),
    with Garmin's latest task as the per-day fallback for days not yet
    materialized. This is what structural review reasons over — not Garmin's raw
    taskList, which may have been edited away."""
    from .garmin.training_plan import task_is_hard

    lo, hi = today.isoformat(), horizon.isoformat()
    by_date: dict[str, dict] = {}
    # Garmin tasks are the fallback layer...
    for t in (snap.get("garmin_coach_plan") or {}).get("scheduled_workouts") or []:
        d = t.get("date")
        if d and lo <= d <= hi:
            by_date[d] = {"date": d, "hard": task_is_hard(t), "rest": bool(t.get("rest_day"))}
    # ...the athlete's plan_days override per day (Garmin base + accepted edits).
    for p in snap.get("current_upcoming_plan") or []:
        d = p.get("date")
        if d and lo <= d <= hi:
            by_date[d] = {"date": d, "hard": p.get("workout_type") in QUALITY_TYPES,
                          "rest": p.get("workout_type") == "rest"}
    return [by_date[k] for k in sorted(by_date)]


def build_review_snapshot(db: Session, user_id: int, today: dt.date, mode: str) -> dict:
    """The planner snapshot plus the review-specific facts (mode, structure)."""
    snap = build_snapshot(db, user_id, today)
    snap["mode"] = mode
    horizon = today + dt.timedelta(days=7)

    flags = _upcoming_structure(snap, today, horizon)
    snap["structural_signals"] = metrics.structural_signals(flags)
    snap["execution_signals"] = metrics.execution_signals(db, user_id, today)
    snap["todays_prescribed_workout"] = _todays_prescribed(snap, today)
    return snap


# One review LLM call per user per day even when the scheduler's eager pass and
# the Today page's lazy trigger race: a per-user lock serializes callers, and a
# done-state re-check under the lock makes the loser a no-op.
_eval_locks: dict[int, threading.Lock] = {}
_eval_locks_guard = threading.Lock()


def _eval_lock(user_id: int) -> threading.Lock:
    with _eval_locks_guard:
        return _eval_locks.setdefault(user_id, threading.Lock())


def evaluate_today(
    db: Session, user_id: int, today: dt.date | None = None, *,
    allow_structural_fallback: bool = False,
) -> DailyReview:
    """The daily review: one LLM call producing a coach_note and, when the data
    warrants, a superseding plan proposal.

    Data gate (one LLM call per day, never on absent data): with no health row
    for today and no explicit fallback, this records state `pending_data` and
    returns WITHOUT an LLM call — the caller shows "getting last night's data".
    With `allow_structural_fallback` (the degraded button), it runs structural-
    only and marks `done_structural`.

    Idempotent: a review already completed today is returned as-is, without a
    second LLM call — safe to invoke from both the scheduler and the API.
    """
    today = today or dt.date.today()
    with _eval_lock(user_id):
        existing = db.get(DailyReview, (user_id, today))
        if existing is not None:
            # Another thread (eager scheduler vs lazy page load) may have just
            # finished it; this session's cached copy can be stale.
            db.refresh(existing)
            if existing.state in ("done_full", "done_structural"):
                return existing
        return _evaluate_today_locked(
            db, user_id, today, allow_structural_fallback=allow_structural_fallback)


def _evaluate_today_locked(
    db: Session, user_id: int, today: dt.date, *,
    allow_structural_fallback: bool,
) -> DailyReview:
    settings = get_settings(db, user_id)
    mode = plan_mode(db, user_id, today, settings)
    health_today = db.get(DailyHealth, (user_id, today))
    # A bare row (a sync that ran before Garmin processed the night) is NOT ready
    # data — gate on real recovery content so the review waits for the real thing.
    data_ready = metrics.has_recovery_data(health_today)

    review = db.get(DailyReview, (user_id, today)) or DailyReview(user_id=user_id, date=today)
    review.mode = mode

    if not data_ready and not allow_structural_fallback:
        review.state = "pending_data"
        db.merge(review)
        db.commit()
        return db.get(DailyReview, (user_id, today))

    state = "done_full" if data_ready else "done_structural"
    # Stamp the authoring persona now (not at render time): a later coach
    # switch must never re-attribute a note that another coach wrote.
    review.coach = settings.get("coach_style") or "default"

    # Author mode has no Garmin base to review — Idaten writes the week itself
    # (one LLM call via generate_plan, auto-applied since it's the athlete's own
    # plan) and the coach_note summarizes it. Editor mode falls through to the
    # review flow below.
    if mode == "author":
        changed = generate_plan(db, user_id, source="daily_review")
        if settings.get("auto_push_workouts") and changed:
            from .garmin.push import push_days
            try:
                push_days(db, changed)
            except Exception:  # noqa: BLE001
                log.exception("author-review push failed (user %s)", user_id)
        latest = db.scalars(
            select(PlanVersion).where(PlanVersion.user_id == user_id)
            .order_by(PlanVersion.created_at.desc()).limit(1)
        ).first()
        review.coach_note = clean_llm_text(latest.summary) if latest and latest.summary else \
            "You're on track - this week's plan looks good."
        log_persona_lint(review.coach, review.coach_note, "daily_review_author")
        review.state = state
        review.proposal_id = None
        db.merge(review)
        db.commit()
        log.info("daily review (user %s, author, %s): authored %d changed",
                 user_id, state, len(changed))
        return db.get(DailyReview, (user_id, today))

    # Editor review. Refresh Garmin's adaptive plan FIRST so the base — and the
    # per-day Garmin fallback for any not-yet-materialized day — reflects its
    # LATEST adaptation (Garmin re-plans through the day), then re-materialize so
    # untouched plan_days track Garmin while the athlete's accepted edits are
    # preserved. Best-effort: a Garmin hiccup falls back to the existing mirror
    # and never blocks the review.
    try:
        from .garmin.client import get_garmin, has_garmin
        from .garmin.training_plan import sync_training_plan
        user = db.get(User, user_id)
        if user is not None and has_garmin(user):
            sync_training_plan(db, user_id, get_garmin(user))
            materialize_coach_plan(db, user_id, today)
    except Exception:  # noqa: BLE001
        log.warning("review plan refresh failed (user %s); using existing mirror",
                    user_id, exc_info=True)

    snapshot = build_review_snapshot(db, user_id, today, mode)
    client = make_client(settings.get("llm_provider"), user_id=user_id, call_site="review")
    system = REVIEW_SYSTEM_PROMPT + style_prompt(settings)
    messages = [{
        "role": "user",
        "content": "Athlete state snapshot (JSON):\n" + json.dumps(snapshot, indent=1)
        + f"\n\nReview {today.isoformat()}: write today's coach_note and propose a "
        "change only if the data warrants it.",
    }]
    result = client.complete_structured(
        system=system, messages=messages, schema=REVIEW_SCHEMA, name="daily_review",
    )

    review.coach_note = clean_llm_text(result.get("coach_note", ""))
    log_persona_lint(review.coach, review.coach_note, "daily_review")
    # Freeze the producing inputs + prompt hash so a later rating on this note
    # is a reproducible eval case (COACH_QUALITY.md Stage 1).
    review.snapshot = snapshot
    review.prompt_version = feedback_mod.prompt_version(system)
    review.state = state
    proposal_id = None
    if result.get("should_propose") and result.get("proposal"):
        proposal = result["proposal"]
        strength_sessions = proposal.get("strength_sessions") or []
        # Anti-nag: a strength proposal dismissed this week stays dismissed —
        # the review never re-offers placements until next week (chat still can).
        if strength_sessions and support_mod.strength_proposal_muted(db, user_id, today):
            log.info("review strength placements muted (user %s): dismissed this week",
                     user_id)
            strength_sessions = []
        edit, error = create_pending_edit(
            db, user_id, proposal.get("days") or [],
            proposal.get("summary", ""), proposal.get("rationale", ""), today,
            strength=strength_sessions,
        )
        if error is not None:
            log.warning("review proposal rejected (user %s): %s", user_id,
                        error.get("violations") or error.get("error"))
        elif edit is not None:
            proposal_id = edit.id
    review.proposal_id = proposal_id
    db.merge(review)
    db.commit()
    log.info("daily review (user %s, %s, %s): proposal=%s", user_id, mode, state, proposal_id)
    return db.get(DailyReview, (user_id, today))


EXECUTION_ANALYSIS_SYSTEM_PROMPT = """\
You are the athlete's running coach writing a short post-run note on how well they
EXECUTED today's workout — and what it means for where they're headed.

You're given an execution score (0-100, already computed — how closely they held
the prescribed HR/pace target through each segment) and, when available, a
per-segment breakdown: each segment's label (warmup / interval / recovery /
cooldown / …), its target band, the athlete's actual average, and that segment's
own score. Source 'garmin' means the watch computed the score, 'idaten' means we
did — don't mention which. When there's no segment breakdown (a watch-scored
run), lean on the overall score and the race/trend context instead.

`context` (when present) carries the FORWARD-LOOKING picture:
- context.race: the primary race — name, days_to_race, goal_pace/goal_time, and
  Garmin's predicted finish (predicted_pace / predicted_time_s), with vs_goal_s
  (predicted minus goal in seconds: NEGATIVE = ahead of goal, POSITIVE = behind).
- context.recent_execution: recent execution scores (how consistently they've been
  hitting their targets lately).

Write 2-4 sentences in the coach's voice — specific, warm, and FORWARD-LOOKING:
- Lead with how the run went: nailed it, or where it slipped. If there's a
  breakdown, name the segments that went well and the ones that didn't (e.g. 'you
  held the threshold reps in the band but the recoveries stayed hot').
- Then connect it to the race goal HONESTLY using context: are they trending
  toward the goal or not? If the prediction is behind goal (vs_goal_s positive),
  say so kindly and what would close the gap; if ahead, name it and encourage; if
  it's only one data point or the race is still far off, don't overclaim. NEVER
  fabricate an 'on track' — ground every trajectory claim in vs_goal_s / recent_execution.
- A low score can mean over-cooking an easy run as much as under-hitting a hard
  one — read it against the targets. If they bailed early or a segment scored ~0,
  name it kindly. End on one honest forward nudge.

Never quote the raw score as the whole message — explain the WHY and the SO-WHAT.
Never invent numbers not in the payload. No markdown, no headings, no lists.
"""

EXECUTION_ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {"analysis": {"type": "string"}},
    "required": ["analysis"],
    "additionalProperties": False,
}


def _execution_context(db: Session, user_id: int, date: dt.date) -> dict | None:
    """Forward-looking facts for the post-run note: the primary race's goal vs the
    current prediction, and the recent execution trend. Lets the coach say honestly
    whether the athlete is tracking toward their goal."""
    from . import races
    out: dict = {}
    race = races.primary_race(db, user_id)
    if race is not None:
        rd = races.race_dict(race, races.prediction_context(db, user_id))
        pred = rd.get("prediction") or {}
        # Garmin's race predictor only — Idaten's calibrated prediction (likely_s /
        # delta_s / confidence) is intentionally withheld here too, same as the plan
        # generator and chat coach. vs_goal_s is Garmin's predicted minus the goal.
        garmin_s = pred.get("garmin_time_s")
        goal_s = pred.get("goal_time_s")
        out["race"] = {
            "name": rd["name"],
            "days_to_race": rd["days_to_race"],
            "goal_time": rd.get("goal_time"),
            "goal_pace": pred.get("goal_pace"),
            "predicted_pace": races._pace_str_from_time(garmin_s, race.distance_km),
            "predicted_time_s": garmin_s,
            "vs_goal_s": round(garmin_s - goal_s) if garmin_s and goal_s else None,
        }
    trend = metrics.execution_signals(db, user_id, date)
    if trend is not None:
        out["recent_execution"] = {
            "avg_score": trend["avg_score"],
            "recent_scores": [r["score"] for r in trend["recent"]],
        }
    return out or None


def write_execution_analysis(db: Session, a: Activity) -> tuple[str, str]:
    """One LLM call: a persona-voiced, forward-looking narrative for an already-
    computed execution score. Returns (analysis_text, coach_style) — the caller
    stamps the coach so a later switch never rewrites who wrote it."""
    settings = get_settings(db, a.user_id)
    coach = settings.get("coach_style") or "default"
    client = make_client(settings.get("llm_provider"), user_id=a.user_id,
                         call_site="execution_analysis")
    system = EXECUTION_ANALYSIS_SYSTEM_PROMPT + style_prompt(settings)
    payload = {
        "workout": a.name,
        "type": a.type,
        "distance_km": round(a.distance_m / 1000, 2) if a.distance_m else None,
        "duration_min": round(a.duration_s / 60) if a.duration_s else None,
        "execution_score": a.execution_score,
        "score_source": a.execution_score_source,
        "segments": a.execution_breakdown,
        "rpe": a.rpe or a.garmin_rpe,
        "feel": a.feel,
        "context": _execution_context(db, a.user_id, a.date),
    }
    result = client.complete_structured(
        system=system,
        messages=[{"role": "user",
                   "content": "Run execution (JSON):\n" + json.dumps(payload, indent=1)
                   + "\n\nWrite the post-run execution note."}],
        schema=EXECUTION_ANALYSIS_SCHEMA, name="execution_analysis",
    )
    # Freeze the producing inputs + prompt hash (caller's commit persists them)
    # so a later rating on this analysis is a reproducible eval case.
    a.execution_analysis_context = payload
    a.execution_analysis_prompt_version = feedback_mod.prompt_version(system)
    analysis = clean_llm_text(result.get("analysis", "")) or ""
    log_persona_lint(coach, analysis, "execution_analysis")
    return analysis, coach
