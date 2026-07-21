"""Phase A foundation for the editor-above-the-DSW build: authoring mode
detection, the plan_authoring override setting, and the DailyReview artifact."""

from __future__ import annotations

import datetime as dt

from app.garmin.training_plan import has_active_plan
from app.models import DailyReview, REVIEW_STATES, TrainingPlan
from app.planner import plan_mode
from app.settings_store import get_settings, put_settings

TODAY = dt.date(2026, 7, 17)


def _mirror_plan(db, user_id, start, end):
    db.add(TrainingPlan(
        user_id=user_id, garmin_plan_id=1, name="Test Plan",
        start_date=start, end_date=end, duration_weeks=25,
        phases=[], upcoming_tasks=[],
    ))
    db.commit()


# --- authoring mode -------------------------------------------------------

def test_author_mode_without_garmin_plan(db, user):
    assert plan_mode(db, user.id, TODAY) == "author"


def test_editor_mode_with_active_garmin_plan(db, user):
    _mirror_plan(db, user.id, TODAY - dt.timedelta(days=50), TODAY + dt.timedelta(days=100))
    assert has_active_plan(db, user.id, TODAY) is True
    assert plan_mode(db, user.id, TODAY) == "editor"


def test_override_forces_author_even_with_plan(db, user):
    _mirror_plan(db, user.id, TODAY - dt.timedelta(days=50), TODAY + dt.timedelta(days=100))
    put_settings(db, user.id, {"plan_authoring": "author"})
    assert plan_mode(db, user.id, TODAY) == "author"


def test_expired_plan_is_not_active(db, user):
    _mirror_plan(db, user.id, TODAY - dt.timedelta(days=200), TODAY - dt.timedelta(days=1))
    assert has_active_plan(db, user.id, TODAY) is False
    assert plan_mode(db, user.id, TODAY) == "author"


def test_active_plan_boundaries_inclusive(db, user):
    _mirror_plan(db, user.id, TODAY, TODAY)  # single-day window covering today
    assert has_active_plan(db, user.id, TODAY) is True
    assert has_active_plan(db, user.id, TODAY + dt.timedelta(days=1)) is False


# --- plan_authoring setting ----------------------------------------------

def test_plan_authoring_defaults_to_auto(db, user):
    assert get_settings(db, user.id)["plan_authoring"] == "auto"


def test_plan_authoring_rejects_invalid(db, user):
    put_settings(db, user.id, {"plan_authoring": "nonsense"})
    assert get_settings(db, user.id)["plan_authoring"] == "auto"


def test_plan_authoring_accepts_author(db, user):
    put_settings(db, user.id, {"plan_authoring": "author"})
    assert get_settings(db, user.id)["plan_authoring"] == "author"


# --- DailyReview artifact --------------------------------------------------

def test_daily_review_roundtrip(db, user):
    db.add(DailyReview(
        user_id=user.id, date=TODAY, state="done_full", mode="editor",
        coach_note="HRV 36 vs ~50 baseline — I eased today's threshold.",
    ))
    db.commit()
    row = db.get(DailyReview, (user.id, TODAY))
    assert row.state == "done_full"
    assert row.mode == "editor"
    assert row.proposal_id is None
    assert "HRV" in row.coach_note


def test_review_states_constant():
    assert REVIEW_STATES == ("pending_data", "done_full", "done_structural")
