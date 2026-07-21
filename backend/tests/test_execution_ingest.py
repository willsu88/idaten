"""Attribution + score-source decision (app.execution.score_run) and the
prescription-segment builders. DB-backed (PlanDay lookup); no Garmin calls.
"""
from __future__ import annotations

import datetime as dt

from app import execution
from app.models import Activity, PlanDay, PlanVersion

TODAY = dt.date(2026, 7, 16)

# Garmin per-athlete zones (as hr_zones_from_garmin would return).
ZONES = {"z1": [130, 144], "z2": [144, 161], "z3": [161, 173],
         "z4": [173, 192], "z5": [192, 212]}

# A flat HR series sitting in z2 for 20 min.
SERIES_Z2 = {"t_s": [i * 30 for i in range(41)], "hr": [150] * 41}


def _run(db, user_id, *, series=SERIES_Z2, splits=None):
    a = Activity(id=1, user_id=user_id, date=TODAY, type="running", name="run",
                 distance_m=5000, duration_s=1200, series=series, splits=splits)
    db.add(a)
    db.commit()
    return a


def _coach_full(te="AEROBIC_BASE", compliance=None):
    s = {"trainingEffectLabel": te}
    if compliance is not None:
        s["directWorkoutComplianceScore"] = compliance
    return {"summaryDTO": s, "metadataDTO": {"trainingPlanId": 45820109}}


def _free_full():
    return {"summaryDTO": {"trainingEffectLabel": "AEROBIC_BASE"}, "metadataDTO": {}}


# --- attribution ----------------------------------------------------------

def test_free_run_is_not_scored(db, user):
    a = _run(db, user.id, splits=[{"intensity": "INTERVAL", "duration_s": 1200}])
    assert execution.score_run(db, a, _free_full(), ZONES) == (None, None, None)


def test_coach_run_is_attributed_and_computed(db, user):
    a = _run(db, user.id, splits=[{"intensity": "INTERVAL", "duration_s": 1200}])
    score, source, breakdown = execution.score_run(db, a, _coach_full(), ZONES)
    assert source == "idaten"          # 165-style: no compliance score -> compute
    assert score == 100                # HR 150 dead-centre in z2 [144,161]
    assert breakdown and breakdown[0]["label"] == "INTERVAL"


def test_garmin_score_is_pulled_when_present(db, user):
    a = _run(db, user.id, splits=[{"intensity": "INTERVAL", "duration_s": 1200}])
    score, source, breakdown = execution.score_run(
        db, a, _coach_full(compliance=73), ZONES)
    assert (score, source, breakdown) == (73, "garmin", None)  # 255-style: pull


def test_idaten_pushed_day_is_attributed(db, user):
    # No coach trainingPlanId, but Idaten pushed a structured HR workout that day.
    db.add(PlanDay(user_id=user.id, date=TODAY, workout_type="easy_run",
                   title="Easy", duration_min=20, target_hr_low=144,
                   target_hr_high=161, garmin_workout_id="w123"))
    db.commit()
    a = _run(db, user.id)
    score, source, _ = execution.score_run(db, a, _free_full(), ZONES)
    assert source == "idaten" and score == 100  # scored vs our own prescription


def _idaten_edit_day(db, user_id):
    """An accepted Idaten edit (chat_edit) for TODAY: easy run, HR 144-161."""
    v = PlanVersion(user_id=user_id, source="chat_edit", summary="ease off")
    db.add(v)
    db.flush()
    db.add(PlanDay(user_id=user_id, date=TODAY, workout_type="easy_run", title="Easy",
                   duration_min=20, target_hr_low=144, target_hr_high=161,
                   version_id=v.id))
    db.commit()


def test_idaten_override_scores_against_idaten_not_coach(db, user):
    # Editor mode: Garmin still tags the run (trainingPlanId present) with a TEMPO
    # effect, but the athlete accepted an Idaten edit to easy -> score vs Idaten's
    # easy [144,161] (HR 150 -> 100), NOT the coach z3 tempo band.
    _idaten_edit_day(db, user.id)
    a = _run(db, user.id, splits=[{"intensity": "INTERVAL", "duration_s": 1200}])
    score, source, _ = execution.score_run(db, a, _coach_full(te="TEMPO"), ZONES)
    assert source == "idaten" and score == 100


