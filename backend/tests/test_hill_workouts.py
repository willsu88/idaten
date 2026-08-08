"""Hill sessions: prescribe by effort, verify by climb.

Garmin cannot trigger or target a workout step on grade, so a hill session
reaches the watch as ordinary time-based intervals. Everything that makes it a
HILL session is ours: the step carries `terrain`, an uphill step is targeted by
HR rather than pace, and the climb is confirmed after the run from the per-lap
elevation gain Garmin does give back.
"""

from __future__ import annotations

import datetime as dt

from app import execution, metrics, planner
from app.garmin.push import _workout_payload
from app.models import Activity, PlanDay, PlanVersion

TODAY = dt.date(2026, 7, 16)

ZONES = {"z1": [100, 130], "z2": [131, 145], "z3": [146, 160],
         "z4": [161, 172], "z5": [173, 190]}


def _step(kind="work", **kw):
    base = dict(kind=kind, duration_min=1.0, distance_km=None, target_pace=None,
                target_hr_low=None, target_hr_high=None, note="", terrain="flat")
    base.update(kw)
    return base


def _hill_day(**kw):
    """A hill session as the planner is told to build one: uphill work by time,
    lap-button jog-down recovery."""
    steps = [
        {"repeat": 1, "steps": [_step("warmup", duration_min=15)]},
        {"repeat": 6, "steps": [
            _step("work", duration_min=1.0, terrain="uphill",
                  target_hr_low=161, target_hr_high=172),
            _step("recovery", duration_min=None, terrain="downhill"),
        ]},
        {"repeat": 1, "steps": [_step("cooldown", duration_min=10)]},
    ]
    defaults = dict(user_id=1, date=TODAY, workout_type="intervals",
                    title="Hill repeats 6x60s", description="On your usual hill",
                    steps=steps)
    defaults.update(kw)
    return PlanDay(**defaults)


# --- terrain vocabulary ------------------------------------------------------

def test_absent_terrain_reads_as_flat():
    """Steps written before terrain existed must not become a third state."""
    assert metrics.step_terrain({}) == "flat"
    assert metrics.step_terrain(None) == "flat"
    assert metrics.step_terrain({"terrain": "nonsense"}) == "flat"
    assert metrics.step_terrain({"terrain": "uphill"}) == "uphill"


def test_terrain_is_in_the_step_schema():
    assert "terrain" in planner.STEP_SCHEMA["properties"]
    assert "terrain" in planner.STEP_SCHEMA["required"]


# --- the defect: uphill steps must never carry a pace target -----------------

def _steps_of(payload):
    out = []
    for s in payload["workoutSegments"][0]["workoutSteps"]:
        out.extend(s.get("workoutSteps") or [s])
    return out


def test_uphill_step_pushes_an_hr_target_not_pace():
    steps = _steps_of(_workout_payload(_hill_day()))
    work = [s for s in steps if s["stepType"]["stepTypeKey"] == "interval"]
    assert work, "expected an interval step"
    for s in work:
        assert s["targetType"]["workoutTargetTypeKey"] == "heart.rate.zone"
        assert (s["targetValueOne"], s["targetValueTwo"]) == (161.0, 172.0)


def test_uphill_step_never_pushes_pace_even_when_one_is_stored():
    """The push boundary holds for a day stored before the terrain guard."""
    day = _hill_day()
    day.steps[1]["steps"][0].update(target_pace="4:10-4:20",
                                    target_hr_low=None, target_hr_high=None)
    steps = _steps_of(_workout_payload(day))
    work = [s for s in steps if s["stepType"]["stepTypeKey"] == "interval"]
    for s in work:
        assert s["targetType"]["workoutTargetTypeKey"] == "no.target"


def test_flat_step_still_takes_its_pace_target():
    """The uphill rule must not leak into ordinary track intervals."""
    day = _hill_day()
    work = day.steps[1]["steps"][0]
    work.update(terrain="flat", target_pace="4:10-4:20",
                target_hr_low=None, target_hr_high=None)
    steps = _steps_of(_workout_payload(day))
    interval = [s for s in steps if s["stepType"]["stepTypeKey"] == "interval"][0]
    assert interval["targetType"]["workoutTargetTypeKey"] == "pace.zone"


