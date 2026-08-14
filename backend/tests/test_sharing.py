"""Shared workouts (ADR 0022): the deterministic adapt round trip, the share
endpoints, and the tenant boundary they deliberately cross."""

from __future__ import annotations

import datetime as dt
import json

from app import sharing
from app.chat.tools import dispatch
from app.models import DayIntent, PlanDay, PlanVersion, SharedWorkout
from app.planner import (_is_override, hr_band_violations,
                         pace_format_violations, terrain_target_violations)
from app.settings_store import put_garmin_hr_zones, put_internal, put_settings
from app import metrics
from conftest import make_user

TODAY = dt.date.today()

SENDER_ZONES = {"z1": [100, 120], "z2": [120, 140], "z3": [140, 155],
                "z4": [155, 170], "z5": [170, 190]}
RECIP_ZONES = {"z1": [110, 135], "z2": [135, 150], "z3": [150, 162],
               "z4": [162, 178], "z5": [178, 200]}


def _payload(workout: dict, vdot=50.0, zones=SENDER_ZONES) -> dict:
    return {"workout": workout,
            "sender": {"display_name": "Will", "hr_zones": zones, "vdot": vdot}}


def _params(vdot=45.0, zones=RECIP_ZONES, profile=None, mode="hybrid") -> dict:
    return {"hr_zones": zones, "vdot": vdot, "pace_profile": profile,
            "training_mode": mode}


def _tempo_day() -> dict:
    return {
        "workout_type": "tempo", "title": "Threshold 3x10", "description": "",
        "duration_min": 50.0, "distance_km": None,
        "target_pace": None, "target_hr_low": None, "target_hr_high": None,
        "steps": [
            {"repeat": 1, "steps": [
                {"kind": "warmup", "duration_min": 10,
                 "target_hr_low": 120, "target_hr_high": 140},
            ]},
            {"repeat": 3, "steps": [
                {"kind": "work", "duration_min": 10, "target_pace": "4:30-4:40"},
                {"kind": "recovery", "duration_min": 3,
                 "target_hr_low": 120, "target_hr_high": 140},
            ]},
            {"repeat": 1, "steps": [{"kind": "cooldown", "duration_min": 7,
                                     "target_hr_low": 100, "target_hr_high": 120}]},
        ],
    }


# --- pure adaptation -------------------------------------------------------------

def test_hr_band_maps_by_zone_position():
    day = {"workout_type": "easy_run", "title": "Easy", "description": "",
           "target_pace": None, "target_hr_low": 140, "target_hr_high": 155,
           "steps": None}
    out = sharing.adapt_workout(_payload(day), _params())
    # Sender's full z3 becomes the recipient's full z3.
    assert [out["target_hr_low"], out["target_hr_high"]] == RECIP_ZONES["z3"]


def test_pace_maps_at_equal_percent_vvo2max():
    day = {"workout_type": "tempo", "title": "T", "description": "",
           "target_pace": "4:30-4:40", "target_hr_low": None,
           "target_hr_high": None, "steps": None}
    out = sharing.adapt_workout(_payload(day, vdot=50.0), _params(vdot=45.0))
    lo, hi = out["target_pace"].split("-")
    # A lower-VDOT recipient gets a strictly slower band, slower bound first.
    assert metrics.pace_seconds(lo) > metrics.pace_seconds("4:30")
    assert metrics.pace_seconds(lo) >= metrics.pace_seconds(hi)
    # Same VDOT round-trips to (almost) the same band.
    same = sharing.adapt_workout(_payload(day, vdot=50.0), _params(vdot=50.0))
    assert abs(metrics.pace_seconds(same["target_pace"]) -
               metrics.pace_seconds("4:30-4:40")) <= 1


def test_adapted_day_honors_planner_invariants():
    out = sharing.adapt_workout(_payload(_tempo_day()), _params())
    days = [{**out, "date": TODAY.isoformat()}]
    assert pace_format_violations(days) == []
    assert hr_band_violations(days) == []
    assert terrain_target_violations(days) == []


