"""HTTP API — see API_CONTRACT.md at the repo root for the frontend contract.

Every data route depends on `current_user` (session cookie). Handlers scope all
queries to that user; nothing below the auth layer trusts client-supplied
identity.
"""

from __future__ import annotations

import datetime as dt
import json
import os
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import (crypto, execution, feedback as feedback_mod, metrics,
               niggles as niggles_mod, rate_limit, races as races_mod, scheduler)
from .config import config
from .auth import (
    COOKIE_NAME,
    SESSION_DAYS,
    admin_user,
    create_invite_token,
    create_session,
    current_user,
    delete_user_data,
    destroy_session,
    get_valid_invite,
    hash_password,
    verify_password,
)
from .chat.agent import run_chat
from .chat.tools import edit_dict
from .db import get_db
from .garmin import backfill
from .garmin.client import drop_client, get_garmin, has_garmin
from .garmin.push import PUSHABLE_TYPES, push_day, push_days, unpush_day
from .models import (
    Activity,
    ChatMessage,
    DailyHealth,
    DailyReview,
    DayIntent,
    Gear,
    LlmUsage,
    PendingEdit,
    PlanDay,
    Race,
    SyncLog,
    TrainingPlan,
    User,
)
from . import planner as planner_mod
from .planner import apply_plan_days, evaluate_today, intent_dict, plan_day_dict, plan_mode
from . import settings_store
from .settings_store import get_settings, put_settings

router = APIRouter(prefix="/api")
auth_router = APIRouter(prefix="/api/auth")


# --- auth ----------------------------------------------------------------------

class LoginBody(BaseModel):
    username: str
    password: str


def _user_dict(u: User) -> dict:
    return {
        "id": u.id,
        "username": u.username,
        "display_name": u.display_name or u.username,
        "garmin_connected": has_garmin(u),
        "garmin_email": u.garmin_email,
        "is_admin": bool(u.is_admin),
    }


@auth_router.post("/login")
def login(body: LoginBody, response: Response, db: Session = Depends(get_db)):
    username = body.username.lower()
    rate_limit.check_login(username)  # 429 before any password work if locked out
    user = db.scalars(select(User).where(User.username == username)).first()
    if user is None or not verify_password(body.password, user.password_hash):
        rate_limit.record_login_failure(username)
        raise HTTPException(401, "invalid username or password")
    rate_limit.clear_login_failures(username)
    token = create_session(db, user)
    response.set_cookie(
        COOKIE_NAME, token,
        max_age=SESSION_DAYS * 86400,
        httponly=True, samesite="lax", secure=config.cookie_secure, path="/",
    )
    return {"ok": True, "user": _user_dict(user)}


@auth_router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    token = request.cookies.get(COOKIE_NAME)
    if token:
        destroy_session(db, token)
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@auth_router.get("/me")
def me(user: User = Depends(current_user)):
    return _user_dict(user)


class ProfileBody(BaseModel):
    display_name: str = Field(min_length=1, max_length=40)


@auth_router.post("/profile")
def update_profile(body: ProfileBody, db: Session = Depends(get_db),
                   user: User = Depends(current_user)):
    name = body.display_name.strip()
    if not name:
        raise HTTPException(422, "display name cannot be blank")
    user.display_name = name
    db.add(user)
    db.commit()
    return _user_dict(user)


# --- membership (admin: invites, removals, password resets) ---------------------

@auth_router.get("/members")
def list_members(db: Session = Depends(get_db), user: User = Depends(admin_user)):
    # Admin-only: the roster (usernames, admin badge, Garmin-connected state) is
    # household administration, not something an invited member should read.
    rows = db.scalars(select(User).order_by(User.id)).all()
    return [{**_user_dict(u), "is_me": u.id == user.id,
             "created_at": u.created_at.isoformat()} for u in rows]


@auth_router.get("/usage")
def usage_summary(days: int = 30, db: Session = Depends(get_db),
                  admin: User = Depends(admin_user)):
    """Admin-only LLM token/cost accounting over the last `days`, broken down by
    user and by call_site (the feature). Cache-hit % shows whether prompt
    caching is paying off. Reads the llm_usage table populated at the seam."""
    days = max(1, min(days, 365))
    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
    aggs = (
        func.count(LlmUsage.id),
        func.coalesce(func.sum(LlmUsage.input_tokens), 0),
        func.coalesce(func.sum(LlmUsage.output_tokens), 0),
        func.coalesce(func.sum(LlmUsage.cache_read_tokens), 0),
        func.coalesce(func.sum(LlmUsage.cache_creation_tokens), 0),
        func.coalesce(func.sum(LlmUsage.cost_usd), 0.0),
    )

    def shape(row) -> dict[str, Any]:
        calls, inp, out, cr, cc, cost = row
        cached_in = (inp or 0) + (cr or 0)  # total input = non-cached + cache reads
        return {
            "calls": calls or 0,
            "input_tokens": inp or 0, "output_tokens": out or 0,
            "cache_read_tokens": cr or 0, "cache_creation_tokens": cc or 0,
            "cost_usd": round(cost or 0.0, 4),
            "cache_hit_pct": round(100 * (cr or 0) / cached_in, 1) if cached_in else 0.0,
        }

    total = shape(db.execute(select(*aggs).where(LlmUsage.ts >= since)).one())
    names = {u.id: (u.display_name or u.username) for u in db.scalars(select(User)).all()}
    by_user = sorted(
        [{"user_id": r[0], "name": names.get(r[0], f"user {r[0]}"), **shape(r[1:])}
         for r in db.execute(
             select(LlmUsage.user_id, *aggs).where(LlmUsage.ts >= since)
             .group_by(LlmUsage.user_id)).all()],
        key=lambda x: x["cost_usd"], reverse=True)
    by_call_site = sorted(
        [{"call_site": r[0], **shape(r[1:])}
         for r in db.execute(
             select(LlmUsage.call_site, *aggs).where(LlmUsage.ts >= since)
             .group_by(LlmUsage.call_site)).all()],
        key=lambda x: x["cost_usd"], reverse=True)
    return {"days": days, "since": since.isoformat(),
            "total": total, "by_user": by_user, "by_call_site": by_call_site}


@auth_router.post("/invites")
def create_invite(db: Session = Depends(get_db), admin: User = Depends(admin_user)):
    """Mint a one-time invite link (7 days). The admin sends it themselves —
    no email involved; the invitee picks their own username and password."""
    token, row = create_invite_token(db, admin.id, "invite")
    return {"path": f"/invite/{token}", "expires_at": row.expires_at.isoformat()}


@auth_router.post("/users/{user_id}/reset_link")
def create_reset_link(user_id: int, db: Session = Depends(get_db),
                      admin: User = Depends(admin_user)):
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(404, "no such user")
    token, row = create_invite_token(db, admin.id, "password_reset", user_id=target.id)
    return {"path": f"/invite/{token}", "expires_at": row.expires_at.isoformat()}


@auth_router.delete("/users/{user_id}")
def remove_user(user_id: int, db: Session = Depends(get_db),
                admin: User = Depends(admin_user)):
    if user_id == admin.id:
        raise HTTPException(400, "you can't remove yourself")
    if db.get(User, user_id) is None:
        raise HTTPException(404, "no such user")
    delete_user_data(db, user_id)
    return {"ok": True}


class InviteAcceptBody(BaseModel):
    # invite: all fields; password_reset: only password
    username: str | None = Field(default=None, min_length=2, max_length=32,
                                 pattern=r"^[a-z0-9_.-]+$")
    password: str = Field(min_length=6)
    display_name: str = ""


@auth_router.get("/invites/{token}")
def check_invite(token: str, db: Session = Depends(get_db)):
    """Public: lets the invite page render the right form (or an error)."""
    row = get_valid_invite(db, token)
    if row is None:
        return {"valid": False}
    out = {"valid": True, "kind": row.kind}
    if row.kind == "password_reset" and row.user_id:
        target = db.get(User, row.user_id)
        out["username"] = target.username if target else None
    return out