def test_jog_down_is_a_lap_button_step():
    """A lap-button recovery is what makes the session fit any hill."""
    steps = _steps_of(_workout_payload(_hill_day()))
    rec = [s for s in steps if s["stepType"]["stepTypeKey"] == "recovery"][0]
    assert rec["endCondition"]["conditionTypeKey"] == "lap.button"


# --- the planner guard -------------------------------------------------------

def test_terrain_guard_flags_an_uphill_pace_target():
    day = {"date": TODAY.isoformat(), "workout_type": "intervals", "steps": [
        {"repeat": 6, "steps": [_step("work", terrain="uphill", target_pace="4:10")]},
    ]}
    violations = planner.terrain_target_violations([day])
    assert len(violations) == 1
    assert "uphill" in violations[0]


def test_terrain_guard_passes_an_hr_targeted_hill():
    day = {"date": TODAY.isoformat(), "workout_type": "intervals", "steps": [
        {"repeat": 6, "steps": [_step("work", terrain="uphill",
                                      target_hr_low=161, target_hr_high=172)]},
    ]}
    assert planner.terrain_target_violations([day]) == []


def test_terrain_guard_ignores_flat_pace_targets():
    day = {"date": TODAY.isoformat(), "workout_type": "intervals", "steps": [
        {"repeat": 6, "steps": [_step("work", target_pace="4:10")]},
    ]}
    assert planner.terrain_target_violations([day]) == []


# --- scoring -----------------------------------------------------------------

def test_uphill_step_is_not_scored_against_a_pace_band():
    """A climb held at the right effort misses a flat band by a mile; scoring it
    that way would fail a correctly-executed repetition."""
    assert execution._step_segment(None, None, "4:10-4:20", 1.0, None, "work",
                                   ZONES, True, "uphill") is None


def test_uphill_step_is_scored_against_its_hr_band():
    seg = execution._step_segment(161, 172, None, 1.0, None, "work",
                                  ZONES, True, "uphill")
    assert seg["axis"] == "hr"
    assert (seg["low"], seg["high"]) == (161.0, 172.0)


def test_flat_step_is_still_scored_against_its_pace_band():
    seg = execution._step_segment(None, None, "4:10-4:20", 1.0, None, "work",
                                  ZONES, True, "flat")
    assert seg["axis"] == "pace"


# --- verify the climb actually happened --------------------------------------

def _splits(*gains):
    return [{"elevation_gain_m": g, "duration_s": 60} for g in gains]


def test_no_hill_check_when_the_day_prescribed_no_climbing():
    """Almost every run: the field stays null rather than becoming noise."""
    day = PlanDay(user_id=1, date=TODAY, workout_type="easy_run", steps=None)
    assert execution.hill_check(day, _splits(0, 0, 0)) is None
    assert execution.hill_check(None, _splits(40, 40)) is None


def test_hill_session_run_on_a_hill_verifies():
    # warmup + 6 climbs + 6 jog-downs + cooldown
    splits = _splits(3, 18, 1, 20, 1, 17, 2, 19, 1, 21, 1, 18, 2, 4)
    check = execution.hill_check(_hill_day(), splits)
    assert check["verified"] is True
    assert check["prescribed_reps"] == 6
    assert check["climbed_reps"] == 6
    assert check["ascent_m"] == 113


def test_hill_session_run_somewhere_flat_does_not_verify():
    """The watch cannot enforce the hill, so this is the only place it is caught."""
    check = execution.hill_check(_hill_day(), _splits(1, 2, 0, 1, 2, 1, 0, 2, 1, 1))
    assert check["verified"] is False
    assert check["climbed_reps"] == 0
    # Reports how flat it actually was, rather than a bare 0 that cannot
    # distinguish "no climbing" from "nothing measured".
    assert check["ascent_m"] == 9


def test_a_shortened_set_still_verifies_the_terrain():
    """Cutting the set short is a score question, not a terrain question."""
    check = execution.hill_check(_hill_day(), _splits(3, 19, 1, 20, 1, 18, 2, 5))
    assert check["verified"] is True
    assert check["climbed_reps"] == 3
    assert check["prescribed_reps"] == 6


def test_one_lone_climb_out_of_six_does_not_verify():
    check = execution.hill_check(_hill_day(), _splits(2, 18, 1, 1, 2, 1, 0, 2))
    assert check["verified"] is False
    assert check["climbed_reps"] == 1


