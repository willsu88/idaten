"""Instance-level coach call-site toggles (docs/adr/0003, .scratch/coach-toggles).

Operator policy: one switch per system-initiated call site, applying to every
member equally. Absent = enabled; a toggle governs LLM generation only.

Seams under test (agreed at spec time):
- weekly.evaluate_week / scheduler._weekly_done (generation choke points)
- POST /activities/{id}/analysis (lazy narrative choke point)
- GET /week/summary `generatable` flag
- the admin coach_toggles endpoints
"""

from __future__ import annotations

import datetime as dt

from app import instance_settings, weekly
from app.models import Activity

MONDAY = dt.date(2026, 7, 27)
CLOSED_WEEK = dt.date(2026, 7, 20)


class StubLLM:
    def __init__(self, result: dict):
        self.result = result
        self.calls = 0

    def complete_structured(self, system, messages, schema, name):
        self.calls += 1
        return self.result


def _stub_weekly(monkeypatch, stub):
    monkeypatch.setattr(weekly, "make_client", lambda provider=None, **_kw: stub)


def _login(client, username="will", password="secret1"):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200


def _make_admin(db, user):
    user.is_admin = True
    db.commit()


# --- the store: absent = enabled ----------------------------------------------

def test_call_sites_default_enabled(db):
    for site in instance_settings.TOGGLEABLE_CALL_SITES:
        assert instance_settings.call_site_enabled(db, site) is True


def test_disable_then_reenable_roundtrip(db):
    instance_settings.set_call_site_enabled(db, "weekly_summary", False)
    assert instance_settings.call_site_enabled(db, "weekly_summary") is False
    assert instance_settings.call_site_enabled(db, "execution_analysis") is True
    instance_settings.set_call_site_enabled(db, "weekly_summary", True)
    assert instance_settings.call_site_enabled(db, "weekly_summary") is True


def test_falsy_stored_value_reads_disabled(db):
    # A future writer storing 0/""/None must never read back as enabled.
    for falsy in (0, "", None, False):
        instance_settings.put_value(
            db, instance_settings.toggle_key("weekly_summary"), falsy)
        assert instance_settings.call_site_enabled(db, "weekly_summary") is False


# --- weekly summary: generation choke point ------------------------------------

def test_disabled_weekly_summary_skips_generation_for_every_member(db, user, monkeypatch):
    from tests.conftest import make_user
    other = make_user(db, "member2", "secret2")
    instance_settings.set_call_site_enabled(db, "weekly_summary", False)
    stub = StubLLM({"summary": "nope"})
    _stub_weekly(monkeypatch, stub)
    assert weekly.evaluate_week(db, user.id, CLOSED_WEEK, today=MONDAY) is None
    assert weekly.evaluate_week(db, other.id, CLOSED_WEEK, today=MONDAY) is None
    assert stub.calls == 0


def test_reenable_resumes_forward_only(db, user, monkeypatch):
    instance_settings.set_call_site_enabled(db, "weekly_summary", False)
    stub = StubLLM({"summary": "Back on."})
    _stub_weekly(monkeypatch, stub)
    assert weekly.evaluate_week(db, user.id, CLOSED_WEEK, today=MONDAY) is None
    instance_settings.set_call_site_enabled(db, "weekly_summary", True)
    s = weekly.evaluate_week(db, user.id, CLOSED_WEEK, today=MONDAY)
    assert s is not None and s.coach_note == "Back on."
    assert stub.calls == 1
    # The week disabled at its generation moment stays a permanent gap.
    import pytest
    with pytest.raises(ValueError):
        weekly.evaluate_week(db, user.id, CLOSED_WEEK - dt.timedelta(days=7),
                             today=MONDAY)


def test_weekly_done_treats_disabled_as_done(db, user):
    from app import scheduler
    assert scheduler._weekly_done(db, user.id, MONDAY) is False
    instance_settings.set_call_site_enabled(db, "weekly_summary", False)
    assert scheduler._weekly_done(db, user.id, MONDAY) is True


