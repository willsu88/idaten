"""Tenant isolation: user A must never see or mutate user B's data, whether
through the HTTP API or through the chat tool layer (whose user_id is bound
server-side and is not a tool parameter)."""

from __future__ import annotations

import datetime as dt
import json

from app.chat.tools import TOOL_SCHEMAS, dispatch
from app.models import Activity, DailyHealth, PendingEdit, PlanDay, Race
from conftest import make_user

TODAY = dt.date.today()


def _seed_two_users(db):
    a = make_user(db, "will", "secret1")
    b = make_user(db, "gf", "secret2")
    db.add(Activity(id=101, user_id=a.id, date=TODAY, type="running",
                    distance_m=10000, duration_s=3000, avg_hr=150, avg_speed_mps=3.3))
    db.add(Activity(id=202, user_id=b.id, date=TODAY, type="running",
                    distance_m=5000, duration_s=1800, avg_hr=140, avg_speed_mps=2.8))
    db.add(PlanDay(user_id=a.id, date=TODAY, workout_type="tempo", title="A tempo"))
    db.add(PlanDay(user_id=b.id, date=TODAY, workout_type="easy_run", title="B easy"))
    db.add(Race(user_id=a.id, name="A race", date=TODAY + dt.timedelta(days=30),
                distance_km=21.1, is_primary=True))
    db.add(Race(user_id=b.id, name="B race", date=TODAY + dt.timedelta(days=60),
                distance_km=10, is_primary=True))
    db.add(DailyHealth(user_id=a.id, date=TODAY, hrv=60, hrv_baseline=60))
    db.add(DailyHealth(user_id=b.id, date=TODAY, hrv=45, hrv_baseline=60))
    db.commit()
    return a, b


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200


def test_no_tool_schema_exposes_identity():
    for tool in TOOL_SCHEMAS:
        params = json.dumps(tool["function"]["parameters"])
        for needle in ("user", "account", "client_id", "tenant"):
            assert needle not in params.lower(), tool["function"]["name"]


def test_api_scopes_to_logged_in_user(db, client):
    _seed_two_users(db)
    _login(client, "gf", "secret2")

    acts = client.get("/api/activities").json()
    assert [a["id"] for a in acts] == [202]

    races = client.get("/api/races").json()
    assert [r["name"] for r in races] == ["B race"]

    week = client.get("/api/plan/week").json()["days"]
    assert [d["title"] for d in week] == ["B easy"]

    today = client.get("/api/dashboard/today").json()
    assert today["workout"]["title"] == "B easy"
    assert today["race"]["name"] == "B race"


def test_cannot_touch_another_users_rows_by_id(db, client):
    a, b = _seed_two_users(db)
    _login(client, "gf", "secret2")

    # A's activity: not readable, not ratable
    assert client.get("/api/activities/101").status_code == 404
    assert client.post("/api/activities/101/rpe", json={"rating": 5}).status_code == 404
    assert db.get(Activity, 101).rpe is None

    # A's race: not editable, not promotable, not deletable
    a_race = db.scalars(db.query(Race).where(Race.user_id == a.id).statement).first()
    assert client.put(f"/api/races/{a_race.id}", json={"name": "hacked"}).status_code == 404
    assert client.post(f"/api/races/{a_race.id}/primary").status_code == 404
    client.delete(f"/api/races/{a_race.id}")
    db.expire_all()
    assert db.get(Race, a_race.id) is not None  # delete silently no-ops on foreign rows


def test_edit_approval_scoped_to_owner(db, client):
    a, b = _seed_two_users(db)
    edit = PendingEdit(user_id=a.id, summary="A's edit", changes=[
        {"date": TODAY.isoformat(), "workout_type": "rest", "title": "Rest",
         "description": "", "rationale": "r"},
    ])
    db.add(edit)
    db.commit()

    _login(client, "gf", "secret2")
    assert client.get("/api/edits/pending").json() is None
    assert client.post(f"/api/edits/{edit.id}/accept").status_code == 404
    assert client.post(f"/api/edits/{edit.id}/dismiss").status_code == 404
    db.expire_all()
    assert db.get(PendingEdit, edit.id).status == "pending"
    assert db.get(PlanDay, (a.id, TODAY)).workout_type == "tempo"  # unchanged


def test_tool_dispatch_bound_to_user(db):
    a, b = _seed_two_users(db)

    result, _ = dispatch(db, b.id, "get_training_data",
                         {"start_date": TODAY.isoformat(), "end_date": TODAY.isoformat()})
    data = json.loads(result)
    assert [x["distance_km"] for x in data["activities"]] == [5.0]  # B's run only

    result, _ = dispatch(db, b.id, "get_current_plan", {})
    assert [d["title"] for d in json.loads(result)["days"]] == ["B easy"]

    # B proposing an edit for a date A also has only captures B's own current day
    result, edit = dispatch(db, b.id, "propose_plan_edit", {
        "summary": "s", "rationale": "r",
        "days": [{"date": TODAY.isoformat(), "workout_type": "rest", "title": "Rest",
                  "description": "", "rationale": "r"}],
    })
    assert edit.user_id == b.id
    assert edit.current[0]["title"] == "B easy"


def test_chat_history_scoped_by_user(db, client):
    from app.models import ChatMessage

    a, b = _seed_two_users(db)
    db.add(ChatMessage(user_id=a.id, session_id="s1", role="user", content="A's secret"))
    db.commit()

    _login(client, "gf", "secret2")
    assert client.get("/api/chat/sessions").json()["sessions"] == []
    assert client.get("/api/chat/history", params={"session_id": "s1"}).json() == []
