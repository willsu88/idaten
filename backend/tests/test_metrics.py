from __future__ import annotations

import datetime as dt

from app import metrics
from app.models import Activity, DailyHealth, DayIntent

TODAY = dt.date.today()


def _run(db, date, load=None, duration_s=3600.0, avg_hr=150.0, speed=3.0, aid=None, user_id=1):
    a = Activity(
        id=aid or int(date.strftime("%Y%m%d")) * 10 + user_id,
        user_id=user_id,
        date=date,
        type="running",
        distance_m=speed * duration_s,
        duration_s=duration_s,
        avg_hr=avg_hr,
        avg_speed_mps=speed,
        training_load=load,
    )
    db.add(a)
    db.commit()
    return a


# --- pace conversions ---------------------------------------------------------

def test_pace_str():
    assert metrics.pace_str(1000 / 330) == "5:30"
    assert metrics.pace_str(None) is None
    assert metrics.pace_str(0) is None


def test_pace_to_mps_roundtrip():
    mps = metrics.pace_to_mps("5:30")
    assert abs(mps - 1000 / 330) < 1e-9
    assert metrics.pace_str(mps) == "5:30"
    assert metrics.pace_to_mps("garbage") is None
    assert metrics.pace_to_mps(None) is None


# --- efficiency factor ----------------------------------------------------------

def test_efficiency_factor():
    a = Activity(id=1, user_id=1, date=TODAY, avg_speed_mps=3.0, avg_hr=150.0)
    assert metrics.efficiency_factor(a) == round(3.0 * 60 / 150, 3)
    assert metrics.efficiency_factor(Activity(id=2, user_id=1, date=TODAY, avg_hr=150.0)) is None
    assert metrics.efficiency_factor(Activity(id=3, user_id=1, date=TODAY, avg_speed_mps=3.0)) is None


# --- activity load ---------------------------------------------------------------

def test_activity_load_prefers_garmin_value():
    a = Activity(id=1, user_id=1, date=TODAY, training_load=87.0, duration_s=3600)
    assert metrics.activity_load(a) == 87.0


def test_activity_load_duration_fallback():
    a = Activity(id=1, user_id=1, date=TODAY, training_load=None, duration_s=3600)
    assert metrics.activity_load(a) == 60.0
    assert metrics.activity_load(Activity(id=2, user_id=1, date=TODAY)) == 0.0


# --- load series (CTL/ATL/TSB) ---------------------------------------------------

def test_load_series_single_activity_decays(db):
    d0 = TODAY - dt.timedelta(days=10)
    _run(db, d0, load=100.0)
    series = metrics.load_series(db, 1, d0, TODAY)
    assert series[0].date == d0
    assert series[0].load == 100.0
    # ATL responds faster than CTL, so TSB goes negative after a hard day
    assert series[0].atl > series[0].ctl
    assert series[0].tsb < 0
    # Both decay toward zero with no further load
    assert series[-1].atl < series[0].atl
    assert series[-1].ctl < series[0].ctl
    # First-day values match the closed-form single-impulse response
    assert abs(series[0].ctl - 100.0 / metrics.CTL_DAYS) < 1e-9
    assert abs(series[0].atl - 100.0 / metrics.ATL_DAYS) < 1e-9


def test_load_series_warmup_counts_history(db):
    # An activity 30 days before the requested window still raises starting CTL
    _run(db, TODAY - dt.timedelta(days=30), load=200.0)
    series = metrics.load_series(db, 1, TODAY - dt.timedelta(days=5), TODAY)
    assert series[0].ctl > 0


def test_intent_day_estimates_load(db):
    d = TODAY - dt.timedelta(days=2)
    db.add(DayIntent(user_id=1, date=d, sport="surfing", duration_min=90, effort="hard"))
    db.commit()
    series = metrics.load_series(db, 1, d, d)
    assert series[0].load == 90 * metrics.INTENT_EFFORT_LOAD["hard"]


