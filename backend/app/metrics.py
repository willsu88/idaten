"""Deterministic training metrics.

Everything the LLM should *not* be trusted to compute lives here: training load
aggregation (CTL/ATL/TSB via exponential decay) and the daily readiness score.
The planner and chat agent consume these as facts.
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Activity, DailyHealth, DayIntent

CTL_DAYS = 42.0  # chronic (fitness) time constant
ATL_DAYS = 7.0   # acute (fatigue) time constant

# Rough load-per-minute for manually declared other-sport days (no watch data)
INTENT_EFFORT_LOAD = {"easy": 0.5, "moderate": 0.9, "hard": 1.4}


def efficiency_factor(a: Activity) -> float | None:
    """EF = meters-per-minute / avg HR. Higher at the same HR = fitter."""
    if not a.avg_speed_mps or not a.avg_hr:
        return None
    return round((a.avg_speed_mps * 60) / a.avg_hr, 3)


def activity_load(a: Activity) -> float:
    """Prefer Garmin's own training load; fall back to a duration-based estimate."""
    if a.training_load:
        return float(a.training_load)
    if a.duration_s:
        return (a.duration_s / 60.0) * 1.0  # ~1 load point per minute of easy work
    return 0.0


@dataclass
class DayMetrics:
    date: dt.date
    load: float
    ctl: float
    atl: float
    tsb: float


def load_series(db: Session, user_id: int, start: dt.date, end: dt.date) -> list[DayMetrics]:
    """Daily load + CTL/ATL/TSB from `start` to `end` inclusive.

    Warms up the exponential averages from up to 90 days of history before
    `start` so early values aren't artificially low.
    """
    warmup_start = start - dt.timedelta(days=90)
    acts = db.scalars(
        select(Activity).where(Activity.user_id == user_id,
                               Activity.date >= warmup_start, Activity.date <= end)
    ).all()
    daily_load: dict[dt.date, float] = {}
    for a in acts:
        daily_load[a.date] = daily_load.get(a.date, 0.0) + activity_load(a)

    # Manually declared other-sport days with no recorded activity (e.g. freediving
    # without the watch) contribute an estimated load so fatigue isn't understated.
    today = dt.date.today()
    intents = db.scalars(
        select(DayIntent).where(DayIntent.user_id == user_id,
                                DayIntent.date >= warmup_start, DayIntent.date <= min(end, today))
    ).all()
    for intent in intents:
        if intent.date not in daily_load and intent.duration_min:
            factor = INTENT_EFFORT_LOAD.get(intent.effort or "moderate", 0.9)
            daily_load[intent.date] = intent.duration_min * factor

    ctl = atl = 0.0
    out: list[DayMetrics] = []
    d = warmup_start
    while d <= end:
        load = daily_load.get(d, 0.0)
        ctl += (load - ctl) / CTL_DAYS
        atl += (load - atl) / ATL_DAYS
        if d >= start:
            out.append(DayMetrics(date=d, load=load, ctl=ctl, atl=atl, tsb=ctl - atl))
        d += dt.timedelta(days=1)
    return out


def has_recovery_data(health: DailyHealth | None) -> bool:
    """True once last night's recovery signals have actually landed — not just an
    empty DailyHealth row created by a sync that ran before Garmin processed the
    night. Gates the daily review so it waits for real data, not a bare row."""
    return health is not None and (
        health.sleep_score is not None
        or health.sleep_seconds is not None
        or health.hrv is not None
    )


def readiness(db: Session, user_id: int, date: dt.date) -> dict | None:
    """Readiness score (0-100) + traffic-light level for a day.

    Weighted blend of: HRV deviation from baseline, sleep duration & score,
    body battery, and training stress balance. Missing components are skipped
    and weights renormalized, so partial data still yields a score.
    """
    health = db.get(DailyHealth, (user_id, date))
    has_activities = db.scalars(
        select(Activity).where(Activity.user_id == user_id).limit(1)
    ).first() is not None
    if health is None and not has_activities:
        return None  # nothing synced yet — no score is better than a fake one
    tsb = load_series(db, user_id, date, date)[0].tsb if has_activities else None

    hrv_delta_pct: float | None = None
    parts: list[tuple[float, float]] = []  # (weight, score 0-100)

    if health and health.hrv and health.hrv_baseline:
        hrv_delta_pct = (health.hrv - health.hrv_baseline) / health.hrv_baseline * 100
        # -20% or worse -> 0, at/above baseline -> 100
        parts.append((0.35, max(0.0, min(100.0, 100 + hrv_delta_pct * 5))))
    if health and health.sleep_seconds:
        hours = health.sleep_seconds / 3600
        parts.append((0.15, max(0.0, min(100.0, (hours / 7.5) * 100))))
    if health and health.sleep_score is not None:
        parts.append((0.15, float(health.sleep_score)))
    if health and health.body_battery is not None:
        parts.append((0.15, float(health.body_battery)))
    if tsb is not None:
        # tsb -25 (very fatigued) -> 0, +10 (fresh) -> 100
        parts.append((0.20, max(0.0, min(100.0, (tsb + 25) / 35 * 100))))

    if not parts:
        return None

    total_w = sum(w for w, _ in parts)
    score = round(sum(w * s for w, s in parts) / total_w)
    level = "green" if score >= 70 else "yellow" if score >= 45 else "red"
    return {
        "score": score,
        "level": level,
        "components": {
            "hrv_delta_pct": round(hrv_delta_pct, 1) if hrv_delta_pct is not None else None,
            "sleep_hours": round(health.sleep_seconds / 3600, 1) if health and health.sleep_seconds else None,
            "sleep_score": health.sleep_score if health else None,
            "body_battery": health.body_battery if health else None,
            "tsb": round(tsb, 1) if tsb is not None else None,
        },
    }


