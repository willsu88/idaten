from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class User(Base):
    """A household member. All data tables hang off user_id; tenant identity is
    always bound server-side from the session cookie, never from client input."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String, unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String, default="")
    password_hash: Mapped[str] = mapped_column(String)
    # Per-user Garmin credentials; tokens cache under garmin_token_dir/<user_id>/
    garmin_email: Mapped[str | None] = mapped_column(String)
    garmin_password: Mapped[str | None] = mapped_column(String)
    # The first user is the admin: manages invites, removals, password resets.
    # Nullable because the column was added by _auto_migrate (NULL = not admin).
    is_admin: Mapped[bool | None] = mapped_column(Boolean, default=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuthSession(Base):
    """Server-side login sessions (httpOnly cookie holds the token)."""

    __tablename__ = "auth_sessions"

    token: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))


class InviteToken(Base):
    """One-time signed links: household invites and password resets.

    Only the SHA-256 of the token is stored; the raw token appears exactly once,
    in the URL handed to the admin. No email infrastructure needed — the admin
    sends the link over whatever messenger they like."""

    __tablename__ = "invite_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    token_hash: Mapped[str] = mapped_column(String, unique=True, index=True)
    kind: Mapped[str] = mapped_column(String)  # invite | password_reset
    user_id: Mapped[int | None] = mapped_column(Integer)  # reset target (kind=password_reset)
    created_by: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class Setting(Base):
    """Per-user key/value JSON store for preferences (athlete profile...)."""

    __tablename__ = "settings"

    user_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[Any] = mapped_column(JSON)


class Activity(Base):
    __tablename__ = "activities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)  # Garmin activity id
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    date: Mapped[dt.date] = mapped_column(Date, index=True)
    type: Mapped[str] = mapped_column(String, default="running")
    name: Mapped[str] = mapped_column(String, default="")
    distance_m: Mapped[float | None] = mapped_column(Float)
    duration_s: Mapped[float | None] = mapped_column(Float)
    avg_hr: Mapped[float | None] = mapped_column(Float)
    avg_speed_mps: Mapped[float | None] = mapped_column(Float)
    training_load: Mapped[float | None] = mapped_column(Float)
    rpe: Mapped[int | None] = mapped_column(Integer)       # athlete-entered in-app (1-10)
    rpe_note: Mapped[str | None] = mapped_column(Text)
    # Logged on the Garmin watch/app; kept SEPARATE from `rpe` to preserve
    # provenance (watch vs in-app). Populated only when the athlete logged them.
    garmin_rpe: Mapped[int | None] = mapped_column(Integer)          # 1-10 (Garmin stores x10)
    feel: Mapped[int | None] = mapped_column(Integer)               # 1-5 (Very Weak..Very Strong)
    body_battery_change: Mapped[float | None] = mapped_column(Float)  # BB delta over the activity
    raw: Mapped[Any] = mapped_column(JSON, default=dict)
    # Enrichment (fetched per-activity after sync; see garmin/enrich.py)
    cadence: Mapped[float | None] = mapped_column(Float)          # avg double cadence spm
    start_lat: Mapped[float | None] = mapped_column(Float)
    start_lon: Mapped[float | None] = mapped_column(Float)
    temperature_c: Mapped[float | None] = mapped_column(Float)
    hr_drift_pct: Mapped[float | None] = mapped_column(Float)     # aerobic decoupling
    time_in_zones: Mapped[Any] = mapped_column(JSON, nullable=True)  # {"z1": s, ..., "z5": s}
    # Downsampled chart series (columnar: {"t_s": [...], "hr": [...], ...}) and
    # per-km splits — cached on first fetch (enrichment or on-demand endpoint).
    series: Mapped[Any] = mapped_column(JSON, nullable=True)
    splits: Mapped[Any] = mapped_column(JSON, nullable=True)
    # GPS route ([[lat, lon], ...], downsampled) — cached like series/splits.
    # None = never fetched; [] = fetched, activity has no GPS (indoor).
    route: Mapped[Any] = mapped_column(JSON, nullable=True)
    # Execution score (0-100): how well the run matched the workout it was
    # attempting. Only set for runs attributed to a planned workout (never a free
    # run). `source` = "garmin" (pulled from the watch's own compliance score) or
    # "idaten" (we computed it); `breakdown` is the per-segment detail.
    execution_score: Mapped[int | None] = mapped_column(Integer)
    execution_score_source: Mapped[str | None] = mapped_column(String)  # garmin | idaten
    execution_breakdown: Mapped[Any] = mapped_column(JSON, nullable=True)
    # Athlete's answer to "was this run an attempt at the planned workout?" when
    # auto-attribution was ambiguous. None = not asked/undecided, True = confirmed
    # (then scored), False = "just a run" (never scored, never re-asked).
    execution_attributed: Mapped[bool | None] = mapped_column(Boolean)
    # LLM analysis narrative for the score. Generated LAZILY, once, when the Today
    # page loads on a recent scored run (never for old history, never at sync).
    # Null = not generated; non-null = cached forever.
    execution_analysis: Mapped[str | None] = mapped_column(Text)
    # The coach persona (coach_style key) that wrote the analysis, stamped at
    # generation time so a later coach switch never rewrites who said it.
    execution_analysis_coach: Mapped[str | None] = mapped_column(String)
    # Provenance for the quality-feedback loop (COACH_QUALITY.md): the exact
    # input payload and system-prompt hash that produced the analysis, stamped
    # at generation time so a rating freezes a reproducible eval case.
    execution_analysis_context: Mapped[Any] = mapped_column(JSON, nullable=True)
    execution_analysis_prompt_version: Mapped[str | None] = mapped_column(String)
    # Shoe worn (Gear.uuid), mirrored from Garmin's gear-service at sync time and
    # written back to Garmin when edited in-app. Only ever a Shoes-type gear —
    # other gear types on the activity are left alone.
    gear_uuid: Mapped[str | None] = mapped_column(String)
    # True after the athlete rejects a shoe suggestion for this activity; the
    # predictor never re-suggests on it.
    gear_suggestion_dismissed: Mapped[bool | None] = mapped_column(Boolean)
    enriched: Mapped[bool] = mapped_column(Boolean, default=False)


class Gear(Base):
    """Garmin gear (shoes, mainly), mirrored at sync time — see garmin/gear.py.

    Totals come from Garmin's gear-service stats, so they cover the shoe's whole
    life, not just our sync window. Photos are instance-local user uploads
    (stored under config.gear_image_dir); the repo ships no imagery."""

    __tablename__ = "gear"

    uuid: Mapped[str] = mapped_column(String, primary_key=True)  # Garmin gear UUID
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(String, default="")  # customMakeModel / display name
    make: Mapped[str] = mapped_column(String, default="")
    model: Mapped[str] = mapped_column(String, default="")
    gear_type: Mapped[str] = mapped_column(String, default="")   # "Shoes", "Bike", ...
    status: Mapped[str] = mapped_column(String, default="active")  # active | retired
    date_begin: Mapped[dt.date | None] = mapped_column(Date)
    maximum_meters: Mapped[float | None] = mapped_column(Float)  # athlete's retire-at limit
    total_distance_m: Mapped[float | None] = mapped_column(Float)
    total_activities: Mapped[int | None] = mapped_column(Integer)
    # Extension of the uploaded photo ("jpg"|"png"|"webp"); null = no photo,
    # the frontend renders its generated card instead.
    image_ext: Mapped[str | None] = mapped_column(String)
    synced_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DailyHealth(Base):
    __tablename__ = "daily_health"

    user_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    sleep_seconds: Mapped[float | None] = mapped_column(Float)
    sleep_score: Mapped[float | None] = mapped_column(Float)
    hrv: Mapped[float | None] = mapped_column(Float)           # last-night avg
    hrv_baseline: Mapped[float | None] = mapped_column(Float)  # Garmin weekly avg
    resting_hr: Mapped[float | None] = mapped_column(Float)
    body_battery: Mapped[float | None] = mapped_column(Float)  # morning/max value
    stress_avg: Mapped[float | None] = mapped_column(Float)
    vo2max: Mapped[float | None] = mapped_column(Float)
    race_predictions: Mapped[Any] = mapped_column(JSON, nullable=True)  # {"time_5k_s": ...}


class Race(Base):
    """Upcoming races; exactly one per user is primary (the plan's target)."""

    __tablename__ = "races"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(String)
    date: Mapped[dt.date] = mapped_column(Date, index=True)
    distance_km: Mapped[float] = mapped_column(Float)
    goal_time: Mapped[str] = mapped_column(String, default="")  # "3:45:00"
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    # "manual" (created in the app) or "garmin" (imported from the Garmin
    # calendar). Legacy rows are NULL — treat as manual. Import never overwrites
    # fields of an existing row: app-side edits win.
    source: Mapped[str | None] = mapped_column(String)
    garmin_uuid: Mapped[str | None] = mapped_column(String, index=True)
    # Course polyline ([[lat, lon], ...], athlete-imported from a Google My Maps
    # link or KML/KMZ/GPX file — see course.py). Same shape as Activity.route.
    course: Mapped[Any] = mapped_column(JSON, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DayIntent(Base):
    """A user-declared non-running day (surfing, hiking, ...) that the planner
    and chat agent must plan around — a run is never scheduled on these days."""

    __tablename__ = "day_intents"

    user_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    sport: Mapped[str] = mapped_column(String)
    note: Mapped[str] = mapped_column(Text, default="")
    duration_min: Mapped[float | None] = mapped_column(Float)
    effort: Mapped[str | None] = mapped_column(String)  # easy | moderate | hard
    source: Mapped[str] = mapped_column(String, default="manual")  # manual | chat


class Niggle(Base):
    """An athlete-reported pain signal (niggle / pain / injury), open until
    resolved. The open set feeds the daily review as a deterministic signal —
    a real coach's most important input, and the one thing Garmin can't see.
    A table (not a settings blob) because we want history and multiple
    concurrent entries."""

    __tablename__ = "niggles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    body_part: Mapped[str] = mapped_column(String)  # "left knee", "right achilles"
    severity: Mapped[int] = mapped_column(Integer, default=1)  # 1 niggle | 2 pain | 3 injury
    onset_date: Mapped[dt.date] = mapped_column(Date)
    resolved_date: Mapped[dt.date | None] = mapped_column(Date)  # null = still open
    note: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String, default="chat")  # chat | ui
    # Last "still sore, keep it open" check-in tap; re-arms the check-in window.
    checkin_date: Mapped[dt.date | None] = mapped_column(Date)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class SupportSession(Base):
    """A planned non-run session (strength for now) — the parallel lane beside
    plan_days. Deliberately NOT a PlanDay: it never collides with editor-mode
    materialization, watch push, or run execution scoring. A synced strength
    activity on the session's date auto-completes it; a manual "did it" covers
    watchless sessions."""

    __tablename__ = "support_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    date: Mapped[dt.date] = mapped_column(Date, index=True)
    kind: Mapped[str] = mapped_column(String, default="strength")  # strength (only, for now)
    duration_min: Mapped[float | None] = mapped_column(Float)
    focus: Mapped[str] = mapped_column(String, default="")  # "hips & glutes", "full body"
    rationale: Mapped[str] = mapped_column(Text, default="")  # the coach's one-line why
    status: Mapped[str] = mapped_column(String, default="planned")  # planned|completed|skipped
    source: Mapped[str] = mapped_column(String, default="manual")  # author|chat_edit|manual
    # The synced activity that completed this session (null for manual completes).
    activity_id: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class PlanDay(Base):
    __tablename__ = "plan_days"

    user_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    workout_type: Mapped[str] = mapped_column(String, default="rest")
    title: Mapped[str] = mapped_column(String, default="Rest")
    description: Mapped[str] = mapped_column(Text, default="")
    duration_min: Mapped[float | None] = mapped_column(Float)
    distance_km: Mapped[float | None] = mapped_column(Float)
    target_pace: Mapped[str | None] = mapped_column(String)  # "5:30" min/km
    target_hr_low: Mapped[int | None] = mapped_column(Integer)   # bpm (hr/hybrid modes)
    target_hr_high: Mapped[int | None] = mapped_column(Integer)
    steps: Mapped[list | None] = mapped_column(JSON)  # [{repeat, steps:[{kind,...}]}]; null = simple
    rationale: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String, default="planned")  # planned|completed|skipped
    version_id: Mapped[int | None] = mapped_column(ForeignKey("plan_versions.id"))
    garmin_workout_id: Mapped[str | None] = mapped_column(String)
    pushed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class PlanVersion(Base):
    """One row per plan mutation, for history/audit."""

    __tablename__ = "plan_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    source: Mapped[str] = mapped_column(String)  # daily_job | chat_edit | manual
    summary: Mapped[str] = mapped_column(Text, default="")
    snapshot: Mapped[Any] = mapped_column(JSON, default=list)  # the 7-day plan as written