def test_structure_passes_through_untouched():
    out = sharing.adapt_workout(_payload(_tempo_day()), _params())
    assert [b["repeat"] for b in out["steps"]] == [1, 3, 1]
    kinds = [s["kind"] for b in out["steps"] for s in b["steps"]]
    assert kinds == ["warmup", "work", "recovery", "cooldown"]
    assert out["duration_min"] == 50.0


def test_hr_mode_recipient_gets_pace_as_zone_band():
    day = {"workout_type": "tempo", "title": "T", "description": "",
           "target_pace": "4:30", "target_hr_low": None, "target_hr_high": None,
           "steps": None}
    out = sharing.adapt_workout(_payload(day, vdot=50.0), _params(mode="hr"))
    assert out["target_pace"] is None
    assert out["target_hr_low"] is not None
    assert out["target_hr_high"] - out["target_hr_low"] >= metrics.MIN_HR_BAND_WIDTH
    # A threshold pace lands in the recipient's z3-z4 family.
    assert out["target_hr_low"] >= RECIP_ZONES["z3"][0]
    assert out["target_hr_high"] <= RECIP_ZONES["z4"][1]


def test_easy_pace_grounds_to_recipient_observed_paces():
    day = {"workout_type": "easy_run", "title": "Easy", "description": "",
           "target_pace": "5:00-5:10", "target_hr_low": None,
           "target_hr_high": None, "steps": None}
    profile = {"runs_last_90d": 10, "typical_pace": "6:40",
               "fastest_avg_pace": "5:50", "slowest_avg_pace": "7:30",
               "typical_pace_s": 400, "fastest_avg_pace_s": 350}
    out = sharing.adapt_workout(_payload(day, vdot=60.0),
                                _params(vdot=55.0, profile=profile))
    # Whatever %vVO2 said, an easy day never outruns the observed typical pace.
    assert metrics.pace_seconds(out["target_pace"]) >= round(400 * 0.93)


def test_uphill_step_keeps_hr_and_never_gains_pace():
    day = {"workout_type": "intervals", "title": "Hills", "description": "",
           "target_pace": None, "target_hr_low": None, "target_hr_high": None,
           "steps": [{"repeat": 4, "steps": [
               {"kind": "work", "duration_min": 2, "terrain": "uphill",
                "target_hr_low": 155, "target_hr_high": 170},
               {"kind": "recovery", "duration_min": 2, "terrain": "downhill"},
           ]}]}
    out = sharing.adapt_workout(_payload(day), _params())
    work = out["steps"][0]["steps"][0]
    assert work["target_pace"] is None
    assert [work["target_hr_low"], work["target_hr_high"]] == RECIP_ZONES["z4"]
    assert work["terrain"] == "uphill"


def test_adapt_unavailable_without_needed_params():
    pace_day = {"workout_type": "tempo", "title": "T", "description": "",
                "target_pace": "4:30", "target_hr_low": None,
                "target_hr_high": None, "steps": None}
    hr_day = {"workout_type": "easy_run", "title": "E", "description": "",
              "target_pace": None, "target_hr_low": 140, "target_hr_high": 155,
              "steps": None}
    no_target = {"workout_type": "easy_run", "title": "E", "description": "",
                 "target_pace": None, "target_hr_low": None,
                 "target_hr_high": None, "steps": None}
    assert sharing.adapt_unavailable_reason(
        _payload(pace_day, vdot=None), _params()) is not None
    assert sharing.adapt_unavailable_reason(
        _payload(pace_day), _params(vdot=None)) is not None
    assert sharing.adapt_unavailable_reason(
        _payload(hr_day, zones=None), _params()) is not None
    assert sharing.adapt_unavailable_reason(
        _payload(hr_day), _params(zones=None)) is not None
    # No targets at all: nothing to translate, adaptation trivially available.
    assert sharing.adapt_unavailable_reason(
        _payload(no_target, vdot=None, zones=None),
        _params(vdot=None, zones=None)) is None


def test_snapshot_excludes_rationale(db):
    a = make_user(db, "will", "secret1")
    day = PlanDay(user_id=a.id, date=TODAY, workout_type="tempo", title="T",
                  rationale="private readiness context")
    db.add(day)
    db.commit()
    payload = sharing.build_payload(db, a, day)
    assert "rationale" not in payload["workout"]
    assert payload["sender"]["display_name"] == "Will"


# --- endpoints -------------------------------------------------------------------