def structural_signals(days: list[dict]) -> dict:
    """Multi-day structure a greedy daily optimizer (like Garmin's DSW) can't see.

    `days` is an ordered list of {"date": ISO, "hard": bool, "rest": bool}. This
    is the deterministic core of Idaten's review layer: it surfaces hard-day
    clustering (the "three threshold sessions in a row" that started the project)
    and how much recovery sits between intensity days. The model reasons FROM
    these facts; it never has to count days itself.
    """
    ordered = sorted(days, key=lambda d: d["date"])
    hard = [dt.date.fromisoformat(d["date"]) for d in ordered if d.get("hard")]
    max_consec = cur = 0
    prev: dt.date | None = None
    for hd in hard:
        cur = cur + 1 if (prev is not None and (hd - prev).days == 1) else 1
        max_consec = max(max_consec, cur)
        prev = hd
    gaps = [(hard[i] - hard[i - 1]).days for i in range(1, len(hard))]
    return {
        "hard_day_count": len(hard),
        "max_consecutive_hard_days": max_consec,
        "min_gap_between_hard_days": min(gaps) if gaps else None,
        "hard_dates": [d.isoformat() for d in hard],
    }


# Menstrual-cycle phase boundaries. Guardrails keep a garbage anchor from
# producing nonsense; typical cycles are 21-35 days, we accept a wide band.
CYCLE_LEN_MIN, CYCLE_LEN_MAX, CYCLE_LEN_DEFAULT = 15, 60, 28
PERIOD_LEN_DEFAULT = 5
# Easing windows (Will's spec): the last N days before the predicted start and
# the first N days of flow are when the coach should dial intensity down.
PREMENSTRUAL_DAYS = 3   # 2-3 days before start
EARLY_FLOW_DAYS = 2     # first 1-2 days of the period


def cycle_phase(cycle: dict | None, date: dt.date) -> dict | None:
    """Where `date` sits in the athlete's menstrual cycle, from a set-once anchor.

    `cycle` is the per-user `cycle` setting: {enabled, last_start_date,
    cycle_length_days, period_length_days}. Pure arithmetic forward/backward
    projection from the anchor — no history, no cold start. Returns None when
    tracking is off or the anchor is missing/invalid, so callers can treat a
    None result as "no cycle signal for this athlete".

    The `ease_recommended` flag is the deterministic coaching signal: true in the
    2-3 days before the predicted start (late luteal / premenstrual) and the
    first 1-2 days of flow. The review LLM reasons from the whole dict; the flag
    is the fact it must not override.
    """
    if not cycle or not cycle.get("enabled"):
        return None
    anchor = cycle.get("last_start_date")
    try:
        last = dt.date.fromisoformat(anchor) if anchor else None
    except (ValueError, TypeError):
        last = None
    if last is None:
        return None

    length = int(cycle.get("cycle_length_days") or CYCLE_LEN_DEFAULT)
    if not (CYCLE_LEN_MIN <= length <= CYCLE_LEN_MAX):
        length = CYCLE_LEN_DEFAULT
    period = int(cycle.get("period_length_days") or PERIOD_LEN_DEFAULT)
    period = max(1, min(period, length - 1))

    delta = (date - last).days
    day_index = delta % length                       # 0-indexed within the cycle
    current_start = last + dt.timedelta(days=delta - day_index)
    next_start = current_start + dt.timedelta(days=length)
    days_to_next = (next_start - date).days           # 1..length

    if day_index < period:
        phase = "menstrual"
    elif days_to_next <= PREMENSTRUAL_DAYS:
        phase = "premenstrual"                        # late luteal
    elif day_index < round(length / 2):
        phase = "follicular"
    else:
        phase = "luteal"

    ease = phase == "premenstrual" or day_index < EARLY_FLOW_DAYS
    # A tight band around the predicted start (2 days before .. 1 day after) where
    # a one-tap "did it start today?" confirmation is offered to keep the open-loop
    # projection honest — the drift self-correction. Deliberately narrow so it is
    # never a monthly nag.
    in_drift_window = days_to_next <= 2 or day_index <= 1
    return {
        "phase": phase,
        "day_of_cycle": day_index + 1,                # 1-indexed for humans
        "cycle_length_days": length,
        "period_length_days": period,
        "days_to_next_period": days_to_next,
        "current_start_date": current_start.isoformat(),  # start of the cycle `date` sits in
        "next_period_date": next_start.isoformat(),
        "ease_recommended": ease,
        "in_drift_window": in_drift_window,
    }