def test_get_week_summary_not_generatable_while_disabled(client, db, user, monkeypatch):
    monkeypatch.setattr(weekly, "app_today", lambda: MONDAY)
    instance_settings.set_call_site_enabled(db, "weekly_summary", False)
    _login(client)
    r = client.get("/api/week/summary")
    assert r.status_code == 200
    assert r.json()["summary"] is None
    assert r.json()["generatable"] is False


def test_existing_summary_stays_readable_while_disabled(client, db, user, monkeypatch):
    from app.models import WeeklySummary
    db.add(WeeklySummary(user_id=user.id, week_start=CLOSED_WEEK,
                         coach_note="Written before the switch."))
    db.commit()
    instance_settings.set_call_site_enabled(db, "weekly_summary", False)
    monkeypatch.setattr(weekly, "app_today", lambda: MONDAY)
    _login(client)
    r = client.get("/api/week/summary", params={"start": CLOSED_WEEK.isoformat()})
    assert r.json()["summary"]["coach_note"] == "Written before the switch."


# --- execution analysis: lazy narrative choke point -----------------------------

def _scored_run(db, user_id, analysis=None):
    a = Activity(user_id=user_id, date=dt.date.today(), type="running",
                 name="Tempo", distance_m=8000, duration_s=2400,
                 execution_score=85, execution_analysis=analysis)
    db.add(a)
    db.commit()
    return a


def test_disabled_analysis_reports_absent_without_llm(client, db, user, monkeypatch):
    from app import planner as planner_mod

    def boom(*a, **k):
        raise AssertionError("LLM must not be called while disabled")

    monkeypatch.setattr(planner_mod, "write_execution_analysis", boom)
    a = _scored_run(db, user.id)
    instance_settings.set_call_site_enabled(db, "execution_analysis", False)
    _login(client)
    r = client.post(f"/api/activities/{a.id}/analysis")
    assert r.status_code == 200
    assert r.json() == {"analysis": None, "coach": None}


def test_disabled_analysis_still_serves_a_cached_narrative(client, db, user):
    # The toggle governs generation only - an already-written artifact survives.
    a = _scored_run(db, user.id, analysis="Solid tempo, right on target.")
    instance_settings.set_call_site_enabled(db, "execution_analysis", False)
    _login(client)
    r = client.post(f"/api/activities/{a.id}/analysis")
    assert r.json()["analysis"] == "Solid tempo, right on target."


# --- admin endpoints ------------------------------------------------------------

def test_admin_reads_defaults_all_on(client, db, user):
    _make_admin(db, user)
    _login(client)
    r = client.get("/api/auth/coach_toggles")
    assert r.status_code == 200
    assert r.json() == {"weekly_summary": True, "execution_analysis": True}


def test_admin_put_is_partial_and_persists(client, db, user):
    _make_admin(db, user)
    _login(client)
    r = client.put("/api/auth/coach_toggles", json={"weekly_summary": False})
    assert r.status_code == 200
    assert r.json() == {"weekly_summary": False, "execution_analysis": True}
    # Unmentioned keys are untouched; the write is durable.
    r2 = client.get("/api/auth/coach_toggles")
    assert r2.json() == {"weekly_summary": False, "execution_analysis": True}
    assert instance_settings.call_site_enabled(db, "weekly_summary") is False


def test_member_cannot_read_or_write_toggles(client, db, user):
    from tests.conftest import make_user
    _make_admin(db, user)  # someone must hold admin; the member is a second user
    make_user(db, "member2", "secret2")
    _login(client, "member2", "secret2")
    assert client.get("/api/auth/coach_toggles").status_code == 403
    assert client.put("/api/auth/coach_toggles",
                      json={"weekly_summary": False}).status_code == 403


def test_toggles_are_invisible_to_member_settings_api(client, db, user):
    instance_settings.set_call_site_enabled(db, "weekly_summary", False)
    _login(client)
    r = client.get("/api/settings")
    assert "coach_toggles" not in r.json()
    assert "weekly_summary" not in r.json()