class PendingEdit(Base):
    """A plan change proposed by the chat agent, awaiting user approval."""

    __tablename__ = "pending_edits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    summary: Mapped[str] = mapped_column(Text, default="")
    rationale: Mapped[str] = mapped_column(Text, default="")
    changes: Mapped[Any] = mapped_column(JSON, default=list)  # proposed PlanDay dicts
    current: Mapped[Any] = mapped_column(JSON, default=list)  # pre-edit PlanDay dicts
    # Proposed strength sessions ({date, duration_min, focus, rationale} dicts);
    # nullable=True is required — Mapped[Any] JSON columns are NOT NULL by default.
    strength: Mapped[Any] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String, default="pending")  # pending|accepted|dismissed


class TrainingPlan(Base):
    """The user's active Garmin Coach adaptive plan, mirrored read-only at
    sync time. One row per user; deleted when Garmin has no active plan.

    Garmin's phase timeline (BASE/BUILD/PEAK/TAPER) and week numbering are
    ground truth for 'which week am I on' — the app must never reset an
    athlete mid-plan back to week 1."""

    __tablename__ = "training_plans"

    user_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    garmin_plan_id: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String, default="")
    start_date: Mapped[dt.date] = mapped_column(Date)
    end_date: Mapped[dt.date] = mapped_column(Date)
    duration_weeks: Mapped[int | None] = mapped_column(Integer)
    avg_weekly_workouts: Mapped[int | None] = mapped_column(Integer)
    # [{"phase": "base", "label": "Base", "start_date": ..., "end_date": ...}]
    phases: Mapped[Any] = mapped_column(JSON, default=list)
    # Scheduled Garmin Coach workouts around today (small mirror window)
    upcoming_tasks: Mapped[Any] = mapped_column(JSON, default=list)
    synced_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DailyReview(Base):
    """One row per user per day: the artifact of the daily `evaluate_today`
    review. Holds the eval state machine, the persona-voiced coach note, and a
    link to any proposal the review raised.

    Distinct from PlanVersion (which audits plan *mutations*): a review very
    often changes nothing yet still owes the athlete a coach note, so it needs
    its own home. `state` also gates the one-LLM-call-per-day contract."""

    __tablename__ = "daily_reviews"

    user_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    # pending_data  — today's readiness/sleep not synced yet; NO LLM spent
    # done_full     — evaluated with today's data
    # done_structural — evaluated without last night's data (structural-only)
    state: Mapped[str] = mapped_column(String, default="pending_data")
    mode: Mapped[str | None] = mapped_column(String)  # editor | author
    coach_note: Mapped[str] = mapped_column(Text, default="")
    # The coach persona (coach_style key) that wrote the note, stamped at
    # generation time so a later coach switch never rewrites who said it
    # (same contract as Activity.execution_analysis_coach). Null on old rows.
    coach: Mapped[str | None] = mapped_column(String)
    # The PendingEdit this review raised, if any (null = nothing proposed).
    proposal_id: Mapped[int | None] = mapped_column(ForeignKey("pending_edits.id"))
    # Provenance for the quality-feedback loop (COACH_QUALITY.md): the review
    # snapshot and system-prompt hash that produced the coach_note, stamped at
    # generation time so a rating freezes a reproducible eval case.
    snapshot: Mapped[Any] = mapped_column(JSON, nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


REVIEW_STATES = ("pending_data", "done_full", "done_structural")


class Feedback(Base):
    """A thumbs rating (or proposal-dismiss reason) on a coach-authored output.

    The rated artifact's text and producing inputs are FROZEN into the row at
    rating time, so every entry is a complete (inputs, output, label, reason)
    example for the eval regression set — see COACH_QUALITY.md. One row per
    (user, surface, artifact_ref); re-rating updates in place."""

    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    surface: Mapped[str] = mapped_column(String)  # coach_note | execution_analysis | edit_proposal
    artifact_ref: Mapped[str] = mapped_column(String)  # review date ISO | activity id | edit id
    rating: Mapped[int | None] = mapped_column(Integer)  # 1 up | -1 down | null (dismiss reason only)
    tags: Mapped[Any] = mapped_column(JSON, default=list)  # preset reason chips
    comment: Mapped[str] = mapped_column(Text, default="")
    artifact_text: Mapped[str] = mapped_column(Text, default="")  # frozen output
    context: Mapped[Any] = mapped_column(JSON, nullable=True)  # frozen producing inputs (snapshot), if stored
    prompt_version: Mapped[str | None] = mapped_column(String)  # hash of the producing system prompt
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    session_id: Mapped[str] = mapped_column(String, index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    role: Mapped[str] = mapped_column(String)  # user | assistant
    # kind "text": content is the message (markdown).
    # kind "edit_proposed": payload = {"edit_id": ...}; content is a plain-text
    # fallback so LLM history replay still reads sensibly.
    kind: Mapped[str] = mapped_column(String, default="text")
    content: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[Any] = mapped_column(JSON, nullable=True)


class SyncLog(Base):
    __tablename__ = "sync_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    ran_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    status: Mapped[str] = mapped_column(String)  # ok | error
    detail: Mapped[str] = mapped_column(Text, default="")
    plan_updated: Mapped[bool] = mapped_column(Boolean, default=False)
    kind: Mapped[str | None] = mapped_column(String, default="full")  # full | data


class LlmUsage(Base):
    """One row per LLM API call, written at the LLMClient seam. `call_site` is
    the feature that made the call (plan | review | execution_analysis | chat),
    the dimension the provider console can't give us. `cost_usd` is derived from
    a price map at write time (see app/usage.py); tokens are exact."""

    __tablename__ = "llm_usage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    ts: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    provider: Mapped[str] = mapped_column(String)  # anthropic | openai
    model: Mapped[str] = mapped_column(String)
    call_site: Mapped[str] = mapped_column(String, index=True)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_creation_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
