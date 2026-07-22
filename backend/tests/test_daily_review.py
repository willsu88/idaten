"""Phase B: the daily review brain — structural signals, the shared proposal
helper, and evaluate_today's data gate + two-branch output."""

from __future__ import annotations

import datetime as dt

import app.planner as planner
from app.metrics import structural_signals
from app.models import DailyHealth, DailyReview, PendingEdit, PlanDay, TrainingPlan
from app.planner import create_pending_edit, evaluate_today, plan_mode

TODAY = dt.date(2026, 7, 17)


class StubReviewLLM:
    """Returns a fixed structured result and records whether it was called."""

    def __init__(self, result: dict):
        self.result = result
        self.calls = 0
        self.seen: dict | None = None

    def complete_structured(self, system, messages, schema, name):
        self.calls += 1
        self.seen = {"system": system, "messages": messages, "name": name}
        return self.result


def _use_llm(monkeypatch, stub):
    monkeypatch.setattr(planner, "make_client", lambda provider=None, **_kw: stub)


def _health(db, user_id, date, **kw):
    db.add(DailyHealth(user_id=user_id, date=date, **kw))
    db.commit()


def _active_plan(db, user_id, tasks=None):
    db.add(TrainingPlan(
        user_id=user_id, garmin_plan_id=1, name="Plan",
        start_date=TODAY - dt.timedelta(days=50), end_date=TODAY + dt.timedelta(days=100),
        duration_weeks=25, phases=[], upcoming_tasks=tasks or [],
    ))
    db.commit()


# --- structural signals ---------------------------------------------------

def test_structural_signals_flags_three_hard_in_a_row():
    # The founding scenario: three threshold days back to back.
    days = [
        {"date": "2026-07-17", "hard": True, "rest": False},
        {"date": "2026-07-18", "hard": True, "rest": False},
        {"date": "2026-07-19", "hard": True, "rest": False},
        {"date": "2026-07-20", "hard": False, "rest": True},
    ]
    sig = structural_signals(days)
    assert sig["hard_day_count"] == 3
    assert sig["max_consecutive_hard_days"] == 3
    assert sig["min_gap_between_hard_days"] == 1


def test_structural_signals_well_spaced_week():
    days = [
        {"date": "2026-07-17", "hard": True, "rest": False},
        {"date": "2026-07-18", "hard": False, "rest": True},
        {"date": "2026-07-19", "hard": False, "rest": False},
        {"date": "2026-07-20", "hard": True, "rest": False},
    ]
    sig = structural_signals(days)
    assert sig["max_consecutive_hard_days"] == 1
    assert sig["min_gap_between_hard_days"] == 3


def test_structural_signals_empty():
    sig = structural_signals([])
    assert sig["hard_day_count"] == 0
    assert sig["min_gap_between_hard_days"] is None


# --- shared proposal helper ----------------------------------------------

def test_create_pending_edit_supersedes_prior(db, user):
    db.add(PendingEdit(user_id=user.id, summary="old", status="pending", changes=[], current=[]))
    db.commit()
    edit, error = create_pending_edit(
        db, user.id,
        [{"date": TODAY.isoformat(), "workout_type": "rest", "title": "Rest",
          "description": "", "rationale": "recovery", "target_pace": None}],
        "ease today", "HRV low", TODAY,
    )
    assert error is None and edit is not None
    superseded = [e for e in db.query(PendingEdit).all() if e.summary == "old"][0]
    assert superseded.status == "superseded"
    assert edit.status == "pending"


def test_create_pending_edit_empty_days_errors(db, user):
    edit, error = create_pending_edit(db, user.id, [], "x", "y", TODAY)
    assert edit is None and error["error"] == "no days provided"


# --- evaluate_today: data gate -------------------------------------------

def test_pending_data_when_no_health_and_no_llm(db, user, monkeypatch):
    stub = StubReviewLLM({"coach_note": "x", "should_propose": False, "proposal": None})
    _use_llm(monkeypatch, stub)
    review = evaluate_today(db, user.id, TODAY)
    assert review.state == "pending_data"
    assert stub.calls == 0                 # never spends an LLM call on absent data
    assert review.coach_note == ""
    assert review.coach is None            # no note yet — no author to stamp


def test_structural_fallback_runs_without_health(db, user, monkeypatch):
    stub = StubReviewLLM({"coach_note": "Based on recent training.",
                          "should_propose": False, "proposal": None})
    _use_llm(monkeypatch, stub)
    review = evaluate_today(db, user.id, TODAY, allow_structural_fallback=True)
    assert review.state == "done_structural"
    assert stub.calls == 1
    assert review.coach == "default"       # authoring persona frozen at write time


def test_review_stamps_active_coach_persona(db, user, monkeypatch):
    # The note is attributed to the coach selected WHEN it was written; a later
    # coach switch must not re-attribute it (the UI renders from this stamp).
    from app.settings_store import put_settings
    put_settings(db, user.id, {"coach_style": "chill"})
    stub = StubReviewLLM({"coach_note": "Nice and easy today.",
                          "should_propose": False, "proposal": None})
    _use_llm(monkeypatch, stub)
    review = evaluate_today(db, user.id, TODAY, allow_structural_fallback=True)
    assert review.coach == "chill"
    put_settings(db, user.id, {"coach_style": "strict"})
    assert db.get(DailyReview, (user.id, TODAY)).coach == "chill"


# --- evaluate_today: author + editor branches ----------------------------