def test_intent_ignored_when_activity_recorded(db):
    d = TODAY - dt.timedelta(days=2)
    _run(db, d, load=50.0)
    db.add(DayIntent(user_id=1, date=d, sport="hiking", duration_min=120, effort="hard"))
    db.commit()
    series = metrics.load_series(db, 1, d, d)
    assert series[0].load == 50.0


# --- readiness -------------------------------------------------------------------

def test_readiness_none_without_data(db):
    assert metrics.readiness(db, 1, TODAY) is None


def test_readiness_full_data(db):
    _run(db, TODAY - dt.timedelta(days=3), load=50.0)
    db.add(DailyHealth(
        user_id=1, date=TODAY, sleep_seconds=7.5 * 3600, sleep_score=85,
        hrv=60, hrv_baseline=60, body_battery=80,
    ))
    db.commit()
    r = metrics.readiness(db, 1, TODAY)
    assert r is not None
    assert 0 <= r["score"] <= 100
    assert r["level"] in ("green", "yellow", "red")
    assert r["components"]["hrv_delta_pct"] == 0.0


def test_readiness_partial_data_renormalizes(db):
    # Only sleep hours available; score should be the sleep score alone (100 at 7.5h+)
    db.add(DailyHealth(user_id=1, date=TODAY, sleep_seconds=7.5 * 3600))
    db.commit()
    r = metrics.readiness(db, 1, TODAY)
    assert r["score"] == 100


def test_readiness_suppressed_hrv_lowers_score(db):
    base = dict(sleep_seconds=7.5 * 3600, sleep_score=85, body_battery=80, hrv_baseline=60)
    db.add(DailyHealth(user_id=1, date=TODAY, hrv=60, **base))
    db.add(DailyHealth(user_id=1, date=TODAY - dt.timedelta(days=1), hrv=45, **base))
    db.commit()
    good = metrics.readiness(db, 1, TODAY)["score"]
    bad = metrics.readiness(db, 1, TODAY - dt.timedelta(days=1))["score"]
    assert bad < good


# --- race prediction (VDOT model) -------------------------------------------

def test_vdot_race_time_round_trip():
    # A performance -> VDOT -> predicted time at the SAME distance is the identity.
    vdot = metrics.vdot_from_performance(10000, 2400)  # 10 km in 40:00
    assert vdot is not None and 45 < vdot < 60
    back = metrics.race_time_for_vdot(vdot, 10.0)
    assert abs(back - 2400) <= 2  # within bisection tolerance


def test_vdot_of_known_half():
    # 2:12 half ~ Daniels VDOT 32-33 (Julianne's Garmin optimistic number).
    vdot = metrics.vdot_from_performance(21097.5, 7920)
    assert 31 <= vdot <= 34


def test_race_time_monotonic_in_vdot():
    # Fitter (higher VDOT) -> faster predicted time.
    fast = metrics.race_time_for_vdot(55, 21.0975)
    slow = metrics.race_time_for_vdot(45, 21.0975)
    assert fast < slow


def test_demonstrated_anchor_none_when_sparse(db):
    db.add(Activity(id=1, user_id=1, date=TODAY - dt.timedelta(days=2),
                    type="running", distance_m=6000, duration_s=1980))
    db.commit()
    # No LTHR -> coarse path needs >= 3 runs; only 1 exists.
    assert metrics.demonstrated_anchor(db, 1, TODAY) is None


