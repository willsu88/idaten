"""Phase 4 (execution signal into the review) + Phase 3 (attribution prompt):
the recent-execution signal, prompt eligibility, confirm-scoring, endpoint.
"""
from __future__ import annotations

import datetime as dt

from app import execution, metrics
from app.models import Activity, PlanDay, TrainingPlan

TODAY = dt.date(2026, 7, 16)
ZONES = {"z1": [130, 144], "z2": [144, 161], "z3": [161, 173],
         "z4": [173, 192], "z5": [192, 212]}
SERIES_Z2 = {"t_s": [i * 30 for i in range(41)], "hr": [150] * 41}


def _run(db, user_id, aid, date, *, score=None, source=None, attributed=None,
         series=SERIES_Z2, splits=None, type_="running"):
    a = Activity(id=aid, user_id=user_id, date=date, type=type_, name="run",
                 distance_m=5000, duration_s=1200, series=series, splits=splits,
                 execution_score=score, execution_score_source=source,
                 execution_attributed=attributed)
    db.add(a)
    db.commit()
    return a


# --- Phase 4: execution_signals -------------------------------------------

def test_signals_none_without_scored_runs(db, user):
    _run(db, user.id, 1, TODAY)  # unscored
    assert metrics.execution_signals(db, user.id, TODAY) is None


def test_signals_summarise_recent_scores(db, user):
    _run(db, user.id, 1, TODAY, score=40, source="idaten")           # newest
    _run(db, user.id, 2, TODAY - dt.timedelta(days=2), score=44, source="idaten")
    _run(db, user.id, 3, TODAY - dt.timedelta(days=4), score=80, source="garmin")
    sig = metrics.execution_signals(db, user.id, TODAY)
    assert sig["count"] == 3
    assert sig["avg_score"] == 55                 # (40+44+80)/3
    assert sig["recent"][0]["score"] == 40        # newest first
    assert sig["low_streak"] == 2                 # two most-recent below 50


def test_low_streak_breaks_on_a_good_run(db, user):
    _run(db, user.id, 1, TODAY, score=85, source="garmin")           # newest = good
    _run(db, user.id, 2, TODAY - dt.timedelta(days=1), score=30, source="idaten")
    assert metrics.execution_signals(db, user.id, TODAY)["low_streak"] == 0


# --- Phase 3: prompt eligibility ------------------------------------------

def _coach_plan(db, user_id, te="LACTATE_THRESHOLD", name="Threshold"):
    db.add(TrainingPlan(
        user_id=user_id, garmin_plan_id=1, name="P", start_date=TODAY,
        end_date=TODAY + dt.timedelta(days=100), duration_weeks=25, phases=[],
        upcoming_tasks=[{"date": TODAY.isoformat(), "name": name,
                         "training_effect": te, "rest_day": False}]))
    db.commit()


def test_prompt_shown_for_unscored_run_on_a_planned_day(db, user):
    _coach_plan(db, user.id)
    a = _run(db, user.id, 1, TODAY)  # unscored, undecided
    assert execution.prompt_label(db, a) == "Threshold"


def test_no_prompt_when_already_scored(db, user):
    _coach_plan(db, user.id)
    a = _run(db, user.id, 1, TODAY, score=70, source="garmin")
    assert execution.prompt_label(db, a) is None


def test_no_prompt_when_already_declined(db, user):
    _coach_plan(db, user.id)
    a = _run(db, user.id, 1, TODAY, attributed=False)
    assert execution.prompt_label(db, a) is None


def test_no_prompt_without_a_planned_workout(db, user):
    a = _run(db, user.id, 1, TODAY)  # no coach plan, no PlanDay
    assert execution.prompt_label(db, a) is None


def test_no_prompt_when_a_sibling_run_already_covers_the_day(db, user):
    _coach_plan(db, user.id)
    _run(db, user.id, 1, TODAY, score=88, source="garmin")   # the coach run, scored
    other = _run(db, user.id, 2, TODAY)                       # a second, free run
    assert execution.prompt_label(db, other) is None


# --- Phase 3: confirm-scoring ---------------------------------------------

def test_score_confirmed_against_coach_te_label(db, user):
    _coach_plan(db, user.id, te="AEROBIC_BASE")
    a = _run(db, user.id, 1, TODAY)  # HR 150, whole-run fallback vs z2 [144,161]
    from app.settings_store import put_garmin_hr_zones
    put_garmin_hr_zones(db, user.id, ZONES, TODAY.isoformat())
    score, breakdown = execution.score_confirmed(db, a, ZONES)
    assert score == 100 and breakdown


def test_score_confirmed_against_idaten_planday(db, user):
    db.add(PlanDay(user_id=user.id, date=TODAY, workout_type="easy_run",
                   title="Easy", duration_min=20, target_hr_low=144,
                   target_hr_high=161))
    db.commit()
    a = _run(db, user.id, 1, TODAY)
    score, _ = execution.score_confirmed(db, a, ZONES)
    assert score == 100


# --- Phase 3: endpoint ----------------------------------------------------

def _login(client):
    assert client.post("/api/auth/login",
                       json={"username": "will", "password": "secret1"}).status_code == 200


def test_attribution_endpoint_yes_scores_no_declines(db, user, client):
    _login(client)
    from app.settings_store import put_garmin_hr_zones
    put_garmin_hr_zones(db, user.id, ZONES, TODAY.isoformat())
    _coach_plan(db, user.id, te="AEROBIC_BASE")
    a = _run(db, user.id, 1, TODAY)

    r = client.post(f"/api/activities/{a.id}/attribution", json={"attempted": True})
    assert r.status_code == 200 and r.json()["execution_score"] == 100
    db.refresh(a)
    assert a.execution_attributed is True and a.execution_score == 100

    r = client.post(f"/api/activities/{a.id}/attribution", json={"attempted": False})
    assert r.status_code == 200
    db.refresh(a)
    assert a.execution_attributed is False and a.execution_score is None