@auth_router.post("/invites/{token}/accept")
def accept_invite(token: str, body: InviteAcceptBody, response: Response,
                  db: Session = Depends(get_db)):
    """Public: consume a one-time link. Creates the account (invite) or sets a
    new password (reset), then logs the user straight in."""
    row = get_valid_invite(db, token)
    if row is None:
        raise HTTPException(410, "this link is no longer valid")

    if row.kind == "invite":
        if not body.username:
            raise HTTPException(422, "username required")
        if db.scalars(select(User).where(User.username == body.username.lower())).first():
            raise HTTPException(409, "username already taken")
        user = User(
            username=body.username.lower(),
            display_name=body.display_name or body.username.capitalize(),
            password_hash=hash_password(body.password),
        )
        db.add(user)
    else:  # password_reset
        user = db.get(User, row.user_id) if row.user_id else None
        if user is None:
            raise HTTPException(410, "this link is no longer valid")
        user.password_hash = hash_password(body.password)
        # A reset invalidates every existing session for the account
        from sqlalchemy import delete as sa_delete

        from .models import AuthSession
        db.execute(sa_delete(AuthSession).where(AuthSession.user_id == user.id))

    row.used_at = dt.datetime.now(dt.timezone.utc)
    db.commit()
    session_token = create_session(db, user)
    response.set_cookie(
        COOKIE_NAME, session_token,
        max_age=SESSION_DAYS * 86400,
        httponly=True, samesite="lax", secure=config.cookie_secure, path="/",
    )
    return {"ok": True, "user": _user_dict(user)}


class PasswordBody(BaseModel):
    current_password: str
    new_password: str = Field(min_length=6)


@auth_router.post("/password")
def change_password(body: PasswordBody, db: Session = Depends(get_db),
                    user: User = Depends(current_user)):
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(401, "current password is incorrect")
    user.password_hash = hash_password(body.new_password)
    db.add(user)
    db.commit()
    return {"ok": True}


# --- serialization helpers ---------------------------------------------------

def _activity_dict(a: Activity) -> dict:
    return {
        "id": a.id,
        "date": a.date.isoformat(),
        "type": a.type,
        "name": a.name,
        "distance_km": round(a.distance_m / 1000, 2) if a.distance_m else None,
        "duration_min": round(a.duration_s / 60, 1) if a.duration_s else None,
        "avg_hr": a.avg_hr,
        "avg_pace": metrics.pace_str(a.avg_speed_mps),
        "training_load": a.training_load,
        "rpe": a.rpe,
        "garmin_rpe": a.garmin_rpe,
        "feel": a.feel,
        "body_battery_change": a.body_battery_change,
        "cadence": a.cadence,
        "temperature_c": a.temperature_c,
        "hr_drift_pct": a.hr_drift_pct,
        "ef": metrics.efficiency_factor(a),
        # Execution score: receipts shown wherever a run appears (score + per-
        # segment breakdown). `analysis` is the LLM narrative — null until the
        # Today page lazily generates it for a recent scored run.
        "execution_score": a.execution_score,
        "execution_score_source": a.execution_score_source,
        "execution_breakdown": a.execution_breakdown,
        "execution_analysis": a.execution_analysis,
        "execution_analysis_coach": a.execution_analysis_coach,  # persona that wrote it
        "gear_uuid": a.gear_uuid,
    }


def _health_dict(h: DailyHealth) -> dict:
    return {
        "date": h.date.isoformat(),
        "sleep_hours": round(h.sleep_seconds / 3600, 1) if h.sleep_seconds else None,
        "sleep_score": h.sleep_score,
        "hrv": h.hrv,
        "hrv_baseline": h.hrv_baseline,
        "resting_hr": h.resting_hr,
        "body_battery": h.body_battery,
        "stress_avg": h.stress_avg,
    }


def _pending_edit(db: Session, user_id: int) -> PendingEdit | None:
    return db.scalars(
        select(PendingEdit).where(PendingEdit.user_id == user_id,
                                  PendingEdit.status == "pending")
        .order_by(PendingEdit.created_at.desc()).limit(1)
    ).first()


def _own_activity(db: Session, user_id: int, activity_id: int) -> Activity:
    a = db.get(Activity, activity_id)
    if a is None or a.user_id != user_id:
        raise HTTPException(404, "activity not found")
    return a


def _own_race(db: Session, user_id: int, race_id: int) -> Race:
    r = db.get(Race, race_id)
    if r is None or r.user_id != user_id:
        raise HTTPException(404, "race not found")
    return r


# --- dashboard ---------------------------------------------------------------

def _today_cycle(db: Session, user_id: int, cycle: dict | None, today: dt.date) -> dict | None:
    """Today's phase plus the drift-prompt flag (confirmed/snooze state applied)."""
    phase = metrics.cycle_phase(cycle, today)
    if phase is None:
        return None
    confirmed = settings_store.get_internal(db, user_id, settings_store.CYCLE_CONFIRMED_KEY)
    snooze = settings_store.get_internal(db, user_id, settings_store.CYCLE_SNOOZE_KEY)
    phase["show_started_prompt"] = metrics.show_started_prompt(phase, confirmed, snooze, today)
    return phase


@router.get("/dashboard/today")
def dashboard_today(db: Session = Depends(get_db), user: User = Depends(current_user)):
    today = dt.date.today()
    primary = races_mod.primary_race(db, user.id)
    race = None
    days_to_race = None
    if primary is not None:
        race = races_mod.race_dict(primary, races_mod.prediction_context(db, user.id, today))
        days_to_race = race["days_to_race"]

    workout = db.get(PlanDay, (user.id, today))
    health = (db.get(DailyHealth, (user.id, today))
              or db.get(DailyHealth, (user.id, today - dt.timedelta(days=1))))
    edit = _pending_edit(db, user.id)
    # Only ever ask about the single most recent run — if it's rated (or too old),
    # ask nothing. A Garmin-logged RPE counts as rated: don't ask again in-app.
    # Older unrated runs stay ratable from their detail pages.
    latest_run = db.scalars(
        select(Activity)
        .where(Activity.user_id == user.id,
               Activity.date >= today - dt.timedelta(days=2), Activity.type.like("%run%"))
        .order_by(Activity.date.desc(), Activity.id.desc()).limit(1)
    ).first()
    rated = latest_run is not None and (latest_run.rpe is not None or latest_run.garmin_rpe is not None)
    unrated = None if rated else latest_run
    # Ambiguous-run prompt: a run auto-attribution didn't catch, on a day with a
    # planned workout. Folded into the same Today moment as the RPE ask.
    attribution = None
    if latest_run is not None:
        label = execution.prompt_label(db, latest_run)
        if label:
            attribution = {"activity_id": latest_run.id, "workout_label": label}

    # Today's completed run, once scored (attributed to the plan): the plan card
    # gives way to this result card. Its analysis may still be null → the client
    # fires the one lazy LLM call on load.
    todays_scored = db.scalars(
        select(Activity).where(Activity.user_id == user.id, Activity.date == today,
                               Activity.type.like("%run%"),
                               Activity.execution_score.is_not(None))
        .order_by(Activity.id.desc()).limit(1)
    ).first()
    completed = None
    if todays_scored:
        completed = {**_activity_dict(todays_scored),
                     "analysis_feedback": feedback_mod.feedback_state(
                         db, user.id, "execution_analysis", todays_scored.id)}

    mode = plan_mode(db, user.id, today)
    cycle = get_settings(db, user.id).get("cycle")
    workout_dict = None
    if workout:
        revertible = (mode == "editor" and workout.status == "planned"
                      and planner_mod._is_override(db, workout))
        workout_dict = {**plan_day_dict(workout), "revertible": revertible,
                        "cycle": metrics.cycle_phase(cycle, today)}

    return {
        "date": today.isoformat(),
        "mode": mode,
        "readiness": metrics.readiness(db, user.id, today),
        "cycle": _today_cycle(db, user.id, cycle, today),
        "workout": workout_dict,
        "health": _health_dict(health) if health else None,
        "pending_edit": edit_dict(edit) if edit else None,
        "race": race,
        "days_to_race": days_to_race,
        "unrated_activity": _activity_dict(unrated) if unrated else None,
        "attribution_prompt": attribution,
        "completed_workout": completed,
        "niggles": niggles_mod.active_niggles(db, user.id, today),
    }


def _review_dict(r: DailyReview | None, db: Session | None = None,
                 user_id: int | None = None) -> dict | None:
    if r is None:
        return None
    out = {
        "date": r.date.isoformat(),
        "state": r.state,
        "mode": r.mode,
        "coach_note": r.coach_note,
        "coach": r.coach,  # persona that wrote the note (null on pre-feature rows)
        "proposal_id": r.proposal_id,
    }
    if db is not None and user_id is not None:
        out["my_feedback"] = feedback_mod.feedback_state(
            db, user_id, "coach_note", r.date.isoformat())
    return out


