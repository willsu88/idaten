from __future__ import annotations

import datetime as dt

from app import races, settings_store
from app.models import Activity, DailyHealth, Race

TODAY = dt.date.today()


def _seed_efforts(db, user_id, *, n=6, pace_s_per_km=330, dist_m=6000, base_days=3):
    """n identical hard-ish 6 km runs in the last few weeks -> a demonstrated anchor."""
    for i in range(n):
        db.add(Activity(id=1000 + i, user_id=user_id,
                        date=TODAY - dt.timedelta(days=base_days + i * 3),
                        type="running", distance_m=dist_m,
                        duration_s=pace_s_per_km * (dist_m / 1000)))
    db.commit()

PREDS = {
    "time_5k_s": 1500,        # 25:00
    "time_10k_s": 3120,       # 52:00
    "time_half_s": 7000,
    "time_marathon_s": 14700,
}


def test_parse_goal_time():
    assert races.parse_goal_time("3:45:00") == 3 * 3600 + 45 * 60
    assert races.parse_goal_time("52:30") == 52 * 60 + 30
    assert races.parse_goal_time("45") == 45
    assert races.parse_goal_time("") is None
    assert races.parse_goal_time(None) is None
    assert races.parse_goal_time("abc") is None


def test_riegel_exact_anchor_is_identity():
    assert races.riegel_predict(PREDS, 10.0) == 3120


def test_riegel_uses_nearest_anchor():
    # 21.14 km should anchor on the half (21.0975), not the marathon
    t = races.riegel_predict(PREDS, 21.14)
    expected = 7000 * (21.14 / 21.0975) ** races.RIEGEL_EXP
    assert abs(t - expected) < 1e-6


def test_riegel_handles_missing():
    assert races.riegel_predict(None, 10.0) is None
    assert races.riegel_predict({}, 10.0) is None
    assert races.riegel_predict(PREDS, 0) is None


def _ctx(garmin=PREDS, k=1.0, n_samples=0):
    return races.PredictionContext(garmin_predictions=garmin, k=k, n_samples=n_samples)


def test_race_dict_uncalibrated_shows_garmin(db):
    # No real races yet -> show Garmin's number, labelled "garmin", low confidence.
    r = Race(user_id=1, name="Test Half", date=TODAY + dt.timedelta(days=30),
             distance_km=21.0975, goal_time="1:52:00", is_primary=True)
    db.add(r)
    db.commit()
    d = races.race_dict(r, _ctx())
    p = d["prediction"]
    assert d["days_to_race"] == 30
    assert p["source"] == "garmin"
    assert p["confidence"] == "low"
    assert p["likely_s"] == 7000            # == Garmin's Riegel number (k=1.0)
    assert p["garmin_time_s"] == 7000
    assert p["goal_time_s"] == 6720
    assert p["delta_s"] == 280              # likely slower than goal
    assert p["low_s"] < p["likely_s"] < p["high_s"]


def test_race_prediction_calibrated_corrects_garmin(db):
    # Once k is learned from real races, likely_s = Garmin x k and source="idaten".
    r = Race(user_id=1, name="Half", date=TODAY + dt.timedelta(days=40),
             distance_km=21.0975, goal_time="2:28:00", is_primary=True)
    db.add(r)
    db.commit()
    p = races.race_prediction_block(r, _ctx(k=1.12, n_samples=2))
    assert p["source"] == "idaten"
    assert p["confidence"] == "medium"
    assert p["garmin_time_s"] == 7000       # Garmin's number rides along as ref
    assert p["likely_s"] == round(7000 * 1.12)


def test_maybe_record_race_result_updates_calibration(db):
    # Garmin predicted 2:20 for the half; athlete actually ran 2:30 -> k rises.
    db.add(DailyHealth(user_id=1, date=TODAY - dt.timedelta(days=2),
                       race_predictions={"time_half_s": 8400}))  # Garmin: 2:20 half
    race = Race(user_id=1, name="Goal Half", date=TODAY - dt.timedelta(days=1),
                distance_km=21.0975, goal_time="2:20:00")
    db.add(race)
    db.commit()
    result = Activity(id=9001, user_id=1, date=TODAY - dt.timedelta(days=1),
                      type="running", distance_m=21100, duration_s=9000)  # 2:30:00
    db.add(result)
    db.commit()
    before = settings_store.get_race_calibration(db, 1)["k"]
    races.maybe_record_race_result(db, 1, result)
    after = settings_store.get_race_calibration(db, 1)
    assert after["k"] > before              # 2:30 actual / ~2:20 predicted > 1
    assert len(after["samples"]) == 1
    # Idempotent: a second call for the same race doesn't double-count.
    races.maybe_record_race_result(db, 1, result)
    assert len(settings_store.get_race_calibration(db, 1)["samples"]) == 1


def test_latest_predictions_picks_newest(db):
    db.add(DailyHealth(user_id=1, date=TODAY - dt.timedelta(days=5), race_predictions={"time_5k_s": 1600}))
    db.add(DailyHealth(user_id=1, date=TODAY, race_predictions={"time_5k_s": 1500}))
    db.commit()
    assert races.latest_predictions(db, 1)["time_5k_s"] == 1500


def test_ensure_primary_promotes_next_upcoming(db):
    db.add(Race(user_id=1, name="A", date=TODAY + dt.timedelta(days=60), distance_km=10))
    db.add(Race(user_id=1, name="B", date=TODAY + dt.timedelta(days=20), distance_km=5))
    db.commit()
    races.ensure_primary(db, 1)
    primary = races.primary_race(db, 1)
    assert primary is not None and primary.name == "B"


def test_set_primary_is_exclusive(db):
    a = Race(user_id=1, name="A", date=TODAY + dt.timedelta(days=60), distance_km=10, is_primary=True)
    b = Race(user_id=1, name="B", date=TODAY + dt.timedelta(days=20), distance_km=5)
    db.add_all([a, b])
    db.commit()
    races.set_primary(db, b)
    assert not db.get(Race, a.id).is_primary
    assert db.get(Race, b.id).is_primary