def show_started_prompt(phase: dict | None, confirmed_start, snooze_date, today: dt.date) -> bool:
    """Whether to offer the one-tap "did your period start today?" confirm.

    Only inside the drift window, and NOT if the athlete already confirmed this
    cycle's start (`confirmed_start` == the current cycle start) or snoozed it
    today. This is what stops the prompt from nagging after a Yes / Not-yet."""
    if not phase or not phase.get("in_drift_window"):
        return False
    if confirmed_start == phase.get("current_start_date"):
        return False
    if snooze_date == today.isoformat():
        return False
    return True


def weekly_km(db: Session, user_id: int, today: dt.date, weeks: int = 4) -> list[float]:
    """Total km per trailing 7-day block, oldest -> newest."""
    out: list[float] = []
    for wk in range(weeks):
        start = today - dt.timedelta(days=7 * (wk + 1))
        end = today - dt.timedelta(days=7 * wk)
        acts = db.scalars(
            select(Activity).where(Activity.user_id == user_id,
                                   Activity.date > start, Activity.date <= end)
        ).all()
        out.append(round(sum((a.distance_m or 0) for a in acts) / 1000, 1))
    out.reverse()
    return out


# --- training-load ramp guardrail (macro/periodization, ROADMAP Idea E) ---------
#
# Rolling 7d/28d load ratio ("acute:chronic"), the too-much-too-soon early
# warning. Constants CALIBRATED on both live users' 300-day history (2026-07-21
# backtest): the raw daily ratio fired ~20% of days (noise + post-break
# restarts where chronic ~0), so a flag requires (a) a chronic FLOOR — below it
# the ratio is meaningless — and (b) the ratio to hold above threshold for
# PERSIST consecutive days. That yields ~5 episodes/10mo (Will) and 2
# (Julianne), all real ramps. Detraining ships as an exposed trend NUMBER (the
# -15%/21d rule alone flagged 83 days for Will — too chatty for a hard zone);
# the model reads it in context.

RAMP_FLOOR = 15.0        # min 28d chronic daily load for the ratio to mean anything
RAMP_CAUTION = 1.3       # zone edges for the 7/28 ratio
RAMP_HIGH = 1.5
RAMP_PERSIST_DAYS = 3    # days the ratio must hold above an edge to flag
DETRAIN_PCT = -15.0      # chronic change (vs 21d ago) the prompt treats as detraining

# Planned-day load estimate: minutes x intensity factor, mirroring
# activity_load's ~1 point/easy-minute. Validated against completed plan days'
# actual Garmin loads (spike 2026-07-21: within ~25% — fine for a band check).
PLANNED_LOAD_FACTORS = {
    "recovery": 0.8, "easy_run": 1.0, "long_run": 1.0, "cross_train": 0.9,
    "tempo": 1.5, "intervals": 1.7, "race": 2.0, "rest": 0.0,
}


def planned_day_load(day: dict) -> float:
    """Estimated training load of one planned day (dict shape of plan_day_dict)."""
    if day.get("workout_type") == "rest":
        return 0.0
    mins = day.get("duration_min") or (
        (day.get("distance_km") or 0) * 6.0)  # ~6 min/km rough easy pace
    return float(mins) * PLANNED_LOAD_FACTORS.get(day.get("workout_type"), 1.0)


def ramp_signal(db: Session, user_id: int, today: dt.date,
                planned_days: list[dict] | None = None) -> dict | None:
    """The block-altitude load-ramp signal for snapshots and the review.

    `zone` is the PERSISTED verdict (ratio held above an edge for
    RAMP_PERSIST_DAYS) — the deterministic flag the coach may act on. The
    chronic FLOOR gates it so a brand-new runner's near-zero base can't produce
    noise ratios — but the floor is WAIVED when the athlete held a real base
    any time in the last 90 days: a comeback after a month off (chronic decayed
    below the floor, then straight back to old volume) is exactly the risky
    ramp this exists to catch. `planned_next_week`, when planned days are
    provided, projects the ratio as if the athlete executes the upcoming plan —
    the forward-looking half no watch widget shows. None when there's no
    training history at all."""
    start = today - dt.timedelta(days=90)
    series = load_series(db, user_id, start, today)
    loads = {m.date: m.load for m in series}
    if not any(loads.values()):
        return None

    def rolling(d: dt.date, n: int) -> float:
        return sum(loads.get(d - dt.timedelta(days=i), 0.0) for i in range(n)) / n

    chronic = rolling(today, 28)
    acute = rolling(today, 7)
    ratio = round(acute / chronic, 2) if chronic > 0 else None

    # A real base held any time in the window waives the floor (comeback case).
    had_base = any(rolling(m.date, 28) >= RAMP_FLOOR for m in series
                   if m.date >= start + dt.timedelta(days=28))
    floor_ok = chronic >= RAMP_FLOOR or had_base

    # Persisted zone: today's edge only counts if held RAMP_PERSIST_DAYS.
    def held(edge: float) -> bool:
        for i in range(RAMP_PERSIST_DAYS):
            d = today - dt.timedelta(days=i)
            rc = rolling(d, 28)
            if not floor_ok or rc <= 0 or rolling(d, 7) / rc <= edge:
                return False
        return True

    zone = "high" if held(RAMP_HIGH) else "caution" if held(RAMP_CAUTION) else "safe"

    chronic_prev = rolling(today - dt.timedelta(days=21), 28)
    trend_pct = (round((chronic / chronic_prev - 1) * 100)
                 if chronic_prev > 0 and (chronic_prev >= RAMP_FLOOR or had_base)
                 else None)
    trend = None
    if trend_pct is not None:
        trend = ("detraining" if trend_pct <= DETRAIN_PCT
                 else "building" if trend_pct >= 5 else "flat")

    out = {
        "acwr_7d_28d": ratio,
        "zone": zone,
        "chronic_daily_load": round(chronic, 1),
        "acute_daily_load": round(acute, 1),
        "chronic_trend_pct_21d": trend_pct,
        "chronic_trend": trend,
        "chronic_floor_met": chronic >= RAMP_FLOOR,
        "had_recent_base": had_base,
    }

    if planned_days:
        week = [d for d in planned_days if d.get("date")][:7]
        planned_avg = sum(planned_day_load(d) for d in week) / 7.0
        projected = round(planned_avg / chronic, 2) if chronic > 0 else None
        p_zone = "safe"
        if projected is not None and floor_ok:
            p_zone = ("high" if projected > RAMP_HIGH
                      else "caution" if projected > RAMP_CAUTION else "safe")
        out["planned_next_week"] = {
            "avg_daily_load": round(planned_avg, 1),
            "acwr_if_executed": projected,
            "zone": p_zone,
        }
    return out


