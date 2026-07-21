"""GET /api/activities?month= + GET /api/activities/months — the Activities
month navigator: one month per page, and the months-with-data index that
powers the arrows/picker."""

from __future__ import annotations

import datetime as dt

from app.models import Activity


def _login(client):
    assert client.post("/api/auth/login",
                       json={"username": "will", "password": "secret1"}).status_code == 200


def _seed(db, uid):
    db.add(Activity(id=1, user_id=uid, date=dt.date(2026, 7, 3), type="running", name="A"))
    db.add(Activity(id=2, user_id=uid, date=dt.date(2026, 7, 20), type="cycling", name="B"))
    db.add(Activity(id=3, user_id=uid, date=dt.date(2025, 12, 31), type="running", name="C"))
    db.commit()


def test_month_filter(client, db, user):
    _seed(db, user.id)
    _login(client)
    rows = client.get("/api/activities?month=2026-07").json()
    assert [a["id"] for a in rows] == [2, 1]  # newest first, July only
    rows = client.get("/api/activities?month=2025-12").json()
    assert [a["id"] for a in rows] == [3]
    # Month + type compose.
    rows = client.get("/api/activities?month=2026-07&type=running").json()
    assert [a["id"] for a in rows] == [1]
    assert client.get("/api/activities?month=nope").status_code == 422


def test_months_index(client, db, user):
    _seed(db, user.id)
    _login(client)
    res = client.get("/api/activities/months")
    assert res.status_code == 200  # must not be swallowed by /activities/{id}
    assert res.json() == [
        {"month": "2026-07", "count": 2},
        {"month": "2025-12", "count": 1},
    ]
