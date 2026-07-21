"""Phase 5 (profile endpoint) + Phase 6 (structured workouts, library, checks)."""

from __future__ import annotations

import datetime as dt

from app import metrics
from app.garmin.push import _workout_payload
from app.models import Activity, PlanDay
from app.planner import apply_plan_days, check_week, plan_day_dict, quality_budget
from app.workout_library import LIBRARY, library_menu, phase_for

from conftest import make_user

TODAY = dt.date.today()


# --- Phase 5: profile ---------------------------------------------------------

def test_update_profile(db, client):
    make_user(db, "gf", "secret2")
    client.post("/api/auth/login", json={"username": "gf", "password": "secret2"})

    r = client.post("/api/auth/profile", json={"display_name": "  Yuki  "})
    assert r.status_code == 200 and r.json()["display_name"] == "Yuki"
    assert client.get("/api/auth/me").json()["display_name"] == "Yuki"

    assert client.post("/api/auth/profile", json={"display_name": "   "}).status_code == 422
    assert client.post("/api/auth/profile", json={"display_name": "x" * 41}).status_code == 422


# --- Phase 6: deterministic signals ---------------------------------------------

def _act(user_id, date, load, km=8.0):
    return Activity(
        id=int(date.strftime("%Y%m%d")) * 10 + user_id,
        user_id=user_id, date=date, type="running", name="run",
        distance_m=km * 1000, duration_s=int(km * 360), training_load=load,
    )


def test_training_monotony(db, user):
    # No activities at all -> None
    assert metrics.training_monotony(db, user.id, TODAY) is None

    # Identical load every day -> SD 0 -> None (nothing to measure)
    for i in range(7):
        db.add(_act(user.id, TODAY - dt.timedelta(days=i), load=50))
    db.commit()
    assert metrics.training_monotony(db, user.id, TODAY) is None

    # A varied week scores low; Foster flags ~2.0+ as monotonous
    db.query(Activity).delete()
    for i, load in enumerate([90, 0, 40, 0, 120, 0, 30]):
        if load:
            db.add(_act(user.id, TODAY - dt.timedelta(days=i), load=load))
    db.commit()
    m = metrics.training_monotony(db, user.id, TODAY)
    assert m is not None and m < 1.5


def test_training_paces():
    assert metrics.training_paces(None) is None
    paces = metrics.training_paces(52)
    assert set(paces) == {"E", "M", "T", "I", "R"}

    def secs(p):
        m, s = p.split(":")
        return int(m) * 60 + int(s)

    # Each zone is strictly faster than the previous (compare fast bounds),
    # and each band is (slower, faster)
    fast = [secs(paces[z][1]) for z in ("E", "M", "T", "I", "R")]
    assert fast == sorted(fast, reverse=True)
    for band in paces.values():
        assert secs(band[0]) > secs(band[1])
    # Anchor: Daniels VDOT 52 threshold pace is ~4:11/km
    assert abs(secs(paces["T"][0]) - 251) <= 8


def test_phase_gating_and_flavors():
    assert phase_for(None) == "base"
    assert phase_for(120) == "base"
    assert phase_for(84) == "build"
    assert phase_for(43) == "build"
    assert phase_for(42) == "peak"
    assert phase_for(14) == "peak"
    assert phase_for(13) == "taper"

    ids = lambda menu: {t["id"] for t in menu}  # noqa: E731
    base = ids(library_menu("base", "default"))
    assert "vo2_classic" not in base and "hill_repeats" in base
    taper = ids(library_menu("taper", "strict"))
    assert "taper_sharpener" in taper and "cruise_intervals" not in taper

    chill = ids(library_menu("build", "chill"))
    assert "fartlek_surges" in chill and "vo2_classic" not in chill
    strict = ids(library_menu("build", "strict"))
    assert "vo2_classic" in strict and "fartlek_surges" not in strict
    # Easy/long/recovery basics available to every persona
    for style in ("default", "chill", "strict"):
        assert {"easy_run", "recovery_jog", "long_easy"} <= ids(library_menu("build", style))
    # Unknown style falls back to default rather than an empty menu
    assert ids(library_menu("build", "bogus")) == ids(library_menu("build", "default"))
    # Every template declares valid phases
    for t in LIBRARY:
        assert t["phases"] and set(t["phases"]) <= {"base", "build", "peak", "taper"}


