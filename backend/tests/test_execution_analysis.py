"""Phase 5: lazy execution-analysis generation + Today result card.

The LLM is stubbed — we test the GATING and CACHING (generate once, only for a
recent scored run, never for old history), not the prose.
"""
from __future__ import annotations

import datetime as dt

from app import planner
from app.models import Activity

TODAY = dt.date.today()


class StubLLM:
    def __init__(self):
        self.calls = 0

    def complete_structured(self, system, messages, schema, name):
        self.calls += 1
        return {"analysis": "You held the intervals well but cut the cooldown short."}


def _use_llm(monkeypatch, stub):
    monkeypatch.setattr(planner, "make_client", lambda provider=None, **_kw: stub)


def _scored_run(db, user_id, aid=1, date=TODAY, score=65):
    a = Activity(id=aid, user_id=user_id, date=date, type="running", name="Threshold",
                 distance_m=8000, duration_s=2400, execution_score=score,
                 execution_score_source="idaten",
                 execution_breakdown=[{"label": "INTERVAL", "axis": "hr",
                                       "target": [161, 173], "duration_s": 600,
                                       "avg_actual": 165, "score": 90}])
    db.add(a)
    db.commit()
    return a


def _login(client):
    assert client.post("/api/auth/login",
                       json={"username": "will", "password": "secret1"}).status_code == 200


def test_analysis_generates_once_then_caches(db, user, client, monkeypatch):
    stub = StubLLM()
    _use_llm(monkeypatch, stub)
    a = _scored_run(db, user.id)
    _login(client)

    r = client.post(f"/api/activities/{a.id}/analysis")
    assert r.status_code == 200 and "cooldown" in r.json()["analysis"]
    assert r.json()["coach"] == "default"  # persona stamped at generation time
    assert stub.calls == 1
    db.refresh(a)
    assert a.execution_analysis_coach == "default"

    # second call returns the cached text WITHOUT another LLM call
    r = client.post(f"/api/activities/{a.id}/analysis")
    assert r.status_code == 200 and stub.calls == 1


def test_analysis_refused_for_old_run(db, user, client, monkeypatch):
    stub = StubLLM()
    _use_llm(monkeypatch, stub)
    a = _scored_run(db, user.id, date=TODAY - dt.timedelta(days=10))
    _login(client)
    r = client.post(f"/api/activities/{a.id}/analysis")
    assert r.status_code == 400 and stub.calls == 0  # old history never spends


def test_analysis_refused_when_unscored(db, user, client, monkeypatch):
    stub = StubLLM()
    _use_llm(monkeypatch, stub)
    a = Activity(id=2, user_id=user.id, date=TODAY, type="running", name="Free run")
    db.add(a)
    db.commit()
    _login(client)
    assert client.post(f"/api/activities/{a.id}/analysis").status_code == 400
    assert stub.calls == 0


def test_today_surfaces_completed_workout(db, user, client):
    _scored_run(db, user.id)
    _login(client)
    payload = client.get("/api/dashboard/today").json()
    cw = payload["completed_workout"]
    assert cw and cw["execution_score"] == 65
    assert cw["execution_analysis"] is None  # not generated until the client asks