def ramp_series(db: Session, user_id: int, start: dt.date, end: dt.date) -> list[dict]:
    """Daily acute/chronic/ratio rows for the Trends ramp chart. Ratio is null
    where the chronic floor isn't met (a ratio on a near-zero base is noise)."""
    series = load_series(db, user_id, start - dt.timedelta(days=27), end)
    loads = [m.load for m in series]
    dates = [m.date for m in series]
    out: list[dict] = []
    # Prefix sums so each day's two windows are O(1).
    prefix = [0.0]
    for x in loads:
        prefix.append(prefix[-1] + x)

    def win(idx: int, n: int) -> float:
        lo = max(0, idx + 1 - n)
        return (prefix[idx + 1] - prefix[lo]) / n

    for i, d in enumerate(dates):
        if d < start:
            continue
        acute, chronic = win(i, 7), win(i, 28)
        out.append({
            "date": d.isoformat(),
            "acute": round(acute, 1),
            "chronic": round(chronic, 1),
            "ratio": round(acute / chronic, 2) if chronic >= RAMP_FLOOR else None,
        })
    return out


def training_monotony(db: Session, user_id: int, today: dt.date) -> float | None:
    """Foster training monotony: mean/SD of daily load over the last 7 days.

    ~2.0+ means the days all look alike (a variety/injury-risk signal even at
    moderate volume); healthy mixed weeks land around 1.0-1.5. None when there
    is no load or no day-to-day variation to measure.
    """
    series = load_series(db, user_id, today - dt.timedelta(days=6), today)
    loads = [m.load for m in series]
    mean = sum(loads) / len(loads)
    if mean <= 0:
        return None
    var = sum((x - mean) ** 2 for x in loads) / len(loads)
    sd = var ** 0.5
    return round(mean / sd, 2) if sd > 0 else None


# Daniels-Gilbert: VO2 cost of running at v m/min. Inverting it at a fraction
# of VDOT gives the classic E/M/T/I/R training paces (approximating Daniels'
# published tables; Garmin's vo2MaxRunning stands in for VDOT).
_PACE_FRACTIONS = {  # zone -> (low %VO2max, high %VO2max) = (slower, faster) bound
    "E": (0.62, 0.72),
    "M": (0.80, 0.86),
    "T": (0.86, 0.90),
    "I": (0.95, 1.00),
    "R": (1.05, 1.10),
}


def _velocity_for_vo2(vo2: float) -> float:
    """Solve -4.60 + 0.182258 v + 0.000104 v^2 = vo2 for v (m/min)."""
    a, b, c = 0.000104, 0.182258, -(4.60 + vo2)
    return (-b + (b * b - 4 * a * c) ** 0.5) / (2 * a)


def training_paces(vdot: float | None) -> dict[str, list[str]] | None:
    """{"E": ["6:23", "5:42"], ...} min/km bands (slow, fast) from VDOT/VO2max."""
    if not vdot or vdot <= 0:
        return None
    out: dict[str, list[str]] = {}
    for zone, (lo, hi) in _PACE_FRACTIONS.items():
        band = []
        for frac in (lo, hi):
            v = _velocity_for_vo2(vdot * frac)  # m/min
            band.append(pace_str(v / 60.0))
        out[zone] = band
    return out


# Running zones as % of lactate threshold HR (Friel-style). LTHR comes from the
# athlete's Garmin profile and anchors the HR targets used by hr/hybrid modes.
LTHR_ZONE_PCT = {
    "z1": (0.70, 0.85),
    "z2": (0.85, 0.89),
    "z3": (0.90, 0.94),
    "z4": (0.95, 0.99),
    "z5": (1.00, 1.06),
}


