"""Shared workouts between household members (ADR 0022).

The snapshot half freezes what crosses the tenant boundary at send time; the
adapt half is the deterministic de-personalize/re-personalize round trip:
HR bounds map by position within the sender's frozen zones into the
recipient's zones, pace bounds map at equal %vVO2max between the two VDOTs.
Everything here is pure over (payload, recipient params) so it unit-tests in
layer 1; the endpoints in api.py own all I/O.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy.orm import Session

from . import metrics, settings_store
from .models import PlanDay, SharedWorkout, User

# The projection of a PlanDay that crosses the boundary. rationale is absent on
# purpose: it is written against the sender's private readiness context. A field
# added to PlanDay later stays private until listed here.
_WORKOUT_FIELDS = (
    "workout_type", "title", "description", "duration_min", "distance_km",
    "target_pace", "target_hr_low", "target_hr_high", "steps",
)

# Shareable = a run the recipient could actually go run. Mirrors
# planner.RUN_TYPES_PLAN (imported lazily below to keep this module light).
_ZONE_KEYS = tuple(f"z{i}" for i in range(1, 6))


def build_payload(db: Session, sender: User, day: PlanDay) -> dict:
    """The send-time snapshot: workout projection + sender's fitness params."""
    return {
        "workout": {f: getattr(day, f) for f in _WORKOUT_FIELDS},
        "sender": {
            "display_name": sender.display_name or sender.username,
            "hr_zones": settings_store.hr_zones(db, sender.id),
            "vdot": settings_store.athlete_auto(db, sender.id).get("vo2max_running"),
        },
    }


def recipient_params(db: Session, user_id: int, today: dt.date) -> dict:
    """Everything adaptation needs about the accepting athlete, in one dict."""
    return {
        "hr_zones": settings_store.hr_zones(db, user_id),
        "vdot": settings_store.athlete_auto(db, user_id).get("vo2max_running"),
        "pace_profile": metrics.pace_profile(db, user_id, today),
        "training_mode": settings_store.get_settings(db, user_id)["training_mode"],
    }


def share_dict(s: SharedWorkout, adapted: dict | None, reason: str | None,
               conflict: dict | None) -> dict:
    return {
        "id": s.id,
        "from": (s.payload.get("sender") or {}).get("display_name") or "A member",
        "created_at": s.created_at.isoformat(),
        "date": s.date.isoformat(),
        "workout": s.payload.get("workout") or {},
        "adapted": adapted,
        "adapt_unavailable_reason": reason,
        "conflict": conflict,
    }


# --- adaptation ------------------------------------------------------------------

def _complete_zones(zones: dict | None) -> bool:
    return bool(zones) and all(
        isinstance(zones.get(z), (list, tuple)) and len(zones[z]) == 2
        for z in _ZONE_KEYS)


def _targets_present(workout: dict) -> tuple[bool, bool]:
    """(any pace target, any HR target) across the day and every step."""
    has_pace = bool(workout.get("target_pace"))
    has_hr = bool(workout.get("target_hr_low") and workout.get("target_hr_high"))
    for block in workout.get("steps") or []:
        for s in block.get("steps") or []:
            has_pace = has_pace or bool(s.get("target_pace"))
            has_hr = has_hr or bool(s.get("target_hr_low") and s.get("target_hr_high"))
    return has_pace, has_hr


def adapt_unavailable_reason(payload: dict, params: dict) -> str | None:
    """Why "accept with my zones" cannot be offered, or None when it can.

    The rule is: never guess a translation. Each target type present in the
    workout needs its parameters on BOTH sides.
    """
    workout = payload.get("workout") or {}
    sender = payload.get("sender") or {}
    has_pace, has_hr = _targets_present(workout)
    if has_pace and not (sender.get("vdot") and params.get("vdot")):
        whose = "your" if sender.get("vdot") else "the sender's"
        return (f"pace targets can't be translated without {whose} running "
                "VO2max from Garmin")
    if has_pace and params.get("training_mode") == "hr" \
            and not _complete_zones(params.get("hr_zones")):
        return ("your training mode is heart-rate but your HR zones aren't "
                "known yet - connect Garmin and sync a run")
    if has_hr and not _complete_zones(sender.get("hr_zones")):
        return "heart-rate targets can't be translated without the sender's HR zones"
    if has_hr and not _complete_zones(params.get("hr_zones")):
        return ("heart-rate targets can't be translated without your HR zones - "
                "connect Garmin and sync a run")
    return None