def test_quality_budget():
    green = {"level": "green"}
    assert quality_budget(green, 1.0, "build") == 2
    assert quality_budget(green, 1.0, "taper") == 1
    assert quality_budget({"level": "yellow"}, 1.0, "build") == 1
    assert quality_budget({"level": "red"}, 1.0, "build") == 0
    assert quality_budget(green, 1.4, "build") == 1
    assert quality_budget(green, 1.6, "build") == 0
    assert quality_budget(None, None, "build") == 2


def test_check_week():
    def day(wt, minutes):
        return {"workout_type": wt, "duration_min": minutes, "distance_km": None}

    good = [day("easy_run", 50), day("tempo", 45), day("rest", None),
            day("long_run", 100), day("easy_run", 40), day("intervals", 50),
            day("rest", None)]
    assert check_week(good, budget=2) == []

    over = check_week(good, budget=1)
    assert any("exceed budget" in w for w in over)

    all_hard = [day("tempo", 60), day("intervals", 60), day("easy_run", 30)]
    warns = check_week(all_hard, budget=2)
    assert any("hard time" in w for w in warns)


# --- Phase 6: steps through the plan pipeline -----------------------------------

STEPS = [
    {"repeat": 1, "steps": [{"kind": "warmup", "duration_min": 15, "distance_km": None,
                             "target_pace": None, "target_hr_low": 130, "target_hr_high": 145,
                             "note": "very relaxed"}]},
    {"repeat": 6, "steps": [
        {"kind": "work", "duration_min": None, "distance_km": 0.8, "target_pace": "3:50",
         "target_hr_low": None, "target_hr_high": None, "note": "controlled, not all-out"},
        {"kind": "recovery", "duration_min": None, "distance_km": 0.4, "target_pace": None,
         "target_hr_low": None, "target_hr_high": None, "note": "easy float"},
    ]},
    {"repeat": 1, "steps": [{"kind": "cooldown", "duration_min": 10, "distance_km": None,
                             "target_pace": None, "target_hr_low": None, "target_hr_high": None,
                             "note": ""}]},
]


def _day_dict(date, steps=None, **over):
    d = {"date": date.isoformat(), "workout_type": "intervals", "title": "VO2 800s",
         "description": "6x800", "duration_min": 60, "distance_km": None,
         "target_pace": None, "target_hr_low": None, "target_hr_high": None,
         "steps": steps, "rationale": "test"}
    d.update(over)
    return d


def test_apply_persists_steps_and_detects_changes(db, user):
    date = TODAY + dt.timedelta(days=1)
    changed = apply_plan_days(db, user.id, [_day_dict(date, steps=STEPS)], "test", "s")
    assert len(changed) == 1
    row = db.get(PlanDay, (user.id, date))
    assert row.steps == STEPS and plan_day_dict(row)["steps"] == STEPS

    # Same day again -> no material change
    assert apply_plan_days(db, user.id, [_day_dict(date, steps=STEPS)], "test", "s") == []

    # Steps-only change is material (needs re-push)
    fewer = [STEPS[0], {**STEPS[1], "repeat": 5}, STEPS[2]]
    assert len(apply_plan_days(db, user.id, [_day_dict(date, steps=fewer)], "test", "s")) == 1

    # Empty list normalizes to null
    apply_plan_days(db, user.id, [_day_dict(date, steps=[])], "test", "s")
    assert db.get(PlanDay, (user.id, date)).steps is None


