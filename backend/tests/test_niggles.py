"""Injury / niggle tracking: signal logic, chat tools, endpoints, snapshot."""

from __future__ import annotations

import datetime as dt
import json

from app import niggles
from app.chat.tools import dispatch
from app.models import Niggle
from tests.conftest import make_user


def _login(client, db):
    make_user(db, username="will", password="secret1")
    r = client.post("/api/auth/login", json={"username": "will", "password": "secret1"})
    assert r.status_code == 200


# --- signal logic ---------------------------------------------------------------

def test_log_resolve_roundtrip(db, user):
    today = dt.date.today()
    n = niggles.log_niggle(db, user.id, "Left  Knee", 2, note="hurts downhill")
    assert n.body_part == "left knee"  # normalized
    active = niggles.active_niggles(db, user.id, today)
    assert active and active[0]["severity_label"] == "pain"
    assert active[0]["days_open"] == 0
    assert active[0]["show_checkin"] is False

    niggles.resolve_niggle(db, user.id, n.id)
    assert niggles.active_niggles(db, user.id, today) is None  # None, not []


def test_same_body_part_updates_not_duplicates(db, user):
    a = niggles.log_niggle(db, user.id, "left knee", 1)
    b = niggles.log_niggle(db, user.id, "Left Knee", 2, note="got worse")
    assert a.id == b.id
    assert b.severity == 2 and b.note == "got worse"
    assert len(niggles.open_niggles(db, user.id)) == 1
    # A different part is its own row.
    niggles.log_niggle(db, user.id, "right achilles", 1)
    assert len(niggles.open_niggles(db, user.id)) == 2


def test_checkin_window_scales_with_severity(db, user):
    today = dt.date.today()
    minor = niggles.log_niggle(db, user.id, "calf", 1,
                               onset_date=today - dt.timedelta(days=7))
    pain = niggles.log_niggle(db, user.id, "knee", 2,
                              onset_date=today - dt.timedelta(days=7))
    by_part = {d["body_part"]: d for d in niggles.active_niggles(db, user.id, today)}
    assert by_part["calf"]["show_checkin"] is True    # sev 1 -> 7-day window
    assert by_part["knee"]["show_checkin"] is False   # sev 2 -> 14-day window

    # "Still sore" re-arms: no prompt again until another full window passes.
    niggles.checkin_niggle(db, user.id, minor.id)
    by_part = {d["body_part"]: d for d in niggles.active_niggles(db, user.id, today)}
    assert by_part["calf"]["show_checkin"] is False


def test_severity_clamped_and_future_onset_rejected(db, user):
    n = niggles.log_niggle(db, user.id, "hip", 9,
                           onset_date=dt.date.today() + dt.timedelta(days=3))
    assert n.severity == 3
    assert n.onset_date == dt.date.today()


def test_tenant_isolation(db, user):
    other = make_user(db, username="julianne")
    n = niggles.log_niggle(db, other.id, "knee", 2)
    assert niggles.resolve_niggle(db, user.id, n.id) is None
    assert n.resolved_date is None


# --- chat tools -----------------------------------------------------------------

def test_chat_log_and_resolve_niggle(db, user):
    out, edit = dispatch(db, user.id, "log_niggle",
                         {"body_part": "right achilles", "severity": 2,
                          "note": "tight since Tuesday"})
    assert edit is None
    payload = json.loads(out)
    assert payload["status"] == "logged"
    nid = payload["niggle"]["id"]
    assert payload["niggle"]["severity_label"] == "pain"

    out, _ = dispatch(db, user.id, "resolve_niggle", {"id": nid})
    assert json.loads(out)["status"] == "resolved"
    assert niggles.active_niggles(db, user.id, dt.date.today()) is None


def test_chat_tool_bad_input(db, user):
    out, _ = dispatch(db, user.id, "log_niggle", {"body_part": "  ", "severity": 1})
    assert "error" in json.loads(out)
    out, _ = dispatch(db, user.id, "resolve_niggle", {"id": 999})
    assert "error" in json.loads(out)


# --- snapshot -------------------------------------------------------------------

def test_snapshot_carries_active_niggles(db, user):
    from app.planner import build_snapshot

    today = dt.date.today()
    assert build_snapshot(db, user.id, today)["active_niggles"] is None
    niggles.log_niggle(db, user.id, "left knee", 2)
    snap = build_snapshot(db, user.id, today)
    assert snap["active_niggles"][0]["body_part"] == "left knee"


# --- endpoints ------------------------------------------------------------------

def test_niggle_endpoints_roundtrip(client, db):
    _login(client, db)
    r = client.post("/api/niggles", json={"body_part": "left knee", "severity": 2,
                                          "note": "sore downhill"})
    assert r.status_code == 200
    nid = r.json()["niggle"]["id"]

    today = client.get("/api/dashboard/today").json()
    assert today["niggles"][0]["body_part"] == "left knee"

    assert client.get("/api/niggles").json()["niggles"][0]["id"] == nid
    assert client.post(f"/api/niggles/{nid}/checkin").json() == {"ok": True}
    assert client.post(f"/api/niggles/{nid}/resolve").json() == {"ok": True}
    assert client.get("/api/niggles").json()["niggles"] == []
    assert client.get("/api/dashboard/today").json()["niggles"] is None


def test_niggle_endpoint_validation(client, db):
    _login(client, db)
    assert client.post("/api/niggles", json={"body_part": " ", "severity": 1}).status_code == 422
    assert client.post("/api/niggles", json={"body_part": "knee", "severity": 5}).status_code == 422
    future = (dt.date.today() + dt.timedelta(days=2)).isoformat()
    assert client.post("/api/niggles", json={
        "body_part": "knee", "severity": 1, "onset_date": future}).status_code == 422
    assert client.post("/api/niggles/12345/resolve").status_code == 404