def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200


def _seed(db):
    a = make_user(db, "will", "secret1")
    b = make_user(db, "gf", "secret2")
    day = PlanDay(user_id=a.id, date=TODAY, **{k: v for k, v in _tempo_day().items()})
    db.add(day)
    db.commit()
    return a, b


def test_share_accept_as_is_lands_as_override(db, client):
    a, b = _seed(db)
    _login(client, "will", "secret1")
    r = client.post("/api/share/workout", json={"to_user_id": b.id,
                                                "date": TODAY.isoformat()})
    assert r.status_code == 200
    share_id = r.json()["id"]

    _login(client, "gf", "secret2")
    inbox = client.get("/api/share/inbox").json()
    assert [s["id"] for s in inbox] == [share_id]
    assert inbox[0]["from"] == "Will"
    assert inbox[0]["workout"]["title"] == "Threshold 3x10"
    # Neither athlete has Garmin data in this test: adapted must be honest-null.
    assert inbox[0]["adapted"] is None
    assert inbox[0]["adapt_unavailable_reason"]

    r = client.post(f"/api/share/{share_id}/accept", json={"mode": "as_is"})
    assert r.status_code == 200
    day = db.get(PlanDay, (b.id, TODAY))
    assert day.title == "Threshold 3x10"
    assert day.rationale == "Shared by Will."
    version = db.get(PlanVersion, day.version_id)
    assert version.source == "shared"
    assert _is_override(db, day)  # the daily job must plan around it
    assert db.get(SharedWorkout, share_id).status == "accepted"
    assert db.get(SharedWorkout, share_id).accept_mode == "as_is"
    # The Today dashboard carries the (now empty) inbox.
    assert client.get("/api/dashboard/today").json()["shared_inbox"] == []


def test_accept_adapted_uses_recipient_zones(db, client):
    a, b = _seed(db)
    put_garmin_hr_zones(db, a.id, SENDER_ZONES, TODAY.isoformat())
    put_garmin_hr_zones(db, b.id, RECIP_ZONES, TODAY.isoformat())
    put_internal(db, a.id, "garmin_profile", {"vo2max_running": 50.0})
    put_internal(db, b.id, "garmin_profile", {"vo2max_running": 45.0})

    _login(client, "will", "secret1")
    share_id = client.post("/api/share/workout", json={
        "to_user_id": b.id, "date": TODAY.isoformat()}).json()["id"]

    _login(client, "gf", "secret2")
    inbox = client.get("/api/share/inbox").json()
    assert inbox[0]["adapted"] is not None
    warmup = inbox[0]["adapted"]["steps"][0]["steps"][0]
    assert [warmup["target_hr_low"], warmup["target_hr_high"]] == RECIP_ZONES["z2"]

    r = client.post(f"/api/share/{share_id}/accept", json={"mode": "adapted"})
    assert r.status_code == 200
    day = db.get(PlanDay, (b.id, TODAY))
    work = day.steps[1]["steps"][0]
    assert metrics.pace_seconds(work["target_pace"]) > metrics.pace_seconds("4:30-4:40")
    assert db.get(SharedWorkout, share_id).accept_mode == "adapted"


def test_share_validation(db, client):
    a, b = _seed(db)
    db.add(PlanDay(user_id=a.id, date=TODAY + dt.timedelta(days=1),
                   workout_type="rest", title="Rest"))
    db.commit()
    _login(client, "will", "secret1")
    to = {"to_user_id": b.id}
    assert client.post("/api/share/workout", json={
        **to, "date": (TODAY + dt.timedelta(days=2)).isoformat()}).status_code == 404
    assert client.post("/api/share/workout", json={
        **to, "date": (TODAY + dt.timedelta(days=1)).isoformat()}).status_code == 422
    assert client.post("/api/share/workout", json={
        "to_user_id": a.id, "date": TODAY.isoformat()}).status_code == 422
    assert client.post("/api/share/workout", json={
        "to_user_id": 999, "date": TODAY.isoformat()}).status_code == 422


def test_share_members_lists_others_only(db, client):
    a, b = _seed(db)
    _login(client, "gf", "secret2")
    members = client.get("/api/share/members").json()
    assert members == [{"id": a.id, "display_name": "Will"}]


