"""Weekly summary (fifth coach call site) — see CONTEXT.md and docs/adr/0002.

Seams under test: the `weekly` module's public functions (week bounds,
evaluate_week) and the HTTP endpoints, mirroring test_daily_review.py's
stubbed-LLM pattern. The LLM is always stubbed; `pytest -m eval` land is
elsewhere.
"""

from __future__ import annotations

import datetime as dt

from app import weekly


class StubWeeklyLLM:
    def __init__(self, result: dict):
        self.result = result
        self.calls = 0
        self.last_system = None
        self.last_messages = None

    def complete_structured(self, system, messages, schema, name):
        self.calls += 1
        self.last_system = system
        self.last_messages = messages
        return self.result


def _use_llm(monkeypatch, stub):
    monkeypatch.setattr(weekly, "make_client", lambda provider=None, **_kw: stub)


# --- summary week boundaries (CONTEXT.md: fixed Mon-Sun, app timezone) --------

def test_week_start_is_monday_for_every_weekday():
    # 2026-07-20 is a Monday; every day of that week maps back to it.
    monday = dt.date(2026, 7, 20)
    for offset in range(7):
        assert weekly.week_start_of(monday + dt.timedelta(days=offset)) == monday


def test_week_start_of_a_monday_is_itself():
    assert weekly.week_start_of(dt.date(2026, 7, 27)) == dt.date(2026, 7, 27)


def test_last_closed_week_on_monday_is_the_week_that_just_ended():
    # On Monday 2026-07-27, the last closed summary week is Mon 20 - Sun 26.
    assert weekly.last_closed_week(dt.date(2026, 7, 27)) == dt.date(2026, 7, 20)


def test_last_closed_week_midweek_is_the_previous_full_week():
    # On Thursday 2026-07-23 the running week (starting the 20th) is NOT closed.
    assert weekly.last_closed_week(dt.date(2026, 7, 23)) == dt.date(2026, 7, 13)


# --- evaluate_week ------------------------------------------------------------

MONDAY = dt.date(2026, 7, 27)          # "today" in these tests
CLOSED_WEEK = dt.date(2026, 7, 20)     # the week that ended yesterday


def _run(db, user_id, date, score=None, minutes=40, km=8.0):
    from app.models import Activity
    a = Activity(user_id=user_id, date=date, type="running", name="Morning Run",
                 distance_m=km * 1000, duration_s=minutes * 60,
                 execution_score=score)
    db.add(a)
    db.commit()
    return a


def test_evaluate_week_writes_summary_and_is_idempotent(db, user, monkeypatch):
    _run(db, user.id, CLOSED_WEEK + dt.timedelta(days=2), score=82)
    stub = StubWeeklyLLM({"summary": "A strong, honest week of work."})
    _use_llm(monkeypatch, stub)

    s = weekly.evaluate_week(db, user.id, CLOSED_WEEK, today=MONDAY)
    assert s.coach_note == "A strong, honest week of work."
    assert s.week_start == CLOSED_WEEK
    assert s.coach == "default"          # persona stamped at generation time
    assert s.prompt_version              # provenance for the quality loop
    assert s.snapshot is not None

    again = weekly.evaluate_week(db, user.id, CLOSED_WEEK, today=MONDAY)
    assert stub.calls == 1               # one LLM call per week, ever
    assert again.coach_note == s.coach_note


def test_evaluate_week_refuses_an_unclosed_week(db, user, monkeypatch):
    stub = StubWeeklyLLM({"summary": "nope"})
    _use_llm(monkeypatch, stub)
    import pytest
    with pytest.raises(ValueError):
        weekly.evaluate_week(db, user.id, MONDAY, today=MONDAY)
    assert stub.calls == 0


def test_evaluate_week_refuses_backfill_of_older_weeks(db, user, monkeypatch):
    # Forward-only (ADR 0002): only the most recently closed week is generatable.
    stub = StubWeeklyLLM({"summary": "nope"})
    _use_llm(monkeypatch, stub)
    import pytest
    with pytest.raises(ValueError):
        weekly.evaluate_week(db, user.id, CLOSED_WEEK - dt.timedelta(days=7),
                             today=MONDAY)
    assert stub.calls == 0