def _map_hr_bound(bpm: int, src: dict, dst: dict) -> int:
    """One HR bound -> the same relative position in the recipient's zones.

    Position = which zone + fraction within it. Outside the sender's zone span
    the bound clamps to the span edge first; inside a boundary gap (LTHR-derived
    zones aren't perfectly contiguous) it snaps to the nearer zone edge.
    """
    lo_all, hi_all = src["z1"][0], src["z5"][1]
    b = min(max(bpm, lo_all), hi_all)
    for z in _ZONE_KEYS:
        z_lo, z_hi = src[z]
        if z_lo <= b <= z_hi:
            frac = (b - z_lo) / (z_hi - z_lo) if z_hi > z_lo else 0.0
            d_lo, d_hi = dst[z]
            return round(d_lo + frac * (d_hi - d_lo))
    # Gap between zones: snap to whichever neighboring edge is closer.
    nearest = min(
        ((z, edge) for z in _ZONE_KEYS for edge in (0, 1)),
        key=lambda ze: abs(src[ze[0]][ze[1]] - b))
    return dst[nearest[0]][nearest[1]]


def _map_hr_band(low, high, src: dict, dst: dict, quality: bool) -> tuple:
    if not low or not high:
        return low, high
    mapped = sorted((_map_hr_bound(int(low), src, dst),
                     _map_hr_bound(int(high), src, dst)))
    return metrics.ensure_hr_band(mapped[0], mapped[1], dst, quality)


def _sec_to_pace(sec: float) -> str:
    sec = max(1, round(sec))
    return f"{int(sec // 60)}:{int(sec % 60):02d}"


def _pace_frac(sec_per_km: float, vdot: float) -> float:
    """A pace as the fraction of `vdot` it costs (the Daniels %vVO2max)."""
    v_m_min = 60000.0 / sec_per_km
    return metrics._vo2_cost(v_m_min) / vdot


def _map_pace_sec(sec_per_km: float, src_vdot: float, dst_vdot: float) -> float:
    """One pace bound -> the recipient's pace at the same %vVO2max."""
    frac = _pace_frac(sec_per_km, src_vdot)
    v = metrics._velocity_for_vo2(dst_vdot * frac)  # m/min
    return 60000.0 / v


def _map_pace(pace: str | None, src_vdot: float, dst_vdot: float) -> str | None:
    parts = metrics._pace_parts(pace)
    if not parts:
        return None  # unreadable = no target (ADR 0020's reader contract)
    secs = [int(p.split(":")[0]) * 60 + int(p.split(":")[1]) for p in parts]
    mapped = sorted((_map_pace_sec(s, src_vdot, dst_vdot) for s in secs),
                    reverse=True)  # slower bound first, the band convention
    if len(mapped) == 1:
        return _sec_to_pace(mapped[0])
    return f"{_sec_to_pace(mapped[0])}-{_sec_to_pace(mapped[1])}"