def test_only_recipient_can_touch_a_share(db, client):
    a, b = _seed(db)
    make_user(db, "guest", "secret3")
    share = SharedWorkout(from_user_id=a.id, to_user_id=b.id, date=TODAY,
                          payload=sharing.build_payload(
                              db, a, db.get(PlanDay, (a.id, TODAY))))
    db.add(share)
    db.commit()

    for username, password in (("will", "secret1"), ("guest", "secret3")):
        _login(client, username, password)
        assert client.get("/api/share/inbox").json() == []
        assert client.post(f"/api/share/{share.id}/accept",
                           json={"mode": "as_is"}).status_code == 404
        assert client.post(f"/api/share/{share.id}/decline").status_code == 404
    db.expire_all()
    assert db.get(SharedWorkout, share.id).status == "pending"


def test_decline_and_expiry(db, client):
    a, b = _seed(db)
    payload = sharing.build_payload(db, a, db.get(PlanDay, (a.id, TODAY)))
    fresh = SharedWorkout(from_user_id=a.id, to_user_id=b.id, date=TODAY,
                          payload=payload)
    stale = SharedWorkout(from_user_id=a.id, to_user_id=b.id,
                          date=TODAY - dt.timedelta(days=1), payload=payload)
    db.add_all([fresh, stale])
    db.commit()

    _login(client, "gf", "secret2")
    inbox = client.get("/api/share/inbox").json()
    assert [s["id"] for s in inbox] == [fresh.id]  # stale one expired on read
    db.expire_all()
    assert db.get(SharedWorkout, stale.id).status == "expired"

    assert client.post(f"/api/share/{fresh.id}/decline").json() == {"ok": True}
    db.expire_all()
    assert db.get(SharedWorkout, fresh.id).status == "declined"
    assert db.get(PlanDay, (b.id, TODAY)) is None  # nothing ever landed


def test_accept_refuses_done_days_and_intent_days(db, client):
    a, b = _seed(db)
    payload = sharing.build_payload(db, a, db.get(PlanDay, (a.id, TODAY)))
    tomorrow = TODAY + dt.timedelta(days=1)
    s1 = SharedWorkout(from_user_id=a.id, to_user_id=b.id, date=TODAY, payload=payload)
    s2 = SharedWorkout(from_user_id=a.id, to_user_id=b.id, date=tomorrow, payload=payload)
    db.add_all([s1, s2])
    db.add(PlanDay(user_id=b.id, date=TODAY, workout_type="easy_run",
                   title="Done", status="completed"))
    db.add(DayIntent(user_id=b.id, date=tomorrow, sport="surfing"))
    db.commit()

    _login(client, "gf", "secret2")
    assert client.post(f"/api/share/{s1.id}/accept",
                       json={"mode": "as_is"}).status_code == 409
    assert client.post(f"/api/share/{s2.id}/accept",
                       json={"mode": "as_is"}).status_code == 409
    # Landing-date override routes around the conflict.
    day_after = (TODAY + dt.timedelta(days=2)).isoformat()
    r = client.post(f"/api/share/{s2.id}/accept",
                    json={"mode": "as_is", "date": day_after})
    assert r.status_code == 200
    assert r.json()["day"]["date"] == day_after


# --- chat tool -------------------------------------------------------------------

def test_send_workout_tool(db):
    a, b = _seed(db)
    result, edit = dispatch(db, a.id, "send_workout_to_friend",
                            {"date": TODAY.isoformat(), "friend": "gf"})
    assert edit is None
    data = json.loads(result)
    assert data["status"] == "sent" and data["to"] == "Gf"
    share = db.scalars(db.query(SharedWorkout).statement).one()
    assert (share.from_user_id, share.to_user_id) == (a.id, b.id)

    result, _ = dispatch(db, a.id, "send_workout_to_friend",
                         {"date": TODAY.isoformat(), "friend": "nobody"})
    assert "household_members" in json.loads(result)

    # The recipient cannot be yourself, and the sender's own day is required.
    result, _ = dispatch(db, b.id, "send_workout_to_friend",
                         {"date": TODAY.isoformat(), "friend": "will"})
    assert "error" in json.loads(result)  # B has no plan day today
