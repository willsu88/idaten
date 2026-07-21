"""Eager morning review (ROADMAP Idea C decision): the daily job generates the
review right after the sync when recovery data is present, catch_up retries
while Garmin data is late, evaluate_today is idempotent so the scheduler and a
Today page load can never double-spend, and /dashboard/review reports
`data_overdue` so the UI can show the calm "no sleep data yet" state."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select

import app.planner as planner
import app.scheduler as scheduler
from app.models import DailyHealth, DailyReview, User
from app.planner import evaluate_today

from conftest import make_user

TODAY = dt.date(2026, 7, 17)

REVIEW_RESULT = {"coach_note": "Sleep looked fine — session stands.",
                 "should_propose": False, "proposal": None}


class StubReviewLLM:
    def __init__(self, result: dict):
        self.result = result
        self.calls = 0

    def complete_structured(self, system, messages, schema, name):
        self.calls += 1
        return self.result


def _use_llm(monkeypatch, stub):
    monkeypatch.setattr(planner, "make_client", lambda provider=None, **_kw: stub)


def _health(db, user_id, date, **kw):
    db.add(DailyHealth(user_id=user_id, date=date, **kw))
    db.commit()


# --- _eager_review: the gate --------------------------------------------------

def test_eager_review_generates_when_data_ready(db, user, monkeypatch):
    stub = StubReviewLLM(REVIEW_RESULT)
    _use_llm(monkeypatch, stub)
    _health(db, user.id, TODAY, sleep_score=80)

    scheduler._eager_review(db, user, TODAY)

    review = db.get(DailyReview, (user.id, TODAY))
    assert review is not None and review.state == "done_full"
    assert stub.calls == 1


def test_eager_review_skips_on_absent_data(db, user, monkeypatch):
    # No health row (or a bare one): no review row is even created, zero spend —
    # catch_up will retry later; the lazy page path stays intact.
    stub = StubReviewLLM(REVIEW_RESULT)
    _use_llm(monkeypatch, stub)

    scheduler._eager_review(db, user, TODAY)
    assert db.get(DailyReview, (user.id, TODAY)) is None
    assert stub.calls == 0

    _health(db, user.id, TODAY)  # bare row: sync ran before Garmin processed the night
    scheduler._eager_review(db, user, TODAY)
    assert db.get(DailyReview, (user.id, TODAY)) is None
    assert stub.calls == 0


def test_eager_review_skips_when_already_done(db, user, monkeypatch):
    stub = StubReviewLLM(REVIEW_RESULT)
    _use_llm(monkeypatch, stub)
    _health(db, user.id, TODAY, sleep_score=80)
    db.add(DailyReview(user_id=user.id, date=TODAY, state="done_structural",
                       coach_note="already reviewed"))
    db.commit()

    scheduler._eager_review(db, user, TODAY)
    assert stub.calls == 0


def test_eager_review_failure_is_swallowed(db, user, monkeypatch):
    # An LLM outage must never fail the sync job it rides on.
    _health(db, user.id, TODAY, sleep_score=80)

    def boom(*a, **kw):
        raise RuntimeError("llm down")

    monkeypatch.setattr(scheduler, "evaluate_today", boom)
    scheduler._eager_review(db, user, TODAY)  # must not raise


# --- evaluate_today: idempotency (scheduler + page load race) ------------------

def test_evaluate_today_is_idempotent(db, user, monkeypatch):
    stub = StubReviewLLM(REVIEW_RESULT)
    _use_llm(monkeypatch, stub)
    _health(db, user.id, TODAY, sleep_score=80)

    first = evaluate_today(db, user.id, TODAY)
    assert first.state == "done_full" and stub.calls == 1

    second = evaluate_today(db, user.id, TODAY)
    assert second.state == "done_full"
    assert stub.calls == 1  # the second caller returns the done review, no spend

    # The structural-fallback flag on an already-done review also spends nothing.
    third = evaluate_today(db, user.id, TODAY, allow_structural_fallback=True)
    assert third.state == "done_full" and stub.calls == 1


# --- catch_up retry: late Garmin data ------------------------------------------

def test_retry_pending_reviews_evaluates_once_data_lands(db, user, monkeypatch):
    # The plan-hour job ran but the night hadn't been processed. The retry
    # syncs (which finally lands the data) and the review is generated.
    today = dt.date.today()
    stub = StubReviewLLM(REVIEW_RESULT)
    _use_llm(monkeypatch, stub)
    monkeypatch.setattr(scheduler, "has_garmin", lambda u: True)

    synced: list[int] = []

    def fake_sync(user_id):
        synced.append(user_id)
        _health(db, user_id, today, sleep_score=74)
        return {"ok": True}

    monkeypatch.setattr(scheduler, "sync_only_job", fake_sync)

    scheduler._retry_pending_reviews()

    assert synced == [user.id]
    review = db.get(DailyReview, (user.id, today))
    assert review is not None and review.state == "done_full"
    assert stub.calls == 1

    # Next tick: review is done, nothing pending — no more syncs.
    scheduler._retry_pending_reviews()
    assert synced == [user.id]


# --- /dashboard/review: data_overdue -------------------------------------------

def _login(client, db, username="will"):
    from app.auth import ensure_admin

    make_user(db, username=username, password="secret1")
    ensure_admin()
    r = client.post("/api/auth/login", json={"username": username, "password": "secret1"})
    assert r.status_code == 200


def test_review_endpoint_reports_data_overdue(client, db, monkeypatch):
    from app.config import config

    _login(client, db)
    monkeypatch.setattr(config, "plan_hour", 7)

    # Shortly after plan_hour: waiting, not overdue.
    monkeypatch.setattr(scheduler, "now_local",
                        lambda: dt.datetime(2026, 7, 17, 8, 0))
    body = client.get("/api/dashboard/review").json()
    assert body["data_ready"] is False
    assert body["data_overdue"] is False

    # Well past plan_hour with still no data: the calm state.
    monkeypatch.setattr(scheduler, "now_local",
                        lambda: dt.datetime(2026, 7, 17, 9, 0))
    body = client.get("/api/dashboard/review").json()
    assert body["data_overdue"] is True


def test_review_endpoint_not_overdue_once_data_lands(client, db, monkeypatch):
    from app.config import config

    _login(client, db)
    monkeypatch.setattr(config, "plan_hour", 7)
    monkeypatch.setattr(scheduler, "now_local",
                        lambda: dt.datetime(2026, 7, 17, 11, 0))
    u = db.scalars(select(User)).first()
    _health(db, u.id, dt.date.today(), sleep_score=81)

    body = client.get("/api/dashboard/review").json()
    assert body["data_ready"] is True
    assert body["data_overdue"] is False