def _pace_to_zone_band(pace: str, src_vdot: float, zones: dict,
                       quality: bool) -> tuple:
    """A pace target -> the recipient's equivalent HR zone band (hr mode).

    The intensity family comes from the pace's %vVO2max against the SENDER's
    VDOT (the frame the pace was written in), using the same zone families the
    planner prompt prescribes: easy z1-z2, threshold/tempo z3-z4, hard z4-z5.
    """
    sec = metrics.pace_seconds(pace)
    frac = _pace_frac(sec, src_vdot)
    if frac <= metrics._PACE_FRACTIONS["E"][1]:        # easy effort
        z_lo, z_hi = "z1", "z2"
    elif frac <= metrics._PACE_FRACTIONS["T"][1]:      # marathon..threshold
        z_lo, z_hi = "z3", "z4"
    else:                                              # interval and up
        z_lo, z_hi = "z4", "z5"
    return metrics.ensure_hr_band(zones[z_lo][0], zones[z_hi][1], zones, quality)


def _ground_pace(pace: str | None, workout_type: str,
                 profile: dict | None) -> str | None:
    """Shift a day-level pace band that outruns the recipient's observed paces.

    Same floors as planner.pace_violations, applied as a repair rather than a
    retry (there is no model in this loop to retry): easy-type days land on the
    typical whole-run pace, quality days on the fastest recent average. The
    band keeps its width; only its midpoint moves (slower).
    """
    from .planner import EASY_TYPES

    parts = metrics._pace_parts(pace)
    if not parts or not profile:
        return pace
    mid = metrics.pace_seconds(pace)
    if workout_type in EASY_TYPES:
        floor = profile["typical_pace_s"]
    elif mid >= profile["fastest_avg_pace_s"] * 0.90:
        return pace
    else:
        floor = round(profile["fastest_avg_pace_s"] * 0.90)
    if workout_type in EASY_TYPES and mid >= floor * 0.93:
        return pace
    shift = floor - mid
    secs = sorted((int(p.split(":")[0]) * 60 + int(p.split(":")[1]) + shift
                   for p in parts), reverse=True)
    return "-".join(_sec_to_pace(s) for s in secs)


def adapt_workout(payload: dict, params: dict) -> dict | None:
    """The workout with every target translated to the recipient, or None when
    adaptation is unavailable (see adapt_unavailable_reason for why).

    Structure (steps, repeats, durations, distances, terrain) passes through
    untouched; only targets change. The output honors the same invariants the
    planner enforces: band grammar (ADR 0020), real HR ranges (ADR 0017), no
    uphill pace (ADR 0021).
    """
    from .planner import QUALITY_TYPES, _drop_uphill_pace

    if adapt_unavailable_reason(payload, params) is not None:
        return None
    workout = payload["workout"]
    sender = payload["sender"]
    wt = workout.get("workout_type")
    quality = wt in QUALITY_TYPES
    src_zones, dst_zones = sender.get("hr_zones"), params.get("hr_zones")
    src_vdot, dst_vdot = sender.get("vdot"), params.get("vdot")
    to_hr = params.get("training_mode") == "hr"

    def convert(target: dict, step_quality: bool) -> dict:
        out = dict(target)
        pace = out.get("target_pace")
        low, high = out.get("target_hr_low"), out.get("target_hr_high")
        if low and high:
            low, high = _map_hr_band(low, high, src_zones, dst_zones, step_quality)
            out["target_hr_low"], out["target_hr_high"] = low, high
        if pace:
            if to_hr:
                band = _pace_to_zone_band(pace, src_vdot, dst_zones, step_quality)
                out["target_pace"] = None
                # A pace step carries no HR of its own (never both); the zone
                # band becomes its target.
                out["target_hr_low"], out["target_hr_high"] = band
            else:
                out["target_pace"] = _map_pace(pace, src_vdot, dst_vdot)
        return out

    adapted = convert(workout, quality)
    if adapted.get("steps"):
        adapted["steps"] = [
            {**block, "steps": [
                convert(s, quality and s.get("kind") == "work")
                for s in (block.get("steps") or [])
            ]}
            for block in adapted["steps"]
        ]
    if not to_hr:
        adapted["target_pace"] = _ground_pace(
            adapted.get("target_pace"), wt, params.get("pace_profile"))
    return _drop_uphill_pace(adapted)