def test_evaluate_week_normalizes_any_date_to_its_monday(db, user, monkeypatch):
    stub = StubWeeklyLLM({"summary": "Anchored right."})
    _use_llm(monkeypatch, stub)
    s = weekly.evaluate_week(db, user.id, CLOSED_WEEK + dt.timedelta(days=3),
                             today=MONDAY)
    assert s.week_start == CLOSED_WEEK


def test_empty_week_still_gets_a_summary(db, user, monkeypatch):
    # CONTEXT.md: always written, including for a week with zero activities.
    stub = StubWeeklyLLM({"summary": "A quiet week - let's ease back in."})
    _use_llm(monkeypatch, stub)
    s = weekly.evaluate_week(db, user.id, CLOSED_WEEK, today=MONDAY)
    assert s.coach_note.startswith("A quiet week")
    assert stub.calls == 1


def test_snapshot_carries_previous_week_summary_for_trend(db, user, monkeypatch):
    from app.models import WeeklySummary
    db.add(WeeklySummary(user_id=user.id, week_start=CLOSED_WEEK - dt.timedelta(days=7),
                         coach_note="Easy volume slipped last week."))
    db.commit()
    stub = StubWeeklyLLM({"summary": "Trend noted."})
    _use_llm(monkeypatch, stub)
    s = weekly.evaluate_week(db, user.id, CLOSED_WEEK, today=MONDAY)
    assert s.snapshot["previous_week_summary"] == "Easy volume slipped last week."


def test_snapshot_aggregates_reflect_the_weeks_activities(db, user, monkeypatch):
    _run(db, user.id, CLOSED_WEEK, score=90, minutes=50, km=10.0)
    _run(db, user.id, CLOSED_WEEK + dt.timedelta(days=5), minutes=30, km=6.0)
    _run(db, user.id, CLOSED_WEEK - dt.timedelta(days=1))   # previous week: excluded
    _run(db, user.id, CLOSED_WEEK + dt.timedelta(days=7))   # next week: excluded
    stub = StubWeeklyLLM({"summary": "ok"})
    _use_llm(monkeypatch, stub)
    s = weekly.evaluate_week(db, user.id, CLOSED_WEEK, today=MONDAY)
    agg = s.snapshot["week_aggregates"]
    assert agg["done_min"] == 80
    assert agg["run_km"] == 16.0
    acts = s.snapshot["activities"]
    assert len(acts) == 2
    assert acts[0]["execution_score"] == 90


# --- HTTP seam ----------------------------------------------------------------

def _login(client, username="will", password="secret1"):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200


def test_get_summary_canonicalizes_and_reports_absent(client, db, user, monkeypatch):
    monkeypatch.setattr(weekly, "_today", lambda: MONDAY)
    _login(client)
    r = client.get("/api/week/summary", params={"start": (CLOSED_WEEK + dt.timedelta(days=4)).isoformat()})
    assert r.status_code == 200
    body = r.json()
    assert body["week_start"] == CLOSED_WEEK.isoformat()
    assert body["summary"] is None
    assert body["generatable"] is True


def test_evaluate_endpoint_generates_then_get_returns_it(client, db, user, monkeypatch):
    monkeypatch.setattr(weekly, "_today", lambda: MONDAY)
    stub = StubWeeklyLLM({"summary": "Week well spent."})
    _use_llm(monkeypatch, stub)
    _login(client)
    r = client.post("/api/week/summary/evaluate", json={"start": CLOSED_WEEK.isoformat()})
    assert r.status_code == 200
    assert r.json()["summary"]["coach_note"] == "Week well spent."
    assert r.json()["summary"]["coach"] == "default"

    r2 = client.post("/api/week/summary/evaluate", json={"start": CLOSED_WEEK.isoformat()})
    assert stub.calls == 1  # idempotent over HTTP too

    r3 = client.get("/api/week/summary", params={"start": CLOSED_WEEK.isoformat()})
    assert r3.json()["summary"]["coach_note"] == "Week well spent."


