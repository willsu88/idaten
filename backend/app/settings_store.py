"""Per-user preferences stored in the settings table (env values are defaults)."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import config
from .models import Setting, User

TRAINING_MODES = ("pace", "hr", "hybrid")
COACH_STYLES = ("default", "chill", "strict")
# How Idaten produces the plan relative to an active Garmin Coach plan:
#   auto   — editor (review + diff) when a Garmin plan is present, else author
#   author — force full authoring even when a Garmin plan is present
PLAN_AUTHORING = ("auto", "author")

DEFAULTS: dict = {
    "athlete": {"age": None, "weekly_km": None, "notes": ""},
    "llm_provider": config.llm_provider,
    "auto_push_workouts": config.auto_push_workouts,
    "plan_hour": config.plan_hour,
    "training_mode": "hybrid",
    "coach_style": "default",
    "plan_authoring": "auto",
    # Menstrual cycle tracking — opt-in, set-once anchor + forward projection.
    # The `enabled` toggle is the feature gate (NOT a gender flag). See
    # metrics.cycle_phase for how the anchor becomes a daily coaching signal.
    "cycle": {
        "enabled": False,
        "last_start_date": None,       # ISO date of the most recent period start
        "cycle_length_days": 28,
        "period_length_days": 5,
    },
    # Strength training — the athlete's weekly-target contract. sessions_per_week
    # 0 = feature off. The target settles WHETHER strength is wanted; the coach
    # only ever decides WHEN and WHAT. Guidance, not a quota.
    "strength": {
        "sessions_per_week": 0,      # 0-3
        "focus": "coach",            # coach decides | full | upper | lower
    },
    "tutorial_done": False,
    "page_hints_seen": [],  # page ids whose first-run coach pointer was dismissed
}

STRENGTH_FOCUS = ("coach", "full", "upper", "lower")

# Internal keys written by server code only — not in DEFAULTS, so they are
# invisible to GET/PUT /api/settings and the client can never tamper with them.
GARMIN_PROFILE_KEY = "garmin_profile"
# Drift-prompt state — server-owned, NOT part of the user-facing `cycle` blob so a
# settings PUT that omits them can't wipe them. Set by the dedicated endpoints.
CYCLE_CONFIRMED_KEY = "cycle_confirmed_start"  # ISO date of the last user-confirmed start
CYCLE_SNOOZE_KEY = "cycle_snooze_date"         # ISO date the athlete tapped "Not yet"
RACE_PRIMARY_OVERRIDE_KEY = "race_primary_manual"       # bool: user chose a primary
DELETED_GARMIN_RACES_KEY = "deleted_garmin_race_uuids"  # tombstones for race import
# The athlete's Garmin HR-zone boundaries, observed from activity payloads. This
# is Garmin's OWN per-athlete basis (whatever calc method they picked — max HR,
# %HRR, %LTHR) so it matches what their watch/coach scores against. Kept in its
# own key (not the profile blob, which sync_profile rewrites wholesale).
GARMIN_HR_ZONES_KEY = "garmin_hr_zones"  # {"zones": {"z1":[lo,hi],...}, "date": ISO}


def normalize_cycle(value) -> dict:
    """Coerce a stored/submitted cycle blob into the canonical shape.

    Robust to partial or malformed input (an old row, a client that PUTs only
    some keys): unknown/bad fields fall back to the default, so cycle_phase
    always receives a well-formed dict. An invalid anchor date is dropped to
    None (tracking simply produces no signal until re-entered)."""
    base = dict(DEFAULTS["cycle"])
    if not isinstance(value, dict):
        return base
    if isinstance(value.get("enabled"), bool):
        base["enabled"] = value["enabled"]
    anchor = value.get("last_start_date")
    if isinstance(anchor, str) and anchor:
        try:
            dt.date.fromisoformat(anchor)
            base["last_start_date"] = anchor
        except ValueError:
            pass  # keep None
    for key, lo, hi in (("cycle_length_days", 15, 60), ("period_length_days", 1, 14)):
        v = value.get(key)
        if isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi:
            base[key] = v
    return base


def normalize_strength(value) -> dict:
    """Coerce a stored/submitted strength blob into the canonical shape (same
    robustness contract as normalize_cycle): bad fields fall back to defaults."""
    base = dict(DEFAULTS["strength"])
    if not isinstance(value, dict):
        return base
    n = value.get("sessions_per_week")
    if isinstance(n, int) and not isinstance(n, bool) and 0 <= n <= 3:
        base["sessions_per_week"] = n
    if value.get("focus") in STRENGTH_FOCUS:
        base["focus"] = value["focus"]
    return base


def get_settings(db: Session, user_id: int) -> dict:
    out = dict(DEFAULTS)
    for row in db.scalars(select(Setting).where(Setting.user_id == user_id)):
        if row.key in DEFAULTS:
            out[row.key] = row.value
    if out.get("training_mode") not in TRAINING_MODES:
        out["training_mode"] = "hybrid"
    if out.get("coach_style") not in COACH_STYLES:
        out["coach_style"] = "default"
    if out.get("plan_authoring") not in PLAN_AUTHORING:
        out["plan_authoring"] = "auto"
    if not isinstance(out.get("page_hints_seen"), list):
        out["page_hints_seen"] = []
    out["cycle"] = normalize_cycle(out.get("cycle"))
    out["strength"] = normalize_strength(out.get("strength"))
    # Whoever pays for the tokens picks the model: non-admins always run on the
    # server default, even if an old row holds a value from before the gate.
    user = db.get(User, user_id)
    if user is not None and not user.is_admin:
        out["llm_provider"] = config.llm_provider
    return out


def put_settings(db: Session, user_id: int, values: dict, is_admin: bool = True) -> dict:
    if "training_mode" in values and values["training_mode"] not in TRAINING_MODES:
        values = {k: v for k, v in values.items() if k != "training_mode"}
    if "coach_style" in values and values["coach_style"] not in COACH_STYLES:
        values = {k: v for k, v in values.items() if k != "coach_style"}
    if "plan_authoring" in values and values["plan_authoring"] not in PLAN_AUTHORING:
        values = {k: v for k, v in values.items() if k != "plan_authoring"}
    if "page_hints_seen" in values and not (
        isinstance(values["page_hints_seen"], list)
        and all(isinstance(p, str) for p in values["page_hints_seen"])
    ):
        values = {k: v for k, v in values.items() if k != "page_hints_seen"}
    if "cycle" in values:
        values = {**values, "cycle": normalize_cycle(values["cycle"])}
    if "strength" in values:
        values = {**values, "strength": normalize_strength(values["strength"])}
    if not is_admin:
        values = {k: v for k, v in values.items() if k != "llm_provider"}
    for key in DEFAULTS:
        if key in values:
            db.merge(Setting(user_id=user_id, key=key, value=values[key]))
    db.commit()
    return get_settings(db, user_id)


def reanchor_cycle(db: Session, user_id: int, new_start: dt.date) -> dict:
    """Re-anchor the cycle to an observed period start (the drift self-correction).

    Moves `last_start_date` to `new_start` and gently nudges `cycle_length_days`
    toward the observed gap since the previous anchor — a light 2:1 blend so one
    early/late month doesn't whipsaw the estimate, but a consistent drift is
    absorbed over a couple of cycles. Enables tracking if it wasn't already.
    Returns the full settings dict (with a recomputed cycle_status upstream)."""
    settings = get_settings(db, user_id)
    cycle = dict(settings["cycle"])
    old_anchor = cycle.get("last_start_date")
    length = cycle.get("cycle_length_days") or DEFAULTS["cycle"]["cycle_length_days"]
    if old_anchor:
        try:
            observed = (new_start - dt.date.fromisoformat(old_anchor)).days
        except ValueError:
            observed = None
        if observed is not None and 15 <= observed <= 60:
            length = round((length * 2 + observed) / 3)
    cycle["last_start_date"] = new_start.isoformat()
    cycle["cycle_length_days"] = length
    cycle["enabled"] = True
    saved = put_settings(db, user_id, {"cycle": cycle})
    # Mark this cycle's start as confirmed and clear any "Not yet" snooze, so the
    # Today prompt stops asking until we approach the NEXT predicted start.
    put_internal(db, user_id, CYCLE_CONFIRMED_KEY, new_start.isoformat())
    put_internal(db, user_id, CYCLE_SNOOZE_KEY, None)
    return saved


def snooze_cycle_prompt(db: Session, user_id: int, on: dt.date) -> None:
    """Record a "Not yet" tap so the drift prompt stays hidden for that day."""
    put_internal(db, user_id, CYCLE_SNOOZE_KEY, on.isoformat())


# Per-user race-prediction calibration. `k` multiplies GARMIN's race-predictor
# time to correct that athlete's systematic optimism/pessimism, learned from real
# race results (actual finish / Garmin's prediction for the same race). Default
# 1.0 = trust Garmin until a real race says otherwise; a runner who finishes
# slower than Garmin predicted pushes k above 1, faster pushes it below. Clamped
# to a sane band so one weird day (a blow-up, a downhill PR) can't distort it.
RACE_PRED_CALIBRATION_KEY = "race_pred_calibration"  # {"k": float, "samples": [...]}
RACE_PRED_K_DEFAULT = 1.0
RACE_PRED_ALPHA = 0.35          # EWMA weight on each new race (~3 races to converge)
RACE_PRED_K_MIN, RACE_PRED_K_MAX = 0.85, 1.25
RACE_PRED_SAMPLES_MAX = 20


def get_race_calibration(db: Session, user_id: int) -> dict:
    """{"k": float, "samples": [{race_id, predicted_s, actual_s, at}]}."""
    v = get_internal(db, user_id, RACE_PRED_CALIBRATION_KEY) or {}
    k = v.get("k")
    if not isinstance(k, (int, float)) or isinstance(k, bool) or not (
            RACE_PRED_K_MIN <= k <= RACE_PRED_K_MAX):
        k = RACE_PRED_K_DEFAULT
    return {"k": float(k), "samples": v.get("samples") or []}


def update_race_calibration(db: Session, user_id: int, race_id: int,
                            predicted_s: float | None, actual_s: float | None,
                            on: dt.date) -> dict:
    """Fold one completed race into the per-user factor `k` via EWMA, then clamp.

    `predicted_s` is the RAW (pre-`k`) prediction for the race. Idempotent per
    race: a race already in `samples` is skipped so re-ingesting an activity
    can't double-count. Returns the updated calibration.
    """
    cal = get_race_calibration(db, user_id)
    if (not predicted_s or not actual_s or predicted_s <= 0 or actual_s <= 0
            or any(s.get("race_id") == race_id for s in cal["samples"])):
        return cal
    observed = actual_s / predicted_s
    k = (1 - RACE_PRED_ALPHA) * cal["k"] + RACE_PRED_ALPHA * observed
    k = max(RACE_PRED_K_MIN, min(RACE_PRED_K_MAX, k))
    samples = (cal["samples"] + [{
        "race_id": race_id,
        "predicted_s": round(predicted_s),
        "actual_s": round(actual_s),
        "at": on.isoformat(),
    }])[-RACE_PRED_SAMPLES_MAX:]
    put_internal(db, user_id, RACE_PRED_CALIBRATION_KEY, {"k": round(k, 4), "samples": samples})
    return {"k": round(k, 4), "samples": samples}


def get_internal(db: Session, user_id: int, key: str, default=None):
    row = db.get(Setting, (user_id, key))
    return row.value if row is not None else default


def put_internal(db: Session, user_id: int, key: str, value) -> None:
    db.merge(Setting(user_id=user_id, key=key, value=value))
    db.commit()


def get_garmin_profile(db: Session, user_id: int) -> dict | None:
    return get_internal(db, user_id, GARMIN_PROFILE_KEY)


def get_garmin_hr_zones(db: Session, user_id: int) -> dict | None:
    """The athlete's cached Garmin HR-zone bands {"z1":[lo,hi],...} or None."""
    return (get_internal(db, user_id, GARMIN_HR_ZONES_KEY) or {}).get("zones")