class EvaluateBody(BaseModel):
    allow_structural: bool = False


@router.get("/dashboard/review")
def dashboard_review(db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Cheap, no-LLM: today's review state + whether last night's data has landed.

    The Today page polls this after painting the base plan; when `data_ready`
    flips true it POSTs /dashboard/evaluate to run the one daily LLM review.

    Self-healing: when today's recovery data hasn't landed, kick a background
    sync (deduped) so the review never waits on a mistimed cron or a laptop that
    slept through it. `data_ready` requires real recovery content, not just a
    bare row, so an early sync (before Garmin processed the night) keeps polling.

    `data_overdue`: data still absent well past plan_hour (household zone) reads
    as a no-sleep-recorded morning, not a slow sync — the Today page swaps
    "syncing…" for the calm "no sleep data yet" state and promotes the
    structural "Review anyway" option."""
    today = dt.date.today()
    data_ready = metrics.has_recovery_data(db.get(DailyHealth, (user.id, today)))
    syncing = False
    if not data_ready and has_garmin(user):
        syncing = scheduler.ensure_fresh_today(user.id)
    data_overdue = (not data_ready
                    and scheduler.now_local().hour >= int(config.plan_hour) + 2)
    return {
        "review": _review_dict(db.get(DailyReview, (user.id, today)), db, user.id),
        "data_ready": data_ready,
        "syncing": syncing,
        "data_overdue": data_overdue,
    }


@router.post("/dashboard/evaluate")
def dashboard_evaluate(body: EvaluateBody, db: Session = Depends(get_db),
                       user: User = Depends(current_user)):
    """Lazy first-login trigger for the daily review. Idempotent per day: a
    review already completed today is returned WITHOUT another LLM call.

    With no data yet and `allow_structural=false`, `evaluate_today` records
    `pending_data` and spends nothing; the degraded "Review anyway" button sends
    `allow_structural=true` to run a structural-only review."""
    today = dt.date.today()
    review = db.get(DailyReview, (user.id, today))
    if review is not None and review.state in ("done_full", "done_structural"):
        return _review_dict(review, db, user.id)
    review = evaluate_today(db, user.id, today, allow_structural_fallback=body.allow_structural)
    return _review_dict(review, db, user.id)


class RevertBody(BaseModel):
    scope: str = Field(pattern="^(day|week)$")
    date: str | None = None   # required for scope="day"
    start: str | None = None  # week start for scope="week"; defaults to today


@router.post("/dashboard/revert-to-garmin")
def revert_to_garmin_endpoint(body: RevertBody, db: Session = Depends(get_db),
                              user: User = Depends(current_user)):
    """Replace Idaten's edit(s) with the original Garmin Coach workout.

    scope="day" reverts one day; scope="week" reverts every Idaten-edited day in
    the 7-day window. Only meaningful in editor mode (a Garmin plan is the base).
    Clears Idaten's pushed watch workout; the native Garmin workout stands."""
    today = dt.date.today()
    if plan_mode(db, user.id, today) != "editor":
        raise HTTPException(400, "revert is only available while following a Garmin Coach plan")

    if body.scope == "day":
        if not body.date:
            raise HTTPException(422, "date is required for scope=day")
        dates = [dt.date.fromisoformat(body.date)]
    else:
        start = dt.date.fromisoformat(body.start) if body.start else today
        dates = planner_mod.edited_days_in_window(
            db, user.id, start, start + dt.timedelta(days=6))

    reverted = planner_mod.revert_to_garmin(db, user.id, dates, today)
    return {"reverted": [d.isoformat() for d in reverted]}


# --- plan --------------------------------------------------------------------

def _week_days(db: Session, user_id: int, start: str | None) -> list[PlanDay]:
    start_date = dt.date.fromisoformat(start) if start else dt.date.today()
    return db.scalars(
        select(PlanDay)
        .where(PlanDay.user_id == user_id,
               PlanDay.date >= start_date, PlanDay.date < start_date + dt.timedelta(days=7))
        .order_by(PlanDay.date)
    ).all()


@router.get("/plan/week")
def plan_week(start: str | None = None, db: Session = Depends(get_db),
              user: User = Depends(current_user)):
    days = _week_days(db, user.id, start)
    start_date = dt.date.fromisoformat(start) if start else dt.date.today()
    today = dt.date.today()
    mode = plan_mode(db, user.id, today)
    # In editor mode, a day carrying an Idaten/hand override can be reverted to
    # the mirrored Garmin coach workout; author mode has no Garmin base.
    revertible = set()
    if mode == "editor" and days:
        revertible = set(planner_mod.edited_days_in_window(
            db, user.id, days[0].date, days[-1].date))
    cycle = get_settings(db, user.id).get("cycle")
    # Matched run per day (its execution score), so a completed day shows the score.
    scored: dict[dt.date, Activity] = {}
    if days:
        for a in db.scalars(select(Activity).where(
                Activity.user_id == user.id, Activity.date >= days[0].date,
                Activity.date <= days[-1].date, Activity.type.like("%run%"),
                Activity.execution_score.is_not(None)).order_by(Activity.id)).all():
            scored[a.date] = a  # last scored run of the day wins
    # Week volume summary, framed in the plan's own currency (time at intensity;
    # these plans are time-based, so planned km often doesn't exist). Distance is
    # a secondary actuals-only fact from completed activities.
    week_acts = db.scalars(select(Activity).where(
        Activity.user_id == user.id, Activity.date >= start_date,
        Activity.date < start_date + dt.timedelta(days=7))).all()
    planned_min = sum(
        d.duration_min for d in days
        if d.workout_type != "rest" and d.duration_min is not None)
    done_min = sum(a.duration_s / 60 for a in week_acts if a.duration_s)
    run_km = sum(
        a.distance_m / 1000 for a in week_acts
        if a.distance_m and "run" in (a.type or ""))
    zone_s = {"easy": 0.0, "total": 0.0}
    for a in week_acts:
        z = a.time_in_zones or {}
        total = sum(z.values())
        if total:
            zone_s["easy"] += z.get("z1", 0) + z.get("z2", 0)
            zone_s["total"] += total
    return {
        "mode": mode,
        "summary": {
            "planned_min": round(planned_min) if planned_min else None,
            "done_min": round(done_min) if done_min else 0,
            "run_km": round(run_km, 1) if run_km else None,
            "easy_pct": (round(100 * zone_s["easy"] / zone_s["total"])
                         if zone_s["total"] else None),
        },
        "days": [
            {**plan_day_dict(d), "revertible": d.date in revertible,
             "cycle": metrics.cycle_phase(cycle, d.date),
             "execution": (
                 {"score": scored[d.date].execution_score,
                  "source": scored[d.date].execution_score_source,
                  "activity_id": scored[d.date].id}
                 if d.date in scored else None)}
            for d in days
        ],
    }


@router.get("/plan/day")
def plan_day(date: str, db: Session = Depends(get_db),
             user: User = Depends(current_user)):
    """Single plan day for the preview/detail page (`/plan/[date]`). Same
    `PlanDay` shape as `/plan/week` days[], plus this date's mode + intent.
    `day` is null when nothing is materialized for the date."""
    try:
        d = dt.date.fromisoformat(date)
    except ValueError:
        raise HTTPException(422, "date must be YYYY-MM-DD")
    day = db.get(PlanDay, (user.id, d))
    mode = plan_mode(db, user.id, dt.date.today())
    revertible = (
        mode == "editor" and day is not None and day.status == "planned"
        and planner_mod._is_override(db, day)
    )
    cycle = get_settings(db, user.id).get("cycle")
    intent = db.get(DayIntent, (user.id, d))
    return {
        "mode": mode,
        "day": (
            {**plan_day_dict(day), "revertible": revertible,
             "cycle": metrics.cycle_phase(cycle, day.date)}
            if day is not None else None
        ),
        "intent": intent_dict(intent) if intent is not None else None,
        # The athlete's HR zones — locates an HR-targeted run on the Z1–Z5 scale
        # in the preview (the "what type of run" signal for a whole-run target).
        "hr_zones": settings_store.hr_zones(db, user.id),
    }


class PushBody(BaseModel):
    date: str


@router.post("/plan/push")
def plan_push(body: PushBody, db: Session = Depends(get_db),
              user: User = Depends(current_user)):
    day = db.get(PlanDay, (user.id, dt.date.fromisoformat(body.date)))
    if day is None:
        raise HTTPException(404, "no plan for that date")
    try:
        workout_id = push_day(db, day)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Garmin push failed: {e}")
    if workout_id is None:
        raise HTTPException(400, f"'{day.workout_type}' days are not pushable")
    return {"ok": True, "garmin_workout_id": workout_id}


class WeekBody(BaseModel):
    start: str | None = None


@router.post("/plan/push_week")
def plan_push_week(body: WeekBody, db: Session = Depends(get_db),
                   user: User = Depends(current_user)):
    pushed = 0
    errors: list[str] = []
    for day in _week_days(db, user.id, body.start):
        if day.workout_type not in PUSHABLE_TYPES or day.pushed_at is not None:
            continue  # skip rest/cross-train and already-current pushes
        try:
            if push_day(db, day):
                pushed += 1
        except Exception as e:  # noqa: BLE001
            errors.append(f"{day.date}: {e}")
    if errors and pushed == 0:
        raise HTTPException(502, "; ".join(errors))
    return {"ok": True, "pushed": pushed, "errors": errors}


@router.post("/plan/unpush")
def plan_unpush(body: PushBody, db: Session = Depends(get_db),
                user: User = Depends(current_user)):
    day = db.get(PlanDay, (user.id, dt.date.fromisoformat(body.date)))
    if day is None:
        raise HTTPException(404, "no plan for that date")
    unpush_day(db, day)
    return {"ok": True}


@router.post("/plan/unpush_week")
def plan_unpush_week(body: WeekBody, db: Session = Depends(get_db),
                     user: User = Depends(current_user)):
    removed = sum(1 for day in _week_days(db, user.id, body.start) if unpush_day(db, day))
    return {"ok": True, "removed": removed}


# --- races ---------------------------------------------------------------------

class RaceBody(BaseModel):
    name: str
    date: str
    distance_km: float = Field(gt=0)
    goal_time: str = ""
    is_primary: bool = False


class RaceUpdateBody(BaseModel):
    name: str | None = None
    date: str | None = None
    distance_km: float | None = Field(default=None, gt=0)
    goal_time: str | None = None


@router.get("/races")
def list_races(include_past: bool = False, db: Session = Depends(get_db),
               user: User = Depends(current_user)):
    ctx = races_mod.prediction_context(db, user.id)
    return [races_mod.race_dict(r, ctx)
            for r in races_mod.upcoming_races(db, user.id, include_past)]


@router.post("/races")
def create_race(body: RaceBody, db: Session = Depends(get_db),
                user: User = Depends(current_user)):
    race = Race(
        user_id=user.id,
        name=body.name,
        date=dt.date.fromisoformat(body.date),
        distance_km=body.distance_km,
        goal_time=body.goal_time,
    )
    db.add(race)
    db.commit()
    if body.is_primary or races_mod.primary_race(db, user.id) is None:
        races_mod.set_primary(db, race)
    if body.is_primary:  # an explicit choice — Garmin import must not override it
        settings_store.put_internal(
            db, user.id, settings_store.RACE_PRIMARY_OVERRIDE_KEY, True)
    return races_mod.race_dict(race, races_mod.prediction_context(db, user.id))


@router.put("/races/{race_id}")
def update_race(race_id: int, body: RaceUpdateBody, db: Session = Depends(get_db),
                user: User = Depends(current_user)):
    race = _own_race(db, user.id, race_id)
    if body.name is not None:
        race.name = body.name
    if body.date is not None:
        race.date = dt.date.fromisoformat(body.date)
    if body.distance_km is not None:
        race.distance_km = body.distance_km
    if body.goal_time is not None:
        race.goal_time = body.goal_time
    db.commit()
    return races_mod.race_dict(race, races_mod.prediction_context(db, user.id))


@router.delete("/races/{race_id}")
def delete_race(race_id: int, db: Session = Depends(get_db),
                user: User = Depends(current_user)):
    race = db.get(Race, race_id)
    if race is not None and race.user_id == user.id:
        if race.garmin_uuid:  # tombstone so the daily import doesn't resurrect it
            deleted = settings_store.get_internal(
                db, user.id, settings_store.DELETED_GARMIN_RACES_KEY, []) or []
            if race.garmin_uuid not in deleted:
                settings_store.put_internal(
                    db, user.id, settings_store.DELETED_GARMIN_RACES_KEY,
                    deleted + [race.garmin_uuid])
        db.delete(race)
        db.commit()
        races_mod.ensure_primary(db, user.id)
    return {"ok": True}


@router.post("/races/{race_id}/primary")
def make_primary(race_id: int, db: Session = Depends(get_db),
                 user: User = Depends(current_user)):
    race = _own_race(db, user.id, race_id)
    races_mod.set_primary(db, race)
    settings_store.put_internal(
        db, user.id, settings_store.RACE_PRIMARY_OVERRIDE_KEY, True)
    return {"ok": True}


class CoursePreviewBody(BaseModel):
    url: str | None = None          # shared Google My Maps link
    content_b64: str | None = None  # or an uploaded .kml/.kmz/.gpx, base64


class CourseBody(BaseModel):
    # [[lat, lon], ...]; bounds checked below (pydantic tuple items would
    # accept any 2-list but not range-check).
    course: list[tuple[float, float]] = Field(min_length=2, max_length=2000)


@router.post("/races/course/preview")
def course_preview(body: CoursePreviewBody, user: User = Depends(current_user)):
    """Parse a course source into candidate tracks for the picker (stateless —
    the chosen track is saved via PUT /races/{id}/course)."""
    import base64

    from . import course as course_mod

    try:
        if body.url:
            data = course_mod.fetch_mymaps(body.url)
        elif body.content_b64:
            if len(body.content_b64) > 14_000_000:  # ~10 MB decoded
                raise HTTPException(413, "File too large (10 MB max)")
            try:
                data = base64.b64decode(body.content_b64, validate=True)
            except Exception:  # noqa: BLE001
                raise course_mod.CourseError("File upload wasn't valid base64")
        else:
            raise course_mod.CourseError("Provide a link or a file")
        tracks = course_mod.parse_course(data)
    except course_mod.CourseError as e:
        raise HTTPException(400, str(e))
    if not tracks:
        raise HTTPException(400, "No course line found — the map has markers but no drawn route")
    return {"tracks": tracks}


@router.put("/races/{race_id}/course")
def set_race_course(race_id: int, body: CourseBody, db: Session = Depends(get_db),
                    user: User = Depends(current_user)):
    if not all(-90 <= lat <= 90 and -180 <= lon <= 180 for lat, lon in body.course):
        raise HTTPException(400, "Course has out-of-range coordinates")
    race = _own_race(db, user.id, race_id)
    race.course = [[lat, lon] for lat, lon in body.course]
    db.commit()
    return races_mod.race_dict(race, races_mod.prediction_context(db, user.id))


@router.delete("/races/{race_id}/course")
def clear_race_course(race_id: int, db: Session = Depends(get_db),
                      user: User = Depends(current_user)):
    race = _own_race(db, user.id, race_id)
    race.course = None
    db.commit()
    return races_mod.race_dict(race, races_mod.prediction_context(db, user.id))


# --- training plan (phases / progress) ------------------------------------------

@router.get("/training-plan")
def training_plan(db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Phase timeline + current week. Garmin Coach plan when one is mirrored
    (its numbering is ground truth); otherwise derived from the primary race;
    null when there is neither."""
    from .garmin.training_plan import derived_payload, plan_payload

    today = dt.date.today()
    row = db.get(TrainingPlan, user.id)
    if row is not None and row.end_date >= today:
        return plan_payload(row, today)
    primary = races_mod.primary_race(db, user.id)
    if primary is not None:
        return derived_payload(primary.name, primary.date, today)
    return None


# --- day intents ---------------------------------------------------------------

class IntentBody(BaseModel):
    sport: str
    note: str = ""
    duration_min: float | None = None
    effort: str | None = None


@router.get("/intents")
def list_intents(start: str, end: str, db: Session = Depends(get_db),
                 user: User = Depends(current_user)):
    rows = db.scalars(
        select(DayIntent)
        .where(DayIntent.user_id == user.id,
               DayIntent.date >= dt.date.fromisoformat(start),
               DayIntent.date <= dt.date.fromisoformat(end))
        .order_by(DayIntent.date)
    ).all()
    return [intent_dict(i) for i in rows]


@router.put("/intents/{date}")
def put_intent(date: str, body: IntentBody, db: Session = Depends(get_db),
               user: User = Depends(current_user)):
    d = dt.date.fromisoformat(date)
    intent = db.get(DayIntent, (user.id, d)) or DayIntent(user_id=user.id, date=d)
    intent.sport = body.sport
    intent.note = body.note
    intent.duration_min = body.duration_min
    intent.effort = body.effort
    intent.source = "manual"
    db.merge(intent)
    db.commit()
    return intent_dict(intent)


@router.delete("/intents/{date}")
def delete_intent(date: str, db: Session = Depends(get_db),
                  user: User = Depends(current_user)):
    intent = db.get(DayIntent, (user.id, dt.date.fromisoformat(date)))
    if intent is not None:
        db.delete(intent)
        db.commit()
    return {"ok": True}


# --- trends / activities -----------------------------------------------------

@router.get("/trends")
def trends(days: int = 90, db: Session = Depends(get_db),
           user: User = Depends(current_user)):
    end = dt.date.today()
    start = end - dt.timedelta(days=min(days, 365))
    series = {m.date: m for m in metrics.load_series(db, user.id, start, end)}
    health = {h.date: h for h in db.scalars(
        select(DailyHealth).where(DailyHealth.user_id == user.id, DailyHealth.date >= start))}
    acts = db.scalars(select(Activity).where(Activity.user_id == user.id,
                                             Activity.date >= start)).all()
    dist: dict[dt.date, float] = {}
    for a in acts:
        dist[a.date] = dist.get(a.date, 0.0) + (a.distance_m or 0) / 1000

    daily = []
    d = start
    while d <= end:
        h = health.get(d)
        m = series.get(d)
        acwr = round(m.atl / m.ctl, 2) if m and m.ctl > 1 else None
        daily.append({
            "date": d.isoformat(),
            "acwr": acwr,
            "vo2max": h.vo2max if h else None,
            "hrv": h.hrv if h else None,
            "hrv_baseline": h.hrv_baseline if h else None,
            "resting_hr": h.resting_hr if h else None,
            "sleep_hours": round(h.sleep_seconds / 3600, 1) if h and h.sleep_seconds else None,
            "sleep_score": h.sleep_score if h else None,
            "body_battery": h.body_battery if h else None,
            "ctl": round(m.ctl, 1) if m else None,
            "atl": round(m.atl, 1) if m else None,
            "tsb": round(m.tsb, 1) if m else None,
            "distance_km": round(dist.get(d, 0.0), 2),
            "training_load": round(m.load, 1) if m else None,
        })
        d += dt.timedelta(days=1)
    return {"daily": daily}


@router.get("/activities")
def activities(limit: int = 20, offset: int = 0, type: str | None = None,
               days: int | None = None, month: str | None = None,
               db: Session = Depends(get_db), user: User = Depends(current_user)):
    q = select(Activity).where(Activity.user_id == user.id)
    if type:
        q = q.where(Activity.type == type)
    if days:
        q = q.where(Activity.date >= dt.date.today() - dt.timedelta(days=days))
    if month:  # "YYYY-MM" — the list page's month navigator
        try:
            first = dt.date.fromisoformat(f"{month}-01")
        except ValueError:
            raise HTTPException(422, "month must be YYYY-MM")
        nxt = (first.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
        q = q.where(Activity.date >= first, Activity.date < nxt)
    rows = db.scalars(
        q.order_by(Activity.date.desc(), Activity.id.desc())
        .offset(offset).limit(min(limit, 100))
    ).all()
    return [_activity_dict(a) for a in rows]


@router.get("/activities/types")
def activity_types(db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Distinct activity types with counts, for the list page's filter chips."""
    from sqlalchemy import func

    rows = db.execute(
        select(Activity.type, func.count())
        .where(Activity.user_id == user.id)
        .group_by(Activity.type).order_by(func.count().desc())
    ).all()
    return [{"type": t, "count": c} for t, c in rows]


@router.get("/activities/months")
def activity_months(db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Months that have activities, newest first, with counts — powers the list
    page's month navigator/picker. (Must route before /activities/{id}.)"""
    from sqlalchemy import func

    ym = func.strftime("%Y-%m", Activity.date)
    rows = db.execute(
        select(ym, func.count())
        .where(Activity.user_id == user.id)
        .group_by(ym).order_by(ym.desc())
    ).all()
    return [{"month": m, "count": c} for m, c in rows]


@router.get("/activities/{activity_id}")
def activity_detail(activity_id: int, db: Session = Depends(get_db),
                    user: User = Depends(current_user)):
    a = _own_activity(db, user.id, activity_id)
    raw = a.raw or {}
    plan = db.get(PlanDay, (user.id, a.date))
    return {
        **_activity_dict(a),
        "rpe_note": a.rpe_note,
        "time_in_zones": a.time_in_zones,
        "max_hr": raw.get("maxHR"),
        "calories": raw.get("calories"),
        "elevation_gain_m": raw.get("elevationGain"),
        "start_time_local": raw.get("startTimeLocal"),
        "plan_day": plan_day_dict(plan) if plan else None,
        "analysis_feedback": feedback_mod.feedback_state(
            db, user.id, "execution_analysis", a.id),
    }


@router.get("/activities/{activity_id}/series")
def activity_series(activity_id: int, db: Session = Depends(get_db),
                    user: User = Depends(current_user)):
    """Chart data for the detail page: downsampled series + per-lap splits.

    Cached on the activity row; older activities (pre-cache) are fetched from
    Garmin on first view. Nulls mean the data genuinely isn't available."""
    from .garmin.series import fetch_and_cache

    a = _own_activity(db, user.id, activity_id)
    # route only warrants a Garmin trip when the activity actually has a GPS fix
    if a.series is None or a.splits is None or (a.route is None and a.start_lat is not None):
        try:
            fetch_and_cache(db, get_garmin(user), a)
        except Exception as e:  # noqa: BLE001
            db.rollback()
            if a.series is None and a.splits is None:
                raise HTTPException(502, f"Garmin fetch failed: {e}")
    for s in a.splits or []:
        s["avg_pace"] = metrics.pace_str(s.get("avg_speed_mps"))
    return {
        "series": a.series,
        "splits": a.splits,
        "route": a.route,
        "hr_zones": settings_store.hr_zones(db, user.id),
    }


class RpeBody(BaseModel):
    rating: int = Field(ge=1, le=10)
    note: str | None = None


@router.post("/activities/{activity_id}/rpe")
def rate_activity(activity_id: int, body: RpeBody, db: Session = Depends(get_db),
                  user: User = Depends(current_user)):
    a = _own_activity(db, user.id, activity_id)
    a.rpe = body.rating
    a.rpe_note = body.note
    db.commit()
    return {"ok": True}


class AttributionBody(BaseModel):
    attempted: bool  # True = this run WAS the planned workout; False = just a run


@router.post("/activities/{activity_id}/attribution")
def attribute_activity(activity_id: int, body: AttributionBody,
                       db: Session = Depends(get_db),
                       user: User = Depends(current_user)):
    """Resolve an ambiguous run: was it an attempt at the day's planned workout?
    A Yes attributes + scores it; a No marks it a plain run (never re-asked)."""
    a = _own_activity(db, user.id, activity_id)
    a.execution_attributed = body.attempted
    if body.attempted:
        score, breakdown = execution.score_confirmed(
            db, a, settings_store.hr_zones(db, user.id))
        a.execution_score = score
        a.execution_score_source = "idaten" if score is not None else None
        a.execution_breakdown = breakdown
        if score is not None:
            execution.mark_day_completed(db, a.user_id, a.date)
    else:
        a.execution_score = None
        a.execution_score_source = None
        a.execution_breakdown = None
    db.commit()
    return {"ok": True, "execution_score": a.execution_score}


# The LLM analysis is generated lazily and ONLY for a recent run — never for old
# history (a hard guard, not just a caller convention) and never at sync.
ANALYSIS_MAX_AGE_DAYS = 2


@router.post("/activities/{activity_id}/analysis")
def activity_analysis(activity_id: int, db: Session = Depends(get_db),
                      user: User = Depends(current_user)):
    """Generate (once) and return the execution-analysis narrative for a recent
    scored run. Idempotent: a cached analysis is returned without an LLM call."""
    a = _own_activity(db, user.id, activity_id)
    if a.execution_score is None:
        raise HTTPException(400, "activity has no execution score")
    if a.execution_analysis is None:
        if a.date < dt.date.today() - dt.timedelta(days=ANALYSIS_MAX_AGE_DAYS):
            raise HTTPException(400, "analysis is only generated for recent runs")
        a.execution_analysis, a.execution_analysis_coach = (
            planner_mod.write_execution_analysis(db, a))
        db.commit()
    return {"analysis": a.execution_analysis,
            "coach": a.execution_analysis_coach}


# --- gear --------------------------------------------------------------------

GEAR_IMAGE_TYPES = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
GEAR_IMAGE_MAX_BYTES = 5 * 1024 * 1024


def _own_gear(db: Session, user_id: int, gear_uuid: str) -> Gear:
    g = db.get(Gear, gear_uuid)
    if g is None or g.user_id != user_id:
        raise HTTPException(404, "gear not found")
    return g


def _gear_image_path(user_id: int, gear_uuid: str, ext: str) -> str:
    return os.path.join(config.gear_image_dir, str(user_id), f"{gear_uuid}.{ext}")


def _gear_dict(g: Gear) -> dict:
    return {
        "uuid": g.uuid,
        "name": g.name,
        "make": g.make,
        "model": g.model,
        "gear_type": g.gear_type,
        "status": g.status,
        "date_begin": g.date_begin.isoformat() if g.date_begin else None,
        "distance_km": round(g.total_distance_m / 1000, 1) if g.total_distance_m else 0,
        "limit_km": round(g.maximum_meters / 1000) if g.maximum_meters else None,
        "total_activities": g.total_activities or 0,
        "has_image": g.image_ext is not None,
    }


@router.get("/gear")
def gear_list(db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows = db.scalars(
        select(Gear).where(Gear.user_id == user.id)
        .order_by(Gear.status, Gear.date_begin.desc())
    ).all()
    return [_gear_dict(g) for g in rows]


@router.post("/gear/refresh")
def gear_refresh(db: Session = Depends(get_db), user: User = Depends(current_user)):
    """On-demand mirror refresh (first visit / pull-to-refresh); the daily sync
    keeps it fresh otherwise."""
    from .garmin.gear import sync_gear

    try:
        sync_gear(db, user.id, get_garmin(user))
    except Exception as e:  # noqa: BLE001
        db.rollback()
        raise HTTPException(502, f"Garmin gear sync failed: {e}")
    return gear_list(db, user)


@router.get("/gear/suggestions")
def gear_suggestion_list(db: Session = Depends(get_db),
                         user: User = Depends(current_user)):
    from .garmin.gear import gear_suggestions

    return gear_suggestions(db, user.id)


class GearBody(BaseModel):
    gear_uuid: str | None  # null = remove the shoe from the activity


@router.put("/activities/{activity_id}/gear")
def set_gear(activity_id: int, body: GearBody, db: Session = Depends(get_db),
             user: User = Depends(current_user)):
    """Swap the shoe on an activity — writes through to Garmin, then mirrors."""
    from .garmin.gear import set_activity_gear

    a = _own_activity(db, user.id, activity_id)
    if body.gear_uuid is not None:
        g = _own_gear(db, user.id, body.gear_uuid)
        if g.gear_type != "Shoes":
            raise HTTPException(422, "only shoes can be assigned to a run")
    try:
        set_activity_gear(db, get_garmin(user), a, body.gear_uuid)
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        db.rollback()
        raise HTTPException(502, f"Garmin gear update failed: {e}")
    return {"ok": True, "gear_uuid": a.gear_uuid}


@router.post("/activities/{activity_id}/gear/dismiss")
def dismiss_gear_suggestion(activity_id: int, db: Session = Depends(get_db),
                            user: User = Depends(current_user)):
    a = _own_activity(db, user.id, activity_id)
    a.gear_suggestion_dismissed = True
    db.commit()
    return {"ok": True}


@router.post("/gear/{gear_uuid}/image")
async def upload_gear_image(gear_uuid: str, file: UploadFile = File(...),
                            db: Session = Depends(get_db),
                            user: User = Depends(current_user)):
    """Instance-local shoe photo; replaces any existing one."""
    g = _own_gear(db, user.id, gear_uuid)
    ext = GEAR_IMAGE_TYPES.get(file.content_type or "")
    if ext is None:
        raise HTTPException(422, "image must be JPEG, PNG or WebP")
    data = await file.read()
    if len(data) > GEAR_IMAGE_MAX_BYTES:
        raise HTTPException(422, "image too large (max 5 MB)")

    path = _gear_image_path(user.id, gear_uuid, ext)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if g.image_ext and g.image_ext != ext:
        old = _gear_image_path(user.id, gear_uuid, g.image_ext)
        if os.path.exists(old):
            os.remove(old)
    with open(path, "wb") as f:
        f.write(data)
    g.image_ext = ext
    db.commit()
    return _gear_dict(g)


@router.get("/gear/{gear_uuid}/image")
def gear_image(gear_uuid: str, db: Session = Depends(get_db),
               user: User = Depends(current_user)):
    g = _own_gear(db, user.id, gear_uuid)
    if not g.image_ext:
        raise HTTPException(404, "no image uploaded")
    path = _gear_image_path(user.id, gear_uuid, g.image_ext)
    if not os.path.exists(path):
        raise HTTPException(404, "no image uploaded")
    media = {v: k for k, v in GEAR_IMAGE_TYPES.items()}[g.image_ext]
    return FileResponse(path, media_type=media)


@router.delete("/gear/{gear_uuid}/image")
def delete_gear_image(gear_uuid: str, db: Session = Depends(get_db),
                      user: User = Depends(current_user)):
    g = _own_gear(db, user.id, gear_uuid)
    if g.image_ext:
        path = _gear_image_path(user.id, gear_uuid, g.image_ext)
        if os.path.exists(path):
            os.remove(path)
        g.image_ext = None
        db.commit()
    return _gear_dict(g)


# --- analytics -----------------------------------------------------------------

AEROBIC_HR_FALLBACK = 152  # used when zone data is missing


def _is_aerobic_run(a: Activity) -> bool:
    """Easy/recovery/long-style run: little time above zone 3."""
    if a.type not in ("running", "trail_running", "track_running", "treadmill_running"):
        return False
    z = a.time_in_zones or {}
    total = sum(z.values()) if z else 0
    if total > 0:
        hard = (z.get("z4", 0) + z.get("z5", 0)) / total
        return hard < 0.10
    return bool(a.avg_hr and a.avg_hr <= AEROBIC_HR_FALLBACK)


@router.get("/analytics")
def analytics(days: int = 180, db: Session = Depends(get_db),
              user: User = Depends(current_user)):
    end = dt.date.today()
    start = end - dt.timedelta(days=min(days, 400))
    acts = db.scalars(
        select(Activity).where(Activity.user_id == user.id,
                               Activity.date >= start).order_by(Activity.date)
    ).all()

    ef_series = [
        {
            "date": a.date.isoformat(),
            "activity_id": a.id,
            "name": a.name,
            "ef": metrics.efficiency_factor(a),
            "avg_pace": metrics.pace_str(a.avg_speed_mps),
            "avg_hr": a.avg_hr,
            "temperature_c": a.temperature_c,
            "hr_drift_pct": a.hr_drift_pct,
            "cadence": a.cadence,
            "distance_km": round(a.distance_m / 1000, 2) if a.distance_m else None,
        }
        for a in acts
        if _is_aerobic_run(a) and metrics.efficiency_factor(a) is not None
    ]

    weekly: dict[dt.date, dict[str, float]] = {}
    for a in acts:
        if not a.time_in_zones:
            continue
        week_start = a.date - dt.timedelta(days=a.date.weekday())
        bucket = weekly.setdefault(week_start, {f"z{i}": 0.0 for i in range(1, 6)})
        for k in bucket:
            bucket[k] += (a.time_in_zones or {}).get(k, 0)
    zones_weekly = [
        {"week_start": w.isoformat(), **{f"{k}_s": round(v) for k, v in z.items()}}
        for w, z in sorted(weekly.items())
    ]

    # Per-day zone buckets — used by the short (7-day) Trends view, where weekly
    # rollups collapse to one or two fat bars.
    daily_z: dict[dt.date, dict[str, float]] = {}
    for a in acts:
        if not a.time_in_zones:
            continue
        bucket = daily_z.setdefault(a.date, {f"z{i}": 0.0 for i in range(1, 6)})
        for k in bucket:
            bucket[k] += (a.time_in_zones or {}).get(k, 0)
    zones_daily = [
        {"date": d.isoformat(), **{f"{k}_s": round(v) for k, v in z.items()}}
        for d, z in sorted(daily_z.items())
    ]

    health_rows = db.scalars(
        select(DailyHealth).where(DailyHealth.user_id == user.id,
                                  DailyHealth.date >= start).order_by(DailyHealth.date)
    ).all()
    vo2max_series = [
        {"date": h.date.isoformat(), "vo2max": h.vo2max} for h in health_rows if h.vo2max
    ]
    latest_pred = next(
        (h for h in reversed(health_rows) if h.race_predictions), None
    )
    race_prediction = (
        {"date": latest_pred.date.isoformat(), **latest_pred.race_predictions}
        if latest_pred else None
    )

    goal = None
    race_prediction_series: list[dict] = []
    primary = races_mod.primary_race(db, user.id)
    if primary is not None:
        pred = races_mod.race_prediction_block(
            primary, races_mod.prediction_context(db, user.id))
        if pred["goal_time_s"]:
            goal = {
                "distance_km": primary.distance_km,
                "goal_time_s": pred["goal_time_s"],
                "predicted_time_s": pred["likely_s"],
            }
        # Garmin's predicted finish for THIS race's distance over time (each day's
        # race predictor, Riegel-adjusted) — a "getting fitter?" trend toward goal.
        for h in health_rows:
            if not h.race_predictions:
                continue
            t = races_mod.riegel_predict(h.race_predictions, primary.distance_km)
            if t:
                race_prediction_series.append(
                    {"date": h.date.isoformat(), "predicted_time_s": round(t)})

    signal = metrics.ramp_signal(db, user.id, end)
    ramp = {
        "series": metrics.ramp_series(db, user.id, start, end),
        "caution": metrics.RAMP_CAUTION,
        "high": metrics.RAMP_HIGH,
        "zone_today": (signal or {}).get("zone"),
        "chronic_trend": (signal or {}).get("chronic_trend"),
        "race": ({"name": primary.name, "date": primary.date.isoformat()}
                 if primary is not None else None),
    }

    return {
        "ef_series": ef_series,
        "zones_weekly": zones_weekly,
        "zones_daily": zones_daily,
        "vo2max_series": vo2max_series,
        "race_prediction": race_prediction,
        "race_prediction_series": race_prediction_series,
        "goal": goal,
        "ramp": ramp,
    }


# --- settings ----------------------------------------------------------------

def _settings_payload(db: Session, user: User, settings: dict) -> dict:
    """Settings + the read-only athlete_auto block — GET and PUT return the
    same shape (a bare-settings PUT response once crashed the settings page)."""
    weekly = metrics.weekly_km(db, user.id, dt.date.today())
    auto = settings_store.athlete_auto(db, user.id)
    auto["weekly_km_4wk"] = round(sum(weekly) / len(weekly), 1) if any(weekly) else None
    payload = {**settings, "athlete_auto": auto,
               # today's phase (read-only), so the cycle UI has one source of truth
               "cycle_status": metrics.cycle_phase(settings.get("cycle"), dt.date.today())}
    if not user.is_admin:
        # Whoever pays for the tokens picks the model — members never see or
        # set the provider (a future bring-your-own-key can unlock this).
        payload.pop("llm_provider", None)
    return payload


@router.get("/settings")
def read_settings(db: Session = Depends(get_db), user: User = Depends(current_user)):
    """User settings plus the read-only athlete_auto block (ignored by PUT)."""
    return _settings_payload(db, user, get_settings(db, user.id))


@router.put("/settings")
def write_settings(values: dict[str, Any], db: Session = Depends(get_db),
                   user: User = Depends(current_user)):
    return _settings_payload(
        db, user, put_settings(db, user.id, values, is_admin=bool(user.is_admin)))


# --- menstrual cycle ------------------------------------------------------------

class CycleStartedBody(BaseModel):
    date: str | None = None  # ISO; defaults to today (the "started today" one-tap)


@router.post("/cycle/started")
def cycle_started(body: CycleStartedBody, db: Session = Depends(get_db),
                  user: User = Depends(current_user)):
    """Re-anchor the cycle to an observed period start (drift self-correction)."""
    try:
        when = dt.date.fromisoformat(body.date) if body.date else dt.date.today()
    except ValueError:
        raise HTTPException(status_code=422, detail="invalid date")
    if when > dt.date.today():
        raise HTTPException(status_code=422, detail="date cannot be in the future")
    settings_store.reanchor_cycle(db, user.id, when)
    return _settings_payload(db, user, get_settings(db, user.id))


@router.post("/cycle/snooze")
def cycle_snooze(db: Session = Depends(get_db), user: User = Depends(current_user)):
    """"Not yet" — hide the drift prompt for the rest of today only."""
    settings_store.snooze_cycle_prompt(db, user.id, dt.date.today())
    return {"ok": True}


def _add_months(d: dt.date, n: int) -> dt.date:
    m = d.month - 1 + n
    return dt.date(d.year + m // 12, m % 12 + 1, 1)


@router.get("/cycle/calendar")
def cycle_calendar(months: int = 3, db: Session = Depends(get_db),
                   user: User = Depends(current_user)):
    """Per-day phase across `months` calendar months (from the 1st of this month),
    for the read-only month strip. Days are null-phase when tracking is off."""
    months = max(1, min(months, 12))
    cycle = get_settings(db, user.id).get("cycle")
    start = dt.date.today().replace(day=1)
    end = _add_months(start, months)
    days = []
    d = start
    while d < end:
        ph = metrics.cycle_phase(cycle, d)
        days.append({
            "date": d.isoformat(),
            "phase": ph["phase"] if ph else None,
            "ease_recommended": bool(ph and ph["ease_recommended"]),
        })
        d += dt.timedelta(days=1)
    return {"start": start.isoformat(), "end": end.isoformat(), "days": days}


# --- niggles (injury / pain tracking) -------------------------------------------

class NiggleBody(BaseModel):
    body_part: str
    severity: int = 1  # 1 niggle | 2 pain | 3 injury
    note: str = ""
    onset_date: str | None = None  # ISO; defaults to today


@router.get("/niggles")
def list_niggles(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return {"niggles": niggles_mod.active_niggles(db, user.id, dt.date.today()) or []}


@router.post("/niggles")
def create_niggle(body: NiggleBody, db: Session = Depends(get_db),
                  user: User = Depends(current_user)):
    if not body.body_part.strip():
        raise HTTPException(status_code=422, detail="body_part is required")
    if body.severity not in (1, 2, 3):
        raise HTTPException(status_code=422, detail="severity must be 1, 2 or 3")
    onset = None
    if body.onset_date:
        try:
            onset = dt.date.fromisoformat(body.onset_date)
        except ValueError:
            raise HTTPException(status_code=422, detail="invalid onset_date")
        if onset > dt.date.today():
            raise HTTPException(status_code=422, detail="onset_date cannot be in the future")
    n = niggles_mod.log_niggle(db, user.id, body.body_part, body.severity,
                               note=body.note, onset_date=onset, source="ui")
    return {"niggle": niggles_mod.niggle_dict(n, dt.date.today())}


@router.post("/niggles/{niggle_id}/resolve")
def resolve_niggle(niggle_id: int, db: Session = Depends(get_db),
                   user: User = Depends(current_user)):
    n = niggles_mod.resolve_niggle(db, user.id, niggle_id)
    if n is None:
        raise HTTPException(status_code=404, detail="niggle not found")
    return {"ok": True}


@router.post("/niggles/{niggle_id}/checkin")
def checkin_niggle(niggle_id: int, db: Session = Depends(get_db),
                   user: User = Depends(current_user)):
    """'Still sore' — keeps it open and re-arms the check-in window."""
    n = niggles_mod.checkin_niggle(db, user.id, niggle_id)
    if n is None:
        raise HTTPException(status_code=404, detail="niggle not found")
    return {"ok": True}


# --- coach-quality feedback (COACH_QUALITY.md) -----------------------------------

class FeedbackBody(BaseModel):
    surface: str  # coach_note | execution_analysis | edit_proposal
    ref: str      # coach_note: review date ISO; others: numeric id
    rating: int | None = None  # 1 up | -1 down | null (dismiss reason only)
    tags: list[str] = []
    comment: str = ""


@router.post("/feedback")
def post_feedback(body: FeedbackBody, db: Session = Depends(get_db),
                  user: User = Depends(current_user)):
    if body.surface not in feedback_mod.SURFACES:
        raise HTTPException(status_code=422, detail="unknown surface")
    if body.rating not in (1, -1, None):
        raise HTTPException(status_code=422, detail="rating must be 1, -1 or null")
    row = feedback_mod.record(db, user.id, body.surface, body.ref,
                              body.rating, body.tags, body.comment[:1000])
    if row is None:
        raise HTTPException(status_code=404, detail="nothing to rate there")
    return {"feedback": feedback_mod.feedback_state(db, user.id, body.surface, body.ref)}


@router.get("/feedback/summary")
def feedback_summary(days: int = 90, db: Session = Depends(get_db),
                     admin: User = Depends(admin_user)):
    """Stage-2 observability: per-surface / per-user thumb rates + the recent
    negative list (each entry a frozen eval case). Admin-only, like /usage."""
    return feedback_mod.summary(db, days=max(1, min(days, 365)))


# --- garmin connection / sync ---------------------------------------------------

class GarminConnectBody(BaseModel):
    email: str
    password: str


@router.post("/garmin/connect")
def garmin_connect(body: GarminConnectBody, db: Session = Depends(get_db),
                   user: User = Depends(current_user)):
    """Store Garmin credentials and verify them with a live login.

    First-time connections kick off two-stage onboarding (quick sync now, deep
    backfill in the background); updating credentials on an account that
    already has data just re-verifies — no 300-day re-download."""
    user.garmin_email = body.email
    user.garmin_password = crypto.encrypt(body.password)  # encrypted at rest
    db.add(user)
    db.commit()
    drop_client(user.id)
    try:
        get_garmin(user)  # performs the login; caches tokens on success
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"Garmin login failed: {e}")
    first_time = db.scalars(
        select(Activity).where(Activity.user_id == user.id).limit(1)
    ).first() is None
    if first_time:
        scheduler.onboard_user(user.id)
    return {"ok": True, "onboarding_started": first_time}


@router.post("/sync")
def sync_now(user: User = Depends(current_user)):
    """Fire-and-forget DATA sync (Garmin pull + enrichment; no LLM, no plan
    changes — replanning is the nightly job's or the coach-in-chat's business).
    Takes ~60s, longer than the frontend proxy's patience, and the UI polls
    /sync/status anyway."""
    if scheduler.is_running():
        return {"ok": True, "already_running": True}
    import threading

    threading.Thread(
        target=scheduler.sync_only_job,
        args=(user.id,),
        daemon=True,
    ).start()
    return {"ok": True, "started": True}


@router.get("/sync/status")
def sync_status(db: Session = Depends(get_db), user: User = Depends(current_user)):
    last = db.scalars(
        select(SyncLog).where(SyncLog.user_id == user.id)
        .order_by(SyncLog.ran_at.desc()).limit(1)
    ).first()
    return {
        "last_run": last.ran_at.isoformat() if last else None,
        "last_status": last.status if last else None,
        "last_detail": last.detail if last else None,
        "running": scheduler.is_running(),
        "backfill": backfill.progress(user.id),
        "garmin_connected": has_garmin(user),
    }


class BackfillBody(BaseModel):
    days: int = Field(default=300, ge=7, le=1000)


@router.post("/backfill")
def start_backfill(body: BackfillBody, user: User = Depends(current_user)):
    if not backfill.start(user.id, body.days):
        raise HTTPException(409, "History is already loading — check the progress banner.")
    return {"ok": True, "started": True}


# --- pending edits (chat approval queue) --------------------------------------

@router.get("/edits/pending")
def pending_edit(db: Session = Depends(get_db), user: User = Depends(current_user)):
    edit = _pending_edit(db, user.id)
    return edit_dict(edit) if edit else None


def _own_pending_edit(db: Session, user_id: int, edit_id: int) -> PendingEdit:
    edit = db.get(PendingEdit, edit_id)
    if edit is None or edit.user_id != user_id:
        raise HTTPException(404, "no such pending edit")
    if edit.status != "pending":
        # 409 with the resolved status so the UI can flip the stale card
        # instead of showing a generic failure.
        detail = {
            "accepted": "This proposal was already accepted.",
            "dismissed": "This proposal was already dismissed.",
            "superseded": "This proposal was superseded by a newer one — "
                          "look for the coach's latest proposal.",
        }.get(edit.status, "This proposal is no longer pending.")
        raise HTTPException(409, detail)
    return edit


@router.post("/edits/{edit_id}/accept")
def accept_edit(edit_id: int, db: Session = Depends(get_db),
                user: User = Depends(current_user)):
    edit = _own_pending_edit(db, user.id, edit_id)
    changed = apply_plan_days(db, user.id, edit.changes, source="chat_edit",
                              summary=edit.summary)
    edit.status = "accepted"
    db.commit()
    if get_settings(db, user.id).get("auto_push_workouts") and changed:
        push_days(db, changed)
    return {"ok": True}


@router.post("/edits/{edit_id}/dismiss")
def dismiss_edit(edit_id: int, db: Session = Depends(get_db),
                 user: User = Depends(current_user)):
    edit = _own_pending_edit(db, user.id, edit_id)
    edit.status = "dismissed"
    db.commit()
    return {"ok": True}


# --- chat --------------------------------------------------------------------

class ChatBody(BaseModel):
    session_id: str | None = None
    message: str
    context_date: str | None = None


@router.post("/chat")
def chat(body: ChatBody, db: Session = Depends(get_db),
         user: User = Depends(current_user)):
    from . import rate_limit
    from .chat.shortcuts import expand

    # Slot first, quota second: a send refused because a stream is running must
    # not burn the member's daily message quota (check_message records on pass).
    gen = rate_limit.acquire_stream(user.id)
    try:
        rate_limit.check_message(user, body.message)  # 429/400 before any LLM spend
        # The user's message is displayed/persisted verbatim; shortcut expansion and
        # the context-date prefix only enter the model-facing history (llm_text).
        llm_text, is_shortcut = expand(body.message)
        if body.context_date:
            llm_text = f"(Regarding the workout planned for {body.context_date})\n{llm_text}"
    except Exception:
        rate_limit.release_stream(user.id, gen)  # never leak the slot pre-stream
        raise

    def event_stream():
        try:
            for event in run_chat(db, user, body.session_id, body.message,
                                  llm_text=llm_text,
                                  kind="shortcut" if is_shortcut else "text",
                                  stream_gen=gen):
                yield f"data: {json.dumps(event)}\n\n"
        finally:
            rate_limit.release_stream(user.id, gen)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/chat/stop")
def chat_stop(user: User = Depends(current_user)):
    """Ask the user's live stream to stop after the current token/tool step."""
    from . import rate_limit

    return {"ok": True, "stopping": rate_limit.request_cancel(user.id)}


@router.get("/chat/sessions")
def chat_sessions(db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows = db.execute(
        select(ChatMessage.session_id, ChatMessage.created_at, ChatMessage.content)
        .where(ChatMessage.user_id == user.id)
        .order_by(ChatMessage.created_at)
    ).all()
    sessions: dict[str, dict] = {}
    for sid, created_at, content in rows:
        if sid not in sessions:
            sessions[sid] = {
                "id": sid,
                "created_at": created_at.isoformat(),
                "title": (content or "")[:60] or "New chat",
            }
    return sorted(sessions.values(), key=lambda s: s["created_at"], reverse=True)


@router.get("/chat/history")
def chat_history(session_id: str, db: Session = Depends(get_db),
                 user: User = Depends(current_user)):
    rows = db.scalars(
        select(ChatMessage).where(ChatMessage.user_id == user.id,
                                  ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at)
    ).all()
    out = []
    for r in rows:
        msg = {
            "role": r.role,
            "kind": r.kind or "text",
            "content": r.content,
            "created_at": r.created_at.isoformat(),
        }
        # Hydrate proposal markers with the edit's CURRENT state so the frontend
        # renders live Accept/Dismiss buttons only while it's still pending.
        if r.kind == "edit_proposed" and (r.payload or {}).get("edit_id"):
            edit = db.get(PendingEdit, r.payload["edit_id"])
            if edit is not None and edit.user_id == user.id:
                msg["edit"] = edit_dict(edit)
        out.append(msg)
    return out
