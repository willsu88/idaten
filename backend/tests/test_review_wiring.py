"""Phase C wiring: the scheduled job does data + editor-base only (no LLM), and
the lazy /dashboard/evaluate + /dashboard/review endpoints drive the review."""

from __future__ import annotations

import datetime as dt

import app.planner as planner
import app.scheduler as scheduler
from app.models import DailyHealth, PlanDay, TrainingPlan

TODAY = dt.date.today()  # the wiring reads dt.date.today() internally


def _no_llm(monkeypatch):
    def boom(provider=None):
        raise AssertionError("LLM must not be called here")
    monkeypatch.setattr(planner, "make_client", boom)


def _active_plan(db, user_id, tasks):
    db.add(TrainingPlan(
        user_id=user_id, garmin_plan_id=1, name="Plan",
        start_date=TODAY - dt.timedelta(days=50), end_date=TODAY + dt.timedelta(days=100),
        duration_weeks=25, phases=[], upcoming_tasks=tasks,
    ))
    db.commit()


class StubReviewLLM:
    def __init__(self, result):
        self.result = result
        self.calls = 0

    def complete_structured(self, system, messages, schema, name):
        self.calls += 1
        return self.result


# --- scheduled job: no LLM -----------------------------------------------

def test_scheduler_editor_materializes_base_without_llm(db, user, monkeypatch):
    _active_plan(db, user.id, tasks=[
        {"date": TODAY.isoformat(), "name": "Threshold",
         "training_effect": "LACTATE_THRESHOLD", "rest_day": False,
         "duration_min": 38, "description": "18:00@172bpm"},
    ])
    monkeypatch.setattr(scheduler, "run_sync", lambda d, u: TODAY)
    monkeypatch.setattr(scheduler, "push_days", lambda d, rows: None)
    _no_llm(monkeypatch)  # scheduled job must never spend an LLM call
    result = scheduler._job_for_user(db, user, "daily_job")
    assert result["plan_updated"] is True
    base = db.get(PlanDay, (user.id, TODAY))
    assert base is not None and base.workout_type == "tempo"


def test_scheduler_author_only_syncs(db, user, monkeypatch):
    monkeypatch.setattr(scheduler, "run_sync", lambda d, u: TODAY)
    _no_llm(monkeypatch)
    result = scheduler._job_for_user(db, user, "daily_job")
    assert result["plan_updated"] is False
    assert db.query(PlanDay).count() == 0  # author weeks are written lazily


# --- lazy endpoints ------------------------------------------------------

def _login(client):
    assert client.post("/api/auth/login",
                       json={"username": "will", "password": "secret1"}).status_code == 200


def test_evaluate_pending_data_spends_no_llm(client, db, user, monkeypatch):
    _no_llm(monkeypatch)
    _login(client)
    r = client.post("/api/dashboard/evaluate", json={})
    assert r.status_code == 200
    assert r.json()["state"] == "pending_data"


def test_review_endpoint_reports_data_readiness(client, db, user):
    _login(client)
    assert client.get("/api/dashboard/review").json()["data_ready"] is False
    db.add(DailyHealth(user_id=user.id, date=TODAY, sleep_score=80, hrv=50, hrv_baseline=50))
    db.commit()
    assert client.get("/api/dashboard/review").json()["data_ready"] is True


def test_evaluate_idempotent_one_llm_call(client, db, user, monkeypatch):
    _active_plan(db, user.id, tasks=[  # editor mode → single review call
        {"date": TODAY.isoformat(), "name": "Base", "training_effect": "AEROBIC_BASE",
         "rest_day": False, "duration_min": 40, "description": "145bpm"},
    ])
    db.add(DailyHealth(user_id=user.id, date=TODAY, sleep_score=80, hrv=50, hrv_baseline=50))
    db.commit()
    stub = StubReviewLLM({"coach_note": "On track.", "should_propose": False, "proposal": None})
    monkeypatch.setattr(planner, "make_client", lambda provider=None, **_kw: stub)
    _login(client)
    first = client.post("/api/dashboard/evaluate", json={})
    second = client.post("/api/dashboard/evaluate", json={})
    assert first.json()["state"] == "done_full"
    assert second.json()["coach_note"] == "On track."
    assert stub.calls == 1  # the second load returns the cached review, no new call