def test_author_review_authors_week_and_notes(db, user, monkeypatch):
    # Author mode (no Garmin plan): evaluate_today writes the week via
    # generate_plan and derives the coach_note from its adjustment summary.
    _health(db, user.id, TODAY, sleep_score=80, hrv=50, hrv_baseline=50)
    assert plan_mode(db, user.id, TODAY) == "author"
    plan_result = {
        "adjustment_note": "Easy week to rebuild after the block.",
        "days": [{
            "date": TODAY.isoformat(), "workout_type": "easy_run", "title": "Easy run",
            "description": "relaxed", "duration_min": 40, "distance_km": None,
            "target_pace": None, "target_hr_low": None, "target_hr_high": None,
            "steps": None, "rationale": "rebuild aerobic base",
        }],
    }
    _use_llm(monkeypatch, StubReviewLLM(plan_result))
    review = evaluate_today(db, user.id, TODAY)
    assert review.state == "done_full"
    assert review.mode == "author"
    assert review.proposal_id is None
    assert review.coach_note == "Easy week to rebuild after the block."
    assert review.coach == "default"
    authored = db.query(PlanDay).filter_by(user_id=user.id, date=TODAY).one()
    assert authored.workout_type == "easy_run"
    assert db.query(PendingEdit).count() == 0


def test_editor_review_creates_linked_proposal(db, user, monkeypatch):
    _active_plan(db, user.id, tasks=[
        {"date": TODAY.isoformat(), "week": 8, "name": "Threshold",
         "training_effect": "LACTATE_THRESHOLD", "rest_day": False, "duration_min": 38},
    ])
    _health(db, user.id, TODAY, sleep_score=55, hrv=36, hrv_baseline=50)
    assert plan_mode(db, user.id, TODAY) == "editor"
    stub = StubReviewLLM({
        "coach_note": "HRV 28% below baseline — easing today.",
        "should_propose": True,
        "proposal": {
            "summary": "Ease today's threshold to easy",
            "rationale": "HRV 36 vs 50 baseline on a threshold day",
            "days": [{"date": TODAY.isoformat(), "workout_type": "easy_run",
                      "title": "Easy run", "description": "keep it relaxed",
                      "rationale": "recovery", "target_pace": None,
                      "target_hr_low": None, "target_hr_high": None,
                      "duration_min": 30, "distance_km": None, "steps": None}],
        },
    })
    _use_llm(monkeypatch, stub)
    review = evaluate_today(db, user.id, TODAY)
    assert review.state == "done_full"
    assert review.mode == "editor"
    assert review.proposal_id is not None
    edit = db.get(PendingEdit, review.proposal_id)
    assert edit.status == "pending"
    assert edit.changes[0]["workout_type"] == "easy_run"


def test_editor_review_refreshes_garmin_plan_before_grounding(db, user, monkeypatch):
    # The review re-syncs Garmin's adaptive plan + re-materializes first, so it
    # grounds on Garmin's LATEST adaptation (which re-plans through the day).
    _active_plan(db, user.id, tasks=[
        {"date": TODAY.isoformat(), "week": 8, "name": "Base",
         "training_effect": "AEROBIC_BASE", "rest_day": False, "duration_min": 40},
    ])
    _health(db, user.id, TODAY, sleep_score=80, hrv=50, hrv_baseline=50)
    order: list[str] = []
    import app.garmin.client as gclient
    import app.garmin.training_plan as gtp
    monkeypatch.setattr(gclient, "has_garmin", lambda u: True)
    monkeypatch.setattr(gclient, "get_garmin", lambda u: object())
    monkeypatch.setattr(gtp, "sync_training_plan", lambda db, uid, g: order.append("sync"))
    monkeypatch.setattr(planner, "materialize_coach_plan",
                        lambda db, uid, today=None: order.append("materialize") or [])
    _use_llm(monkeypatch, StubReviewLLM({"coach_note": "on track", "should_propose": False}))

    evaluate_today(db, user.id, TODAY)
    assert order == ["sync", "materialize"]  # fresh Garmin plan before the LLM reads it


def test_editor_review_survives_garmin_refresh_failure(db, user, monkeypatch):
    # A Garmin hiccup during the refresh must not block the review.
    _active_plan(db, user.id, tasks=[
        {"date": TODAY.isoformat(), "name": "Base", "training_effect": "AEROBIC_BASE",
         "rest_day": False, "duration_min": 40},
    ])
    _health(db, user.id, TODAY, sleep_score=80, hrv=50, hrv_baseline=50)
    import app.garmin.client as gclient
    import app.garmin.training_plan as gtp

    def boom(*a, **k):
        raise RuntimeError("garmin down")

    monkeypatch.setattr(gclient, "has_garmin", lambda u: True)
    monkeypatch.setattr(gclient, "get_garmin", lambda u: object())
    monkeypatch.setattr(gtp, "sync_training_plan", boom)
    _use_llm(monkeypatch, StubReviewLLM({"coach_note": "on track", "should_propose": False}))

    review = evaluate_today(db, user.id, TODAY)
    assert review.state == "done_full"  # review still completed on the existing mirror


def test_review_reuses_daily_row(db, user, monkeypatch):
    # A second same-day call returns the one existing row untouched — the
    # one-LLM-call-per-day contract now lives inside evaluate_today (idempotent
    # for the scheduler's eager pass + the Today page's lazy trigger).
    _active_plan(db, user.id)  # editor mode → review flow uses the stub's note
    _health(db, user.id, TODAY, sleep_score=80, hrv=50, hrv_baseline=50)
    stub = StubReviewLLM({"coach_note": "first", "should_propose": False, "proposal": None})
    _use_llm(monkeypatch, stub)
    evaluate_today(db, user.id, TODAY)
    stub.result = {"coach_note": "second", "should_propose": False, "proposal": None}
    evaluate_today(db, user.id, TODAY)
    rows = db.query(DailyReview).filter_by(user_id=user.id, date=TODAY).all()
    assert len(rows) == 1
    assert rows[0].coach_note == "first"  # done review returned as-is, no re-spend
    assert stub.calls == 1
