from __future__ import annotations

import datetime as dt

from app.models import PlanDay, PlanVersion
from tests.conftest import make_user


def _login(client, db):
    make_user(db, username="jul", password="secret1")
    r = client.post("/api/auth/login", json={"username": "jul", "password": "secret1"})
    assert r.status_code == 200


def test_settings_cycle_roundtrip_and_status(client, db):
    _login(client, db)

    # Default: tracking off, no status.
    s = client.get("/api/settings").json()
    assert s["cycle"] == {
        "enabled": False, "last_start_date": None,
        "cycle_length_days": 28, "period_length_days": 5,
    }
    assert s["cycle_status"] is None

    # Enable with an anchor 2 days ago -> menstrual, day 3, ease still on (day<2? no).
    anchor = (dt.date.today() - dt.timedelta(days=2)).isoformat()
    put = client.put("/api/settings", json={"cycle": {
        "enabled": True, "last_start_date": anchor,
        "cycle_length_days": 30, "period_length_days": 5,
    }}).json()
    assert put["cycle"]["enabled"] is True
    assert put["cycle"]["cycle_length_days"] == 30
    status = put["cycle_status"]
    assert status is not None
    assert status["phase"] == "menstrual"
    assert status["day_of_cycle"] == 3

    # Bad anchor is normalized away; garbage length falls back.
    bad = client.put("/api/settings", json={"cycle": {
        "enabled": True, "last_start_date": "nope", "cycle_length_days": 999,
    }}).json()
    assert bad["cycle"]["last_start_date"] is None
    assert bad["cycle"]["cycle_length_days"] == 28
    assert bad["cycle_status"] is None  # no anchor -> no signal


def test_week_payload_carries_cycle_phase(client, db):
    _login(client, db)
    today = dt.date.today()

    # A plan day today so /plan/week returns a row.
    db.add(PlanVersion(user_id=1, source="manual", summary="t", snapshot=[]))
    db.add(PlanDay(user_id=1, date=today, workout_type="easy_run",
                   title="Easy", description="", status="planned"))
    db.commit()

    # Anchor today -> day 1, ease recommended, menstrual.
    client.put("/api/settings", json={"cycle": {
        "enabled": True, "last_start_date": today.isoformat(),
        "cycle_length_days": 28, "period_length_days": 5,
    }})

    week = client.get("/api/plan/week").json()
    day = next(d for d in week["days"] if d["date"] == today.isoformat())
    assert day["cycle"] is not None
    assert day["cycle"]["phase"] == "menstrual"
    assert day["cycle"]["ease_recommended"] is True

    # Turn tracking off -> the day carries no cycle signal.
    client.put("/api/settings", json={"cycle": {"enabled": False}})
    week2 = client.get("/api/plan/week").json()
    day2 = next(d for d in week2["days"] if d["date"] == today.isoformat())
    assert day2["cycle"] is None


def test_cycle_started_reanchors_and_learns_length(client, db):
    _login(client, db)
    today = dt.date.today()

    # Anchor 26 days ago on a 28-day cycle: predicted start is in 2 days, but the
    # period actually starts TODAY (2 days early). Confirming re-anchors to today
    # and nudges the length down toward the observed 26.
    client.put("/api/settings", json={"cycle": {
        "enabled": True,
        "last_start_date": (today - dt.timedelta(days=26)).isoformat(),
        "cycle_length_days": 28, "period_length_days": 5,
    }})
    out = client.post("/api/cycle/started", json={}).json()
    assert out["cycle"]["last_start_date"] == today.isoformat()
    # 2:1 blend of 28 and observed 26 -> round((28*2+26)/3) = 27.
    assert out["cycle"]["cycle_length_days"] == 27
    assert out["cycle_status"]["phase"] == "menstrual"
    assert out["cycle_status"]["day_of_cycle"] == 1

    # Future dates are rejected.
    fut = client.post("/api/cycle/started",
                      json={"date": (today + dt.timedelta(days=1)).isoformat()})
    assert fut.status_code == 422


def test_drift_prompt_stops_after_confirm_and_snooze(client, db):
    _login(client, db)
    today = dt.date.today()

    # Anchor 27 days ago on a 28-day cycle -> predicted start is tomorrow: in the
    # drift window, and (nothing confirmed/snoozed yet) the prompt should show.
    client.put("/api/settings", json={"cycle": {
        "enabled": True,
        "last_start_date": (today - dt.timedelta(days=27)).isoformat(),
        "cycle_length_days": 28, "period_length_days": 5,
    }})
    d = client.get("/api/dashboard/today").json()["cycle"]
    assert d["in_drift_window"] is True
    assert d["show_started_prompt"] is True

    # "Not yet" -> hidden for today (window itself unchanged).
    assert client.post("/api/cycle/snooze").status_code == 200
    d2 = client.get("/api/dashboard/today").json()["cycle"]
    assert d2["in_drift_window"] is True
    assert d2["show_started_prompt"] is False

    # "Yes, today" -> re-anchors to day 1 (STILL in the window) but the prompt is
    # off because this cycle's start is now confirmed. This is the reported bug.
    client.post("/api/cycle/started", json={})
    d3 = client.get("/api/dashboard/today").json()["cycle"]
    assert d3["day_of_cycle"] == 1
    assert d3["in_drift_window"] is True
    assert d3["show_started_prompt"] is False


def test_cycle_calendar_shades_period_days(client, db):
    _login(client, db)
    today = dt.date.today()
    client.put("/api/settings", json={"cycle": {
        "enabled": True, "last_start_date": today.replace(day=1).isoformat(),
        "cycle_length_days": 28, "period_length_days": 5,
    }})
    cal = client.get("/api/cycle/calendar?months=2").json()
    assert len(cal["days"]) >= 56
    first = cal["days"][0]
    assert first["phase"] == "menstrual"  # anchored on the 1st
    # Every day has a phase when tracking is on.
    assert all(d["phase"] is not None for d in cal["days"])

    client.put("/api/settings", json={"cycle": {"enabled": False}})
    off = client.get("/api/cycle/calendar").json()
    assert all(d["phase"] is None for d in off["days"])