def test_chat_edit_drops_a_pace_target_from_an_uphill_step():
    """The chat path has no corrective retry, so the repair is mechanical."""
    day = {"date": TODAY.isoformat(), "workout_type": "intervals", "steps": [
        {"repeat": 6, "steps": [
            _step("work", terrain="uphill", target_pace="4:10",
                  target_hr_low=161, target_hr_high=172),
            _step("recovery", terrain="downhill"),
        ]},
    ]}
    out = planner._drop_uphill_pace(day)
    work = out["steps"][0]["steps"][0]
    assert work["target_pace"] is None
    assert (work["target_hr_low"], work["target_hr_high"]) == (161, 172)
    assert planner.terrain_target_violations([out]) == []


def test_chat_edit_leaves_flat_pace_targets_alone():
    day = {"date": TODAY.isoformat(), "workout_type": "intervals", "steps": [
        {"repeat": 6, "steps": [_step("work", target_pace="4:10")]},
    ]}
    assert planner._drop_uphill_pace(day)["steps"][0]["steps"][0]["target_pace"] == "4:10"


def test_no_hill_check_without_laps():
    assert execution.hill_check(_hill_day(), None) is None
    assert execution.hill_check(_hill_day(), []) is None


# --- the check follows attribution (ADR 0018) --------------------------------
#
# A hill_check asserts something to the athlete ("this was a hill session, but
# your reps show almost no climbing"), so it must only ever be made about a run
# that actually executed that prescription.

HILL_SERIES = {"t_s": [i * 30 for i in range(41)], "hr": [166] * 41}
HILL_SPLITS = [{"elevation_gain_m": g, "duration_s": 60}
               for g in (3, 18, 1, 20, 1, 17, 2, 19, 1, 21, 1, 18, 2, 4)]


def _hill_run(db, user_id, name="run"):
    a = Activity(id=1, user_id=user_id, date=TODAY, type="running", name=name,
                 distance_m=5000, duration_s=1200, series=HILL_SERIES,
                 splits=HILL_SPLITS)
    db.add(a)
    db.commit()
    return a


def _push_hill_day(db, user_id, **kw):
    day = _hill_day(user_id=user_id, garmin_workout_id="w123", **kw)
    db.add(day)
    db.commit()
    return day


def test_pushed_hill_session_gets_a_hill_check(db, user):
    _push_hill_day(db, user.id)
    a = _hill_run(db, user.id)
    res = execution.score_run(db, a, {"summaryDTO": {}, "metadataDTO": {}}, ZONES)
    assert res.hill and res.hill["verified"] is True


def test_a_free_run_on_a_hill_day_gets_no_hill_check(db, user):
    """The day prescribed hills, but this run was never attributed to it - so
    we have no standing to say anything about its terrain."""
    _hill_day(user_id=user.id)  # not pushed, not an override: no attribution
    a = _hill_run(db, user.id)
    res = execution.score_run(db, a, {"summaryDTO": {}, "metadataDTO": {}}, ZONES)
    assert res == execution.NOT_SCORED
    assert res.hill is None


def test_a_run_that_executed_a_different_workout_gets_no_hill_check(db, user):
    """Mismatch: the athlete ran the coach's original workout, not our edited
    hill day, so the climb is no evidence about the hill session."""
    # An accepted chat edit to a hill session that was never pushed: the watch
    # still holds Garmin's "Threshold", and the athlete ran that instead.
    version = PlanVersion(user_id=user.id, source="chat_edit", summary="hills")
    db.add(version)
    db.flush()
    db.add(_hill_day(user_id=user.id, version_id=version.id))
    db.add(PlanVersion(user_id=user.id, source="garmin_mirror", summary="mirror",
                       snapshot=[{"date": TODAY.isoformat(), "name": "Threshold",
                                  "training_effect": "LACTATE_THRESHOLD"}]))
    db.commit()
    a = _hill_run(db, user.id, name="Threshold")
    res = execution.score_run(
        db, a, {"summaryDTO": {"trainingEffectLabel": "TEMPO"},
                "metadataDTO": {"trainingPlanId": 45820109}}, ZONES)
    assert res.mismatch is not None
    assert res.hill is None