def test_idaten_override_ignores_garmin_compliance_when_not_pushed(db, user):
    # A non-pushed edit: the watch still holds Garmin's workout, so its compliance
    # score is against the wrong target -> compute vs Idaten's plan, don't pull.
    _idaten_edit_day(db, user.id)
    a = _run(db, user.id, splits=[{"intensity": "INTERVAL", "duration_s": 1200}])
    score, source, _ = execution.score_run(
        db, a, _coach_full(te="TEMPO", compliance=30), ZONES)
    assert source == "idaten" and score == 100


def test_rest_day_push_absent_is_not_scored(db, user):
    # A PlanDay with no pushed workout is not an attribution signal.
    db.add(PlanDay(user_id=user.id, date=TODAY, workout_type="rest", title="Rest"))
    db.commit()
    a = _run(db, user.id)
    assert execution.score_run(db, a, _free_full(), ZONES) == (None, None, None)


# --- segment builders -----------------------------------------------------

def test_coach_segments_derive_per_lap(db, user):
    a = _run(db, user.id)
    splits = [
        {"intensity": "WARMUP", "duration_s": 300},
        {"intensity": "INTERVAL", "duration_s": 600},
        {"intensity": "COOLDOWN", "duration_s": 300},
    ]
    segs = execution._coach_segments(splits, "TEMPO", ZONES, a)
    assert [s["label"] for s in segs] == ["WARMUP", "INTERVAL", "COOLDOWN"]
    assert segs[0]["low"] == 130                 # warmup -> z1
    assert segs[1]["low"] == 161                 # tempo work -> z3 [161,173]


def test_coach_segments_fallback_whole_run(db, user):
    a = _run(db, user.id)  # duration_s 1200
    segs = execution._coach_segments([], "AEROBIC_BASE", ZONES, a)  # no laps
    assert len(segs) == 1
    assert segs[0]["duration_s"] == 1200 and segs[0]["low"] == 144   # z2 work zone


def test_mark_day_completed_only_flips_planned(db, user):
    # planned -> completed
    db.add(PlanDay(user_id=user.id, date=TODAY, workout_type="long_run",
                   title="Long", status="planned"))
    db.commit()
    execution.mark_day_completed(db, user.id, TODAY)
    db.commit()
    assert db.get(PlanDay, (user.id, TODAY)).status == "completed"

    # a skipped day is history — never touched
    other = dt.date(2026, 7, 15)
    db.add(PlanDay(user_id=user.id, date=other, workout_type="tempo",
                   title="Tempo", status="skipped"))
    db.commit()
    execution.mark_day_completed(db, user.id, other)
    db.commit()
    assert db.get(PlanDay, (user.id, other)).status == "skipped"

    # no plan day for the date -> no-op, no error
    execution.mark_day_completed(db, user.id, dt.date(2026, 7, 1))


def test_coach_segments_ignores_laps_without_intensity(db, user):
    # Laps cached before the intensity field existed must NOT all be scored as
    # work (that would zero a warmup); fall back to the whole-run estimate.
    a = _run(db, user.id)
    splits = [{"duration_s": 300}, {"duration_s": 900}]  # no "intensity"
    segs = execution._coach_segments(splits, "TEMPO", ZONES, a)
    assert len(segs) == 1 and segs[0]["duration_s"] == 1200   # whole-run fallback


def test_idaten_segments_structured_repeat(db, user):
    day = PlanDay(user_id=user.id, date=TODAY, workout_type="intervals",
                  title="6x800", steps=[
                      {"repeat": 1, "steps": [{"kind": "warmup", "duration_min": 10,
                                               "target_hr_low": 130, "target_hr_high": 144}]},
                      {"repeat": 3, "steps": [{"kind": "work", "duration_min": 4,
                                               "target_hr_low": 173, "target_hr_high": 192}]},
                  ])
    segs = execution._idaten_segments(day, ZONES)
    assert len(segs) == 4                         # 1 warmup + 3 repeated work reps
    assert segs[1]["low"] == 173 and segs[1]["duration_s"] == 240