def hr_zones_from_lthr(lthr: float | None) -> dict[str, list[int]] | None:
    """{"z1": [low_bpm, high_bpm], ...} or None when LTHR is unknown."""
    if not lthr or lthr <= 0:
        return None
    return {z: [round(lthr * lo), round(lthr * hi)] for z, (lo, hi) in LTHR_ZONE_PCT.items()}


def hr_zones_from_garmin(payload: list | None) -> dict[str, list[int]] | None:
    """{"z1": [low, high], ...} from a get_activity_hr_in_timezones payload.

    Garmin returns each zone's lower bound (`zoneLowBoundary`) tuned to the
    athlete's own profile - the SAME basis its coach scores against - so this is
    a far better band source than Friel-from-LTHR (whose LTHR value is often a
    stale max-HR). The top zone is open-ended; cap it generously. None if the
    payload lacks boundaries.
    """
    lows: dict[int, int] = {}
    for z in payload or []:
        n, lo = z.get("zoneNumber"), z.get("zoneLowBoundary")
        if n and lo is not None:
            lows[int(n)] = int(lo)
    if not lows:
        return None
    out: dict[str, list[int]] = {}
    for n in range(1, 6):
        lo = lows.get(n)
        if lo is None:
            continue
        out[f"z{n}"] = [lo, lows.get(n + 1, lo + 20)]  # top zone: open -> +20 bpm
    return out or None


def pace_str(speed_mps: float | None) -> str | None:
    """m/s -> 'M:SS' min/km."""
    if not speed_mps or speed_mps <= 0:
        return None
    sec_per_km = 1000.0 / speed_mps
    return f"{int(sec_per_km // 60)}:{int(sec_per_km % 60):02d}"


def pace_to_mps(pace: str) -> float | None:
    """'M:SS' min/km -> m/s."""
    try:
        m, s = pace.strip().split(":")
        sec = int(m) * 60 + int(s)
        return 1000.0 / sec if sec > 0 else None
    except (ValueError, AttributeError):
        return None


def pace_seconds(pace: str | None) -> int | None:
    """'M:SS' min/km -> seconds per km."""
    try:
        m, s = pace.strip().split(":")
        return int(m) * 60 + int(s)
    except (ValueError, AttributeError):
        return None