def put_garmin_hr_zones(db: Session, user_id: int, zones: dict | None,
                        on_date: str | None) -> None:
    """Cache observed Garmin HR-zone bands, keeping the newest observation.

    Bands arrive per-activity; a later run's zones supersede an earlier one's, so
    forward planning always uses the athlete's current configuration while a past
    run stays judged against whatever was in effect when it was run.
    """
    if not zones:
        return
    cur = get_internal(db, user_id, GARMIN_HR_ZONES_KEY) or {}
    if cur.get("date") and on_date and cur["date"] >= on_date:
        return
    put_internal(db, user_id, GARMIN_HR_ZONES_KEY, {"zones": zones, "date": on_date})


def hr_zones(db: Session, user_id: int) -> dict | None:
    """The athlete's HR zones — the single source for planner targets AND
    execution scoring. Prefers Garmin's own per-athlete boundaries (the basis
    Garmin itself scores against); falls back to LTHR-derived Friel zones only
    until we've observed a real set. None when neither is available.
    """
    from . import metrics  # lazy: metrics has no settings_store dependency
    return (get_garmin_hr_zones(db, user_id)
            or metrics.hr_zones_from_lthr(athlete_auto(db, user_id).get("lthr")))


def athlete_auto(db: Session, user_id: int) -> dict:
    """The read-only athlete block derived from the Garmin profile."""
    p = get_garmin_profile(db, user_id) or {}
    age = None
    if p.get("birth_date"):
        try:
            born = dt.date.fromisoformat(p["birth_date"])
            today = dt.date.today()
            age = today.year - born.year - ((today.month, today.day) < (born.month, born.day))
        except ValueError:
            pass
    return {
        "age": age,
        "gender": p.get("gender"),
        "weight_kg": p.get("weight_kg"),
        "height_cm": p.get("height_cm"),
        "lthr": p.get("lthr"),
        "vo2max_running": p.get("vo2max_running"),
        "updated": p.get("fetched_at"),
    }