def test_multistep_push_payload(db, user):
    day = PlanDay(user_id=user.id, date=TODAY, workout_type="intervals",
                  title="VO2 800s", description="6x800", duration_min=60,
                  steps=STEPS)
    payload = _workout_payload(day)
    steps = payload["workoutSegments"][0]["workoutSteps"]
    assert [s["type"] for s in steps] == ["ExecutableStepDTO", "RepeatGroupDTO", "ExecutableStepDTO"]

    wu, group, cd = steps
    assert wu["stepType"]["stepTypeKey"] == "warmup"
    assert wu["targetType"]["workoutTargetTypeKey"] == "heart.rate.zone"
    assert (wu["targetValueOne"], wu["targetValueTwo"]) == (130.0, 145.0)
    assert wu["endCondition"]["conditionTypeKey"] == "time" and wu["endConditionValue"] == 900.0

    assert group["numberOfIterations"] == 6
    assert group["endCondition"]["conditionTypeKey"] == "iterations"
    work, rec = group["workoutSteps"]
    assert work["stepType"]["stepTypeKey"] == "interval"
    assert work["targetType"]["workoutTargetTypeKey"] == "pace.zone"
    assert work["endCondition"]["conditionTypeKey"] == "distance" and work["endConditionValue"] == 800.0
    assert rec["stepType"]["stepTypeKey"] == "recovery"
    assert rec["targetType"]["workoutTargetTypeKey"] == "no.target"

    assert cd["stepType"]["stepTypeKey"] == "cooldown"

    # stepOrder is globally sequential, containers included
    orders = [wu["stepOrder"], group["stepOrder"], work["stepOrder"],
              rec["stepOrder"], cd["stepOrder"]]
    assert orders == [1, 2, 3, 4, 5]


def test_legacy_single_step_push_unchanged(db, user):
    day = PlanDay(user_id=user.id, date=TODAY, workout_type="easy_run",
                  title="Easy", description="", duration_min=None, distance_km=10,
                  target_pace="5:30", steps=None)
    steps = _workout_payload(day)["workoutSegments"][0]["workoutSteps"]
    assert len(steps) == 1 and steps[0]["type"] == "ExecutableStepDTO"
    assert steps[0]["endCondition"]["conditionTypeKey"] == "distance"
    assert steps[0]["targetType"]["workoutTargetTypeKey"] == "pace.zone"


# --- data-only manual sync -------------------------------------------------------

def test_sync_only_job_never_replans(db, user, monkeypatch):
    from app import scheduler
    from app.models import SyncLog

    called = {"sync": 0}
    monkeypatch.setattr(scheduler, "run_sync", lambda db_, u: called.__setitem__("sync", called["sync"] + 1) or TODAY)
    monkeypatch.setattr(scheduler, "has_garmin", lambda u: True)
    monkeypatch.setattr(scheduler, "session", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)  # job owns its session; keep the fixture's alive

    result = scheduler.sync_only_job(user.id)
    # Manual sync is data-only: it syncs and never materializes/reviews a plan.
    assert result["ok"] and called["sync"] == 1
    row = db.query(SyncLog).order_by(SyncLog.id.desc()).first()
    assert row.kind == "data" and row.status == "ok" and row.plan_updated is False
    assert db.query(PlanDay).count() == 0


def test_data_syncs_dont_mark_daily_job_done(db, user, monkeypatch):
    import datetime as _dt

    from app import scheduler
    from app.models import SyncLog

    monkeypatch.setattr(scheduler, "has_garmin", lambda u: True)
    now = _dt.datetime.now(_dt.timezone.utc)

    # Only a manual data sync today -> the real (replan) job still owes us a run
    db.add(SyncLog(user_id=user.id, status="ok", kind="data", detail=""))
    db.commit()
    assert scheduler._ran_today_for_all(db, now) is False

    # A full run (kind NULL = legacy row) counts
    db.add(SyncLog(user_id=user.id, status="ok", kind=None, detail=""))
    db.commit()
    assert scheduler._ran_today_for_all(db, now) is True