def pace_profile(db: Session, user_id: int, today: dt.date) -> dict | None:
    """Observed whole-run average paces from the last 90 days of real runs.

    The code-computed anchor for every prescribed pace: the planner and chat
    agent must ground targets in what the athlete actually runs, never in
    VDOT-table guesses. None until at least 3 qualifying runs (>= 2 km) exist.
    """
    start = today - dt.timedelta(days=90)
    runs = db.scalars(
        select(Activity).where(Activity.user_id == user_id,
                               Activity.date >= start,
                               Activity.type.contains("running"),
                               Activity.distance_m >= 2000,
                               Activity.duration_s > 0)
    ).all()
    # sec/km per run; discard GPS junk outside a 2:30-15:00 min/km window
    paces = sorted(
        p for a in runs
        if (p := a.duration_s / (a.distance_m / 1000)) and 150 <= p <= 900
    )
    if len(paces) < 3:
        return None

    def fmt(sec: float) -> str:
        return f"{int(sec // 60)}:{int(sec % 60):02d}"

    median = paces[len(paces) // 2]
    return {
        "runs_last_90d": len(paces),
        "typical_pace": fmt(median),        # median whole-run average, min/km
        "fastest_avg_pace": fmt(paces[0]),  # best whole-run average
        "slowest_avg_pace": fmt(paces[-1]),
        "typical_pace_s": round(median),
        "fastest_avg_pace_s": round(paces[0]),
    }


# ---------------------------------------------------------------------------
# Race prediction from DEMONSTRATED performance (Idaten's own model).
#
# Garmin's race predictor is a VO2max ceiling that runs optimistic for
# recreational runners. Idaten instead predicts from what the athlete has
# actually run: it derives a VDOT (Daniels) from recent hard efforts, projects a
# race time at the target distance, applies a per-user calibration factor, and
# emits a range whose width reflects how much/how recent the anchoring data is.
# Garmin's number is kept only as a reference (see races.race_prediction_block).
# ---------------------------------------------------------------------------

# Daniels-Gilbert: fraction of VDOT sustainable for a race of `t_min` minutes,
# and the VO2 cost of running at `v` m/min (the same cost curve `_velocity_for_vo2`
# inverts for training paces). VDOT = VO2(v) / %max(t).
def _daniels_pct_max(t_min: float) -> float:
    return (0.8 + 0.1894393 * math.exp(-0.012778 * t_min)
            + 0.2989558 * math.exp(-0.1932605 * t_min))


def _vo2_cost(v_m_min: float) -> float:
    return -4.60 + 0.182258 * v_m_min + 0.000104 * v_m_min ** 2


def vdot_from_performance(distance_m: float | None, time_s: float | None) -> float | None:
    """VDOT implied by covering `distance_m` in `time_s` (a Daniels race point)."""
    if not distance_m or not time_s or distance_m <= 0 or time_s <= 0:
        return None
    v = distance_m / (time_s / 60.0)      # m/min
    pct = _daniels_pct_max(time_s / 60.0)
    if pct <= 0:
        return None
    vdot = _vo2_cost(v) / pct
    return vdot if vdot > 0 else None


def race_time_for_vdot(vdot: float | None, distance_km: float | None) -> float | None:
    """Invert: predicted race time (s) at `distance_km` for a given VDOT.

    VDOT decreases monotonically with time (a longer time = slower = less fit),
    so a bisection on time converges cleanly.
    """
    if not vdot or vdot <= 0 or not distance_km or distance_km <= 0:
        return None
    d_m = distance_km * 1000
    lo, hi = 60.0, 6 * 3600.0  # 1 min .. 6 h
    for _ in range(60):
        mid = (lo + hi) / 2
        v = vdot_from_performance(d_m, mid)
        if v is None or v > vdot:
            lo = mid       # too fast for this VDOT -> need more time
        else:
            hi = mid
    return round((lo + hi) / 2)


# Demonstrated-anchor window and gates. 8 weeks keeps the fitness estimate
# current; the distance floor drops warmup jogs/strides that would distort VDOT.
#
# VDOT-from-a-run is only a valid RACE-fitness proxy for efforts run at genuine
# race-representative intensity — an easy run's whole-run-average pace badly
# understates race fitness. So when HR + threshold are known we gate candidates
# to hard efforts (>= HARD_HR_FRAC x LTHR: tempo/threshold/race). When they are
# not, we fall back to a high percentile over all qualifying runs and cap
# confidence, accepting a coarser estimate.
DEMO_WINDOW_DAYS = 56
DEMO_MIN_DIST_M = 3000
DEMO_MIN_EFFORTS = 2
DEMO_HARD_PCTL = 0.85     # over hard efforts: 2nd-ish best, robust to one flier
DEMO_COARSE_PCTL = 0.95   # over all runs (no HR gate): near-max to fight easy-run drag
DEMO_COARSE_MIN = 3
HARD_HR_FRAC = 0.88       # avg HR >= 88% of LTHR ~ tempo effort or harder


def _percentile(sorted_vals: list[float], p: float) -> float | None:
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    idx = p * (len(sorted_vals) - 1)
    lo = int(idx)
    frac = idx - lo
    if lo + 1 < len(sorted_vals):
        return sorted_vals[lo] + frac * (sorted_vals[lo + 1] - sorted_vals[lo])
    return sorted_vals[lo]


def demonstrated_anchor(db: Session, user_id: int, asof: dt.date,
                        lthr: float | None = None) -> dict | None:
    """Athlete's demonstrated race fitness as of `asof`, or None if too sparse.

    Window is the DEMO_WINDOW_DAYS ending at `asof` (inclusive). Returns
    {fitness_vdot, best, efforts[], n_efforts, most_recent_days, quality}. When
    LTHR is known, `fitness_vdot` is the 85th-percentile VDOT over HARD efforts
    (avg HR >= HARD_HR_FRAC x LTHR) whose average pace is a valid race proxy —
    `quality: "hard"`. Otherwise it's the 95th-percentile over all qualifying
    runs (`quality: "coarse"`), which the caller treats with lower confidence.
    None when too few efforts exist, so the caller falls back to Garmin.
    Calibration passes an `asof` before a race day to measure it against training
    fitness, not the race itself.
    """
    start = asof - dt.timedelta(days=DEMO_WINDOW_DAYS)
    runs = db.scalars(
        select(Activity).where(Activity.user_id == user_id,
                               Activity.date >= start,
                               Activity.date <= asof,
                               Activity.type.contains("running"),
                               Activity.distance_m >= DEMO_MIN_DIST_M,
                               Activity.duration_s > 0)
    ).all()
    efforts = []
    for a in runs:
        pace = a.duration_s / (a.distance_m / 1000)   # s/km
        if not (150 <= pace <= 900):                  # discard GPS junk
            continue
        vdot = vdot_from_performance(a.distance_m, a.duration_s)
        if not vdot:
            continue
        hard = bool(lthr and a.avg_hr and a.avg_hr >= HARD_HR_FRAC * lthr)
        efforts.append({
            "distance_km": round(a.distance_m / 1000, 2),
            "time_s": round(a.duration_s),
            "vdot": round(vdot, 1),
            "days_ago": (asof - a.date).days,
            "hard": hard,
        })

    hard = [e for e in efforts if e["hard"]]
    if lthr and len(hard) >= DEMO_MIN_EFFORTS:
        pool, pctl, quality = hard, DEMO_HARD_PCTL, "hard"
    elif len(efforts) >= DEMO_COARSE_MIN:
        pool, pctl, quality = efforts, DEMO_COARSE_PCTL, "coarse"
    else:
        return None

    fitness = _percentile(sorted(e["vdot"] for e in pool), pctl)
    best = max(pool, key=lambda e: e["vdot"])
    return {
        "fitness_vdot": round(fitness, 1),
        "best": best,
        "efforts": pool,
        "n_efforts": len(pool),
        "most_recent_days": min(e["days_ago"] for e in pool),
        "quality": quality,
    }


# Symmetric half-width (fraction of the point estimate) per confidence tier.
# More real race results -> tighter range and higher confidence.
RANGE_BASE = {"high": 0.04, "medium": 0.06, "low": 0.08}


def _round5(x: float) -> int:
    return int(round(x / 5.0) * 5)


def prediction_confidence(n_samples: int) -> str:
    """Confidence in the calibrated number, from how many real races have tuned it."""
    if n_samples >= 3:
        return "high"
    if n_samples >= 1:
        return "medium"
    return "low"


def race_prediction(garmin_time_s: float | None, k: float, n_samples: int) -> dict:
    """Idaten's race prediction: Garmin's physiological estimate corrected by the
    athlete's own optimism factor `k` (learned from real race results).

    Returns {source, likely_s, low_s, high_s, confidence}. `source` is "garmin"
    until at least one real race has calibrated `k` (we're just showing Garmin's
    number, honestly labelled), then "idaten" (it's our corrected number). We do
    NOT try to out-model Garmin's physiology from training runs — only genuine
    race performances are trustworthy, and those flow in through calibration.
    """
    if not garmin_time_s:
        return {"source": "garmin", "likely_s": None, "low_s": None,
                "high_s": None, "confidence": None}
    likely = garmin_time_s * k
    conf = prediction_confidence(n_samples)
    hw = RANGE_BASE[conf]
    return {
        "source": "idaten" if n_samples >= 1 else "garmin",
        "likely_s": round(likely),
        "low_s": _round5(likely * (1 - hw)),
        "high_s": _round5(likely * (1 + hw)),
        "confidence": conf,
    }


# ---------------------------------------------------------------------------
# Execution score — how well a run matched the workout it was attempting.
#
# Mirrors Garmin's directWorkoutComplianceScore (reverse-engineered 2026-07-19):
# a time-integrated measure of how close the athlete's actual HR/pace sat to the
# prescribed target band, per step, aggregated over the WHOLE prescribed
# duration. Completion + structure + intensity fall out of one integral: time
# spent outside the band (too easy OR too hard) and time not run at all (bailed
# early) both earn zero credit. Used only for runs that were an attempt at a
# planned workout; a free run is never scored.
# ---------------------------------------------------------------------------

# Tolerance beyond a target band before credit reaches zero. HR is absolute
# (bpm); pace tolerance scales with the band (fraction of its midpoint speed).
# Calibrated 2026-07-19 against William's real runs vs Garmin's own
# directWorkoutComplianceScore (using Garmin's per-athlete zone boundaries as the
# band basis): tol 10 bpm gives MAE ~9 with correct ordering. Residual error is
# irreducible heuristic slack - Garmin's exact per-workout targets are hidden.
EXEC_TOL_HR = 10.0
EXEC_TOL_SPEED_FRAC = 0.10

# trainingEffectLabel (the day's intent) -> the HR zone the WORK steps target.
_TE_WORK_ZONE = {
    "RECOVERY": "z1",
    "AEROBIC_BASE": "z2",
    "BASE": "z2",
    "TEMPO": "z3",
    "LACTATE_THRESHOLD": "z4",
    "THRESHOLD": "z4",
    "VO2MAX": "z5",
    "SPEED": "z5",
    "ANAEROBIC": "z5",
}
# Non-work lap intensities always target the easy zone regardless of the label.
_EASY_INTENSITIES = {"WARMUP", "COOLDOWN", "REST", "RECOVERY"}


def derive_hr_band(intensity_type: str | None, te_label: str | None,
                   hr_zones: dict | None) -> list[int] | None:
    """Target HR band [low, high] for one lap when Garmin hides the real one.

    Used for coach runs on watches that don't emit a compliance score: the lap's
    own intensityType (WARMUP/INTERVAL/COOLDOWN) plus the day's trainingEffect
    label map to one of the athlete's own HR zones. Warmups/cooldowns/rests are
    always the easy zone; work steps take the zone implied by the day's intent.
    """
    if not hr_zones:
        return None
    it = (intensity_type or "").upper()
    lbl = (te_label or "").upper()
    # Recovery INTENT (the day's label, or an in-workout recovery jog) is a broad
    # easy effort that legitimately sits anywhere in z1-z2 - a single narrow zone
    # under-scores it (Garmin marks low-z2 compliant on a recovery day).
    if lbl == "RECOVERY" or it == "RECOVERY":
        z1, z2 = hr_zones.get("z1"), hr_zones.get("z2")
        lo = (z1 or z2 or [None])[0]
        hi = (z2 or z1 or [None, None])[1]
        return [int(lo), int(hi)] if lo is not None and hi is not None else None
    # Warmups/cooldowns/rests target the easy zone; work steps take the zone the
    # day's training-effect label implies.
    zone = "z1" if it in _EASY_INTENSITIES else _TE_WORK_ZONE.get(lbl, "z2")
    band = hr_zones.get(zone)
    return [int(band[0]), int(band[1])] if band else None


EXEC_LOW = 50   # below this an execution score reads as notably off-target


def execution_signals(db: Session, user_id: int, today: dt.date, n: int = 6) -> dict | None:
    """Recent workout-execution history for the daily review to reason from.

    A deterministic summary of the last `n` SCORED runs: how well the athlete has
    been hitting prescribed intensities lately. A run of low scores means they are
    repeatedly missing the target (fatigue, or an over-ambitious plan) → the review
    should lean toward easing; consistently high means they're executing well and
    can progress. None until at least one scored run exists.
    """
    runs = db.scalars(
        select(Activity).where(Activity.user_id == user_id,
                               Activity.date <= today,
                               Activity.execution_score.is_not(None))
        .order_by(Activity.date.desc()).limit(n)
    ).all()
    if not runs:
        return None
    recent = [{"date": a.date.isoformat(), "score": a.execution_score,
               "source": a.execution_score_source, "type": a.type} for a in runs]
    vals = [a.execution_score for a in runs]
    # consecutive most-recent runs scoring below EXEC_LOW
    low_streak = 0
    for v in vals:
        if v < EXEC_LOW:
            low_streak += 1
        else:
            break
    return {
        "recent": recent,                       # newest first
        "count": len(vals),
        "avg_score": round(sum(vals) / len(vals)),
        "low_streak": low_streak,
    }


def _band_credit(value: float | None, low: float, high: float, tol: float) -> float | None:
    """1.0 inside [low, high]; linear decay to 0 across `tol` beyond each edge.

    Symmetric: running too hard is penalised the same as too easy. None when the
    sample has no value (sensor dropout) so the caller can skip it.
    """
    if value is None or tol <= 0:
        return None
    if value < low:
        d = low - value
    elif value > high:
        d = value - high
    else:
        return 1.0
    return max(0.0, 1.0 - d / tol)


def execution_score(series: dict | None, segments: list[dict], *,
                    tol_hr: float = EXEC_TOL_HR,
                    tol_speed_frac: float = EXEC_TOL_SPEED_FRAC) -> dict | None:
    """Score a run against its prescription. 0-100, or None if unscoreable.

    `series`  columnar actuals: {"t_s": [...], "hr": [...], "speed_mps": [...]}.
    `segments` ordered prescription steps, each:
        {"axis": "hr"|"pace", "low": float, "high": float,
         "duration_s": float, "label": str}
      HR band in bpm; pace band in m/s (matches series speed_mps, higher = faster
      = more intense, so under/over-shoot are symmetric with HR).

    Aligned to the series by elapsed time. The denominator is the PRESCRIBED
    total duration, so time run outside the band and time not run at all (bailed
    early) both drag the score down. Returns {"score", "breakdown"[per-segment]}.
    """
    if not series or not segments:
        return None
    t = series.get("t_s")
    if not t or len(t) < 2:
        return None
    total = sum((s.get("duration_s") or 0) for s in segments)
    if total <= 0:
        return None

    hr = series.get("hr")
    sp = series.get("speed_mps")
    if any(s.get("axis") == "hr" for s in segments) and not hr:
        return None
    if any(s.get("axis") == "pace" for s in segments) and not sp:
        return None

    # Cumulative [start, end) boundary for each segment on the prescribed clock.
    bounds, acc = [], 0.0
    for s in segments:
        start = acc
        acc += (s.get("duration_s") or 0)
        bounds.append((start, acc))

    seg_num = [0.0] * len(segments)   # integral of credit * time
    seg_sum = [0.0] * len(segments)   # sum of actual values (for avg)
    seg_cnt = [0] * len(segments)
    n = len(t)
    for i in range(n):
        ti = t[i]
        if ti >= total:
            break
        # active segment for this sample
        si = next((k for k, (a, b) in enumerate(bounds) if a <= ti < b), None)
        if si is None:
            continue
        seg = segments[si]
        # time this sample stands for, clipped to the segment and the total
        t_next = t[i + 1] if i + 1 < n else ti
        w = min(t_next, total, bounds[si][1]) - ti
        if w <= 0:
            continue
        if seg.get("axis") == "hr":
            val = hr[i] if hr and i < len(hr) else None
            tol = tol_hr
        else:
            val = sp[i] if sp and i < len(sp) else None
            mid = (seg["low"] + seg["high"]) / 2.0
            tol = tol_speed_frac * mid
        credit = _band_credit(val, seg["low"], seg["high"], tol)
        if credit is None:
            continue  # sensor dropout: counts as uncovered (denominator is total)
        seg_num[si] += credit * w
        seg_sum[si] += val
        seg_cnt[si] += 1

    breakdown = []
    for k, seg in enumerate(segments):
        dur = seg.get("duration_s") or 0
        breakdown.append({
            "label": seg.get("label"),
            "axis": seg.get("axis"),
            "target": [seg.get("low"), seg.get("high")],
            "duration_s": dur,
            "avg_actual": round(seg_sum[k] / seg_cnt[k], 1) if seg_cnt[k] else None,
            "score": round(100 * seg_num[k] / dur) if dur else None,
        })
    return {
        "score": round(100 * sum(seg_num) / total),
        "breakdown": breakdown,
    }
