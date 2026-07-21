"""Unit tests for the execution-score core (metrics.execution_score / helpers).

These are pure-function tests: no DB, no Garmin. They pin the behaviour the
design promises - band closeness, symmetric over/under-shoot, completion falling
out of the integral, and target derivation for coach runs.
"""
from __future__ import annotations

from app import metrics
from app.metrics import _band_credit, derive_hr_band, execution_score


def steady_series(value: float, duration_s: float, *, channel: str = "hr",
                  step: float = 10.0) -> dict:
    """A flat series holding `value` on `channel` for `duration_s`."""
    n = int(duration_s // step) + 1
    t = [i * step for i in range(n)]
    return {"t_s": t, channel: [value] * n}


# --- _band_credit ---------------------------------------------------------

def test_credit_inside_band_is_full():
    assert _band_credit(150, 145, 155, 12) == 1.0


def test_credit_decays_linearly_below_and_symmetric_above():
    # 6 bpm under the low edge, tol 12 -> half credit; same 6 over the high edge.
    assert _band_credit(139, 145, 155, 12) == 0.5
    assert _band_credit(161, 145, 155, 12) == 0.5


def test_credit_floors_at_zero_far_outside():
    assert _band_credit(100, 145, 155, 12) == 0.0
    assert _band_credit(200, 145, 155, 12) == 0.0


def test_credit_none_when_value_missing():
    assert _band_credit(None, 145, 155, 12) is None


# --- execution_score: single easy segment --------------------------------

def test_perfect_run_scores_100():
    seg = [{"axis": "hr", "low": 145, "high": 155, "duration_s": 600, "label": "easy"}]
    out = execution_score(steady_series(150, 600), seg)
    assert out["score"] == 100
    assert out["breakdown"][0]["avg_actual"] == 150


def test_run_too_easy_scores_low():
    # HR 125 vs a 145-155 band: 20 under, tol 12 -> credit 0 the whole time.
    seg = [{"axis": "hr", "low": 145, "high": 155, "duration_s": 600, "label": "easy"}]
    assert execution_score(steady_series(125, 600), seg)["score"] == 0


def test_run_slightly_off_scores_partial():
    # 6 bpm under the low edge, default tol 10 -> 0.4 credit -> ~40.
    seg = [{"axis": "hr", "low": 145, "high": 155, "duration_s": 600, "label": "easy"}]
    assert execution_score(steady_series(139, 600), seg)["score"] == 40


# --- completion falls out of the integral --------------------------------

def test_bailing_early_caps_the_score():
    # Ran perfectly but only for half the prescribed 600s -> ~50.
    seg = [{"axis": "hr", "low": 145, "high": 155, "duration_s": 600, "label": "easy"}]
    out = execution_score(steady_series(150, 300), seg)
    assert 45 <= out["score"] <= 55


# --- structure: per-segment, wrong intensity on the wrong step ------------

def test_botched_cooldown_drags_total_down():
    # Warmup + work nailed, but the cooldown is run at work HR (170 vs 145-155).
    series = {
        "t_s": [0, 100, 200, 300, 400, 500],
        "hr": [150, 150, 150, 150, 170, 170],  # last third too hot for cooldown
    }
    segs = [
        {"axis": "hr", "low": 145, "high": 155, "duration_s": 200, "label": "warmup"},
        {"axis": "hr", "low": 145, "high": 155, "duration_s": 200, "label": "work"},
        {"axis": "hr", "low": 145, "high": 155, "duration_s": 200, "label": "cooldown"},
    ]
    out = execution_score(series, segs)
    assert out["breakdown"][2]["score"] == 0   # cooldown failed
    assert out["score"] < 75                    # total dragged down, not 100


# --- pace axis ------------------------------------------------------------

def test_pace_axis_scores_speed_band():
    # Target 3.0-3.3 m/s; running 3.15 m/s is dead centre.
    seg = [{"axis": "pace", "low": 3.0, "high": 3.3, "duration_s": 600, "label": "tempo"}]
    out = execution_score(steady_series(3.15, 600, channel="speed_mps"), seg)
    assert out["score"] == 100


# --- guards ---------------------------------------------------------------

def test_none_when_hr_channel_absent_but_needed():
    seg = [{"axis": "hr", "low": 145, "high": 155, "duration_s": 600, "label": "easy"}]
    assert execution_score({"t_s": [0, 10], "speed_mps": [3, 3]}, seg) is None


def test_none_on_empty_inputs():
    assert execution_score(None, []) is None
    assert execution_score({"t_s": [0, 10], "hr": [150, 150]}, []) is None


# --- derive_hr_band -------------------------------------------------------

ZONES = {"z1": [130, 145], "z2": [148, 155], "z3": [158, 164],
         "z4": [166, 172], "z5": [174, 184]}


def test_warmup_and_cooldown_always_easy_zone():
    assert derive_hr_band("WARMUP", "TEMPO", ZONES) == [130, 145]
    assert derive_hr_band("COOLDOWN", "VO2MAX", ZONES) == [130, 145]


def test_work_step_takes_zone_from_te_label():
    assert derive_hr_band("INTERVAL", "TEMPO", ZONES) == [158, 164]
    assert derive_hr_band("INTERVAL", "LACTATE_THRESHOLD", ZONES) == [166, 172]
    assert derive_hr_band("INTERVAL", "AEROBIC_BASE", ZONES) == [148, 155]


def test_unknown_label_defaults_to_z2():
    assert derive_hr_band("INTERVAL", "MYSTERY", ZONES) == [148, 155]


def test_none_without_zones():
    assert derive_hr_band("INTERVAL", "TEMPO", None) is None


def test_recovery_intent_spans_z1_z2():
    # A recovery day (or an in-workout recovery jog) is scored against the broad
    # easy range, not a single narrow zone.
    assert derive_hr_band("INTERVAL", "RECOVERY", ZONES) == [130, 155]
    assert derive_hr_band("RECOVERY", "TEMPO", ZONES) == [130, 155]


# --- hr_zones_from_garmin -------------------------------------------------

def test_zones_from_garmin_boundaries():
    payload = [
        {"zoneNumber": 1, "zoneLowBoundary": 130},
        {"zoneNumber": 2, "zoneLowBoundary": 144},
        {"zoneNumber": 3, "zoneLowBoundary": 161},
        {"zoneNumber": 4, "zoneLowBoundary": 173},
        {"zoneNumber": 5, "zoneLowBoundary": 192},
    ]
    zones = metrics.hr_zones_from_garmin(payload)
    assert zones["z2"] == [144, 161]   # band = this zone's low .. next zone's low
    assert zones["z5"] == [192, 212]   # top zone open-ended -> +20 bpm cap


def test_zones_from_garmin_none_without_boundaries():
    assert metrics.hr_zones_from_garmin([]) is None
    assert metrics.hr_zones_from_garmin([{"zoneNumber": 1, "secsInZone": 100}]) is None