def test_demonstrated_anchor_coarse_excludes_junk_and_short(db):
    # 3 valid runs + 1 too-short + 1 GPS-junk -> coarse anchor from the 3 valid.
    for i, (dist, dur) in enumerate([(8000, 2640), (6000, 1980), (7000, 2310)]):
        db.add(Activity(id=i + 1, user_id=1, date=TODAY - dt.timedelta(days=2 + i),
                        type="running", distance_m=dist, duration_s=dur))
    db.add(Activity(id=90, user_id=1, date=TODAY - dt.timedelta(days=6),
                    type="running", distance_m=1000, duration_s=300))    # too short
    db.add(Activity(id=91, user_id=1, date=TODAY - dt.timedelta(days=7),
                    type="running", distance_m=5000, duration_s=200))    # junk pace
    db.commit()
    anchor = metrics.demonstrated_anchor(db, 1, TODAY)   # no LTHR -> coarse
    assert anchor is not None
    assert anchor["n_efforts"] == 3
    assert anchor["quality"] == "coarse"


def test_demonstrated_anchor_hard_gate_excludes_easy(db):
    # With LTHR known, easy runs (low HR) drop out; only hard efforts anchor.
    db.add(Activity(id=1, user_id=1, date=TODAY - dt.timedelta(days=2),
                    type="running", distance_m=8000, duration_s=2640, avg_hr=170))  # hard
    db.add(Activity(id=2, user_id=1, date=TODAY - dt.timedelta(days=4),
                    type="running", distance_m=10000, duration_s=3300, avg_hr=172))  # hard
    db.add(Activity(id=3, user_id=1, date=TODAY - dt.timedelta(days=6),
                    type="running", distance_m=12000, duration_s=4200, avg_hr=135))  # easy
    db.commit()
    anchor = metrics.demonstrated_anchor(db, 1, TODAY, lthr=185)
    assert anchor["quality"] == "hard"
    assert anchor["n_efforts"] == 2                     # the easy run is excluded
    # Coarse (no LTHR) would keep all three.
    assert metrics.demonstrated_anchor(db, 1, TODAY)["n_efforts"] == 3


def test_demonstrated_anchor_respects_asof_window(db):
    # A run AFTER the asof date is excluded (calibration measures pre-race).
    for i in range(3):
        db.add(Activity(id=i + 1, user_id=1, date=TODAY - dt.timedelta(days=2 + i * 3),
                        type="running", distance_m=6000, duration_s=1980))
    db.add(Activity(id=99, user_id=1, date=TODAY,  # after asof
                    type="running", distance_m=6000, duration_s=1500))
    db.commit()
    anchor = metrics.demonstrated_anchor(db, 1, TODAY - dt.timedelta(days=1))
    assert anchor["n_efforts"] == 3


def test_race_prediction_uncalibrated_shows_garmin():
    # No real races yet -> we show Garmin's number, honestly labelled "garmin".
    p = metrics.race_prediction(garmin_time_s=7000, k=1.0, n_samples=0)
    assert p["source"] == "garmin"
    assert p["likely_s"] == 7000
    assert p["confidence"] == "low"
    assert p["low_s"] < p["likely_s"] < p["high_s"]


def test_race_prediction_calibrated_corrects_garmin():
    # After real races, k corrects Garmin's optimism and the number is "ours".
    p = metrics.race_prediction(garmin_time_s=7920, k=1.12, n_samples=2)
    assert p["source"] == "idaten"
    assert p["likely_s"] == round(7920 * 1.12)   # Garmin 2:12 * 1.12 -> ~2:28
    assert p["confidence"] == "medium"


def test_race_prediction_confidence_tightens_with_samples():
    wide = metrics.race_prediction(7920, 1.1, n_samples=0)
    tight = metrics.race_prediction(7920, 1.1, n_samples=3)
    assert metrics.prediction_confidence(0) == "low"
    assert metrics.prediction_confidence(1) == "medium"
    assert metrics.prediction_confidence(3) == "high"
    # Higher confidence -> narrower range.
    assert (tight["high_s"] - tight["low_s"]) < (wide["high_s"] - wide["low_s"])


def test_race_prediction_empty_when_no_garmin():
    p = metrics.race_prediction(garmin_time_s=None, k=1.0, n_samples=0)
    assert p["likely_s"] is None and p["source"] == "garmin"