def test_evaluate_endpoint_rejects_unclosed_and_backfill_weeks(client, db, user, monkeypatch):
    monkeypatch.setattr(weekly, "_today", lambda: MONDAY)
    stub = StubWeeklyLLM({"summary": "nope"})
    _use_llm(monkeypatch, stub)
    _login(client)
    r = client.post("/api/week/summary/evaluate", json={"start": MONDAY.isoformat()})
    assert r.status_code == 409
    r = client.post("/api/week/summary/evaluate",
                    json={"start": (CLOSED_WEEK - dt.timedelta(days=7)).isoformat()})
    assert r.status_code == 409
    assert stub.calls == 0


def test_old_summary_still_readable_after_its_week_ages_out(client, db, user, monkeypatch):
    # Permanent Week-page home: GET serves any existing row forever.
    from app.models import WeeklySummary
    old_week = CLOSED_WEEK - dt.timedelta(days=21)
    db.add(WeeklySummary(user_id=user.id, week_start=old_week,
                         coach_note="An old but good week.", coach="chill"))
    db.commit()
    monkeypatch.setattr(weekly, "_today", lambda: MONDAY)
    _login(client)
    r = client.get("/api/week/summary", params={"start": old_week.isoformat()})
    assert r.json()["summary"]["coach_note"] == "An old but good week."
    assert r.json()["generatable"] is False


def test_summary_requires_auth(client, db, user):
    r = client.get("/api/week/summary")
    assert r.status_code == 401


def test_weekly_summary_feedback_roundtrip(client, db, user, monkeypatch):
    monkeypatch.setattr(weekly, "_today", lambda: MONDAY)
    stub = StubWeeklyLLM({"summary": "Rate me."})
    _use_llm(monkeypatch, stub)
    _login(client)
    client.post("/api/week/summary/evaluate", json={"start": CLOSED_WEEK.isoformat()})
    r = client.post("/api/feedback", json={
        "surface": "weekly_summary", "ref": CLOSED_WEEK.isoformat(), "rating": 1})
    assert r.status_code == 200
    assert r.json()["feedback"]["rating"] == 1
    r2 = client.get("/api/week/summary", params={"start": CLOSED_WEEK.isoformat()})
    assert r2.json()["summary"]["my_feedback"]["rating"] == 1


def test_feedback_on_missing_week_404s(client, db, user):
    _login(client)
    r = client.post("/api/feedback", json={
        "surface": "weekly_summary", "ref": "2026-01-05", "rating": 1})
    assert r.status_code == 404


# --- scheduler: eager Monday generation --------------------------------------

def test_eager_weekly_writes_summary_on_monday_only(db, user, monkeypatch):
    from app import scheduler
    from app.models import WeeklySummary
    stub = StubWeeklyLLM({"summary": "Monday morning delivery."})
    _use_llm(monkeypatch, stub)

    scheduler._eager_weekly(db, user, dt.date(2026, 7, 23))  # Thursday: no-op
    assert stub.calls == 0

    scheduler._eager_weekly(db, user, MONDAY)
    assert stub.calls == 1
    row = db.get(WeeklySummary, (user.id, CLOSED_WEEK))
    assert row is not None and row.coach_note == "Monday morning delivery."

    scheduler._eager_weekly(db, user, MONDAY)  # already written: no second call
    assert stub.calls == 1


def test_eager_weekly_failure_never_raises(db, user, monkeypatch):
    from app import scheduler

    def boom(*a, **k):
        raise RuntimeError("provider down")

    monkeypatch.setattr(weekly, "make_client", boom)
    scheduler._eager_weekly(db, user, MONDAY)  # must swallow, sync goes on


def test_disabled_setting_skips_generation(db, user, monkeypatch):
    # Idea G seam: the enabled flag is read at the generation choke point.
    from app.models import Setting
    db.add(Setting(user_id=user.id, key=weekly.ENABLED_KEY, value=False))
    db.commit()
    stub = StubWeeklyLLM({"summary": "nope"})
    _use_llm(monkeypatch, stub)
    assert weekly.evaluate_week(db, user.id, CLOSED_WEEK, today=MONDAY) is None
    assert stub.calls == 0
