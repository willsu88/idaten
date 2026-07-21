"""Load-ramp guardrail (Idea E): signal zones, persistence, floor, forward
projection, planned-load estimate, and the check_week assertion."""

from __future__ import annotations

import datetime as dt

from app import metrics
from app.models import Activity
from app.planner import check_week

TODAY = dt.date.today()


def _run(db, user_id, date, load):
    a = Activity(user_id=user_id, date=date, type="running",
                 duration_s=int(load * 60), training_load=load)
    db.add(a)


def _seed(db, user_id, daily: list[float]):
    """daily[0] is the OLDEST day; last entry lands on TODAY."""
    for i, load in enumerate(daily):
        if load > 0:
            _run(db, user_id, TODAY - dt.timedelta(days=len(daily) - 1 - i), load)
    db.commit()


def test_steady_training_is_safe(db, user):
    # 80 days so the trend's comparison window is fully inside history —
    # 40 days would (correctly) read as "building" from nothing.
    _seed(db, user.id, [30.0] * 80)
    s = metrics.ramp_signal(db, user.id, TODAY)
    assert s["zone"] == "safe"
    assert 0.95 <= s["acwr_7d_28d"] <= 1.05
    assert s["chronic_trend"] == "flat"


def test_sustained_spike_flags_high(db, user):
    # A month at 25/day, then the last 7 days doubled — held well past 3 days.
    _seed(db, user.id, [25.0] * 33 + [55.0] * 7)
    s = metrics.ramp_signal(db, user.id, TODAY)
    assert s["zone"] == "high"


def test_single_hot_day_does_not_flag(db, user):
    # One big day on a steady base: ratio may blip but persistence guards it.
    _seed(db, user.id, [25.0] * 39 + [90.0])
    s = metrics.ramp_signal(db, user.id, TODAY)
    assert s["zone"] == "safe"


def test_travel_week_return_is_not_flagged(db, user):
    # Will's question: months at ~30/day, one ~10/day travel week, back to 30.
    # The 28-day baseline absorbs the dip — returning to normal is SAFE.
    daily = [30.0] * 26 + [10.0] * 7 + [30.0] * 7
    _seed(db, user.id, daily)
    s = metrics.ramp_signal(db, user.id, TODAY)
    assert s["zone"] == "safe"
    assert s["acwr_7d_28d"] <= 1.3


def test_month_off_return_is_flagged(db, user):
    # A real base, then a month mostly off (chronic decays below the floor),
    # then straight back to full volume: the comeback ramp is genuine and the
    # had-recent-base rule waives the floor so it flags.
    daily = [30.0] * 30 + [3.0] * 28 + [30.0] * 7
    _seed(db, user.id, daily)
    s = metrics.ramp_signal(db, user.id, TODAY)
    assert s["zone"] in ("caution", "high")


def test_low_chronic_floor_suppresses_zone(db, user):
    # A brand-new runner's first week: huge ratio on a near-zero base is noise,
    # not a ramp — the floor keeps the zone safe.
    _seed(db, user.id, [0.0] * 30 + [20.0] * 5)
    s = metrics.ramp_signal(db, user.id, TODAY)
    assert s["zone"] == "safe"
    assert s["chronic_floor_met"] is False


def test_no_history_returns_none(db, user):
    assert metrics.ramp_signal(db, user.id, TODAY) is None


def test_detraining_trend_reported_not_zoned(db, user):
    # Chronic sliding down: trend says detraining, zone stays safe (no alarm).
    daily = [40.0] * 20 + [5.0] * 20
    _seed(db, user.id, daily)
    s = metrics.ramp_signal(db, user.id, TODAY)
    assert s["chronic_trend"] == "detraining"
    assert s["zone"] == "safe"


def test_forward_projection_flags_planned_overreach(db, user):
    _seed(db, user.id, [25.0] * 40)
    plan = [{"date": (TODAY + dt.timedelta(days=i)).isoformat(),
             "workout_type": "easy_run", "duration_min": 90} for i in range(7)]
    s = metrics.ramp_signal(db, user.id, TODAY, planned_days=plan)
    p = s["planned_next_week"]
    assert p["acwr_if_executed"] > 1.3
    assert p["zone"] in ("caution", "high")
    # A sane week projects safe.
    plan_ok = [{"date": d["date"], "workout_type": "easy_run", "duration_min": 25}
               for d in plan]
    s2 = metrics.ramp_signal(db, user.id, TODAY, planned_days=plan_ok)
    assert s2["planned_next_week"]["zone"] == "safe"


def test_planned_day_load_estimates():
    assert metrics.planned_day_load({"workout_type": "rest"}) == 0.0
    easy = metrics.planned_day_load({"workout_type": "easy_run", "duration_min": 40})
    tempo = metrics.planned_day_load({"workout_type": "tempo", "duration_min": 40})
    assert easy == 40.0 and tempo == 60.0  # intensity factor applies
    # distance fallback: 5 km ~ 30 easy minutes
    assert metrics.planned_day_load({"workout_type": "easy_run", "distance_km": 5}) == 30.0


def test_check_week_ramp_warning():
    days = [{"date": f"2026-08-{10+i:02d}", "workout_type": "easy_run",
             "duration_min": 80} for i in range(7)]
    # chronic 25/day, planned 80/day -> projected ratio >> 1.3 -> warns.
    warns = check_week(days, budget=2, chronic_daily_load=25.0)
    assert any("acwr" in w for w in warns)
    # Same week on a big chronic base is fine; and no chronic -> no ramp check.
    assert not any("acwr" in w for w in check_week(days, budget=2,
                                                   chronic_daily_load=80.0))
    assert not any("acwr" in w for w in check_week(days, budget=2))


def test_ramp_series_shape(db, user):
    _seed(db, user.id, [30.0] * 40)
    rows = metrics.ramp_series(db, user.id, TODAY - dt.timedelta(days=9), TODAY)
    assert len(rows) == 10
    last = rows[-1]
    assert last["date"] == TODAY.isoformat()
    assert last["chronic"] > 0 and 0.9 <= last["ratio"] <= 1.1
    # Below the floor the ratio is withheld, not fabricated.
    early = metrics.ramp_series(db, user.id, TODAY - dt.timedelta(days=60),
                                TODAY - dt.timedelta(days=55))
    assert all(r["ratio"] is None for r in early)


def test_analytics_carries_ramp(client, db):
    from tests.conftest import make_user

    make_user(db, username="will", password="secret1")
    r = client.post("/api/auth/login", json={"username": "will", "password": "secret1"})
    assert r.status_code == 200
    _seed(db, 1, [30.0] * 40)
    body = client.get("/api/analytics?days=30").json()
    ramp = body["ramp"]
    assert ramp["caution"] == 1.3 and ramp["high"] == 1.5
    assert len(ramp["series"]) >= 30
    assert ramp["zone_today"] == "safe"
