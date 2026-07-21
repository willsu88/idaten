"""Gear: shoe predictor buckets/thresholds, Garmin swap write-through, endpoints."""

from __future__ import annotations

import datetime as dt
import io

from app.garmin.gear import (_bucket, _name_label, gear_suggestions,
                             set_activity_gear)
from app.models import Activity, Gear


def make_gear(db, user_id: int, uuid: str, name: str, **kw) -> Gear:
    g = Gear(uuid=uuid, user_id=user_id, name=name, gear_type="Shoes",
             status="active", **kw)
    db.add(g)
    db.commit()
    return g


def make_run(db, user_id: int, aid: int, days_ago: int, name: str,
             gear_uuid: str | None, speed: float = 3.0) -> Activity:
    a = Activity(id=aid, user_id=user_id,
                 date=dt.date.today() - dt.timedelta(days=days_ago),
                 type="running", name=name, gear_uuid=gear_uuid,
                 avg_speed_mps=speed)
    db.add(a)
    db.commit()
    return a


# --- bucketing -----------------------------------------------------------------

def test_name_label_parses_pushed_workout_names():
    assert _name_label("Xindian District - Tempo") == "tempo"
    assert _name_label("Base") == "base"
    assert _name_label("Xindian District - Long Run") == "long_run"
    assert _name_label("Xindian District Running") is None
    assert _name_label("Banqiao District - Zepro run NTPC") is None


def test_bucket_prefers_name_then_plan_then_pace(db, user):
    a = make_run(db, user.id, 1, 0, "X - Threshold", None, speed=4.0)
    assert _bucket(a, {}) == "plan:threshold"
    free = make_run(db, user.id, 2, 0, "Morning Running", None, speed=2.6)
    assert _bucket(free, {}) == "pace:easy"
    assert _bucket(free, {free.date: "easy_run"}) == "plan:easy_run"


# --- suggestions ---------------------------------------------------------------

def seed_habit(db, user_id: int, n_daily: int = 8):
    """8 base runs in the daily trainer + one recent base run in the racer."""
    make_gear(db, user_id, "daily", "Daily Trainer")
    make_gear(db, user_id, "racer", "Racer")
    for i in range(n_daily):
        make_run(db, user_id, 100 + i, 30 + i, "X - Base", "daily")
    return make_run(db, user_id, 200, 1, "X - Base", "racer")


def test_suggests_habit_shoe_for_outlier(db, user):
    outlier = seed_habit(db, user.id)
    sugg = gear_suggestions(db, user.id)
    assert len(sugg) == 1
    s = sugg[0]
    assert s["activity_id"] == outlier.id
    assert s["suggested"]["uuid"] == "daily"
    assert s["current"]["uuid"] == "racer"
    # own vote excluded: 8 of the other 8 runs agree
    assert s["confidence"] == 1.0


def test_no_suggestion_below_thresholds(db, user):
    # Mixed habit: 4/4 split never clears MIN_SHARE.
    make_gear(db, user.id, "a", "Shoe A")
    make_gear(db, user.id, "b", "Shoe B")
    for i in range(4):
        make_run(db, user.id, 300 + i, 30 + i, "X - Tempo", "a")
    for i in range(4):
        make_run(db, user.id, 310 + i, 20 + i, "X - Tempo", "b")
    make_run(db, user.id, 320, 1, "X - Tempo", "b")
    assert gear_suggestions(db, user.id) == []


def test_dismissed_and_old_runs_never_suggested(db, user):
    outlier = seed_habit(db, user.id)
    outlier.gear_suggestion_dismissed = True
    db.commit()
    assert gear_suggestions(db, user.id) == []
    outlier.gear_suggestion_dismissed = None
    outlier.date = dt.date.today() - dt.timedelta(days=60)  # outside window
    db.commit()
    assert gear_suggestions(db, user.id) == []


def test_retired_shoe_never_suggested(db, user):
    seed_habit(db, user.id)
    db.get(Gear, "daily").status = "retired"
    db.commit()
    assert gear_suggestions(db, user.id) == []


# --- Garmin write-through ------------------------------------------------------

class FakeGarminClient:
    def __init__(self):
        self.calls = []

    def request(self, method, subdomain, path, api=True):
        self.calls.append((method, path))


class FakeGarmin:
    """Activity currently wearing two shoes on Garmin's side."""

    def __init__(self, current):
        self.client = FakeGarminClient()
        self._current = current

    def get_activity_gear(self, activity_id):
        return self._current


def test_swap_unlinks_other_shoes_and_links_new(db, user):
    a = make_run(db, user.id, 1, 0, "X - Base", "old")
    garmin = FakeGarmin([
        {"uuid": "old", "gearTypeName": "Shoes"},
        {"uuid": "bike", "gearTypeName": "Bike"},  # untouched
    ])
    set_activity_gear(db, garmin, a, "new")
    assert garmin.client.calls == [
        ("PUT", "/gear-service/gear/unlink/old/activity/1"),
        ("PUT", "/gear-service/gear/link/new/activity/1"),
    ]
    assert a.gear_uuid == "new"


def test_swap_to_already_linked_shoe_is_idempotent(db, user):
    a = make_run(db, user.id, 1, 0, "X - Base", None)
    garmin = FakeGarmin([{"uuid": "new", "gearTypeName": "Shoes"}])
    set_activity_gear(db, garmin, a, "new")
    assert garmin.client.calls == []
    assert a.gear_uuid == "new"


def test_remove_shoe(db, user):
    a = make_run(db, user.id, 1, 0, "X - Base", "old")
    garmin = FakeGarmin([{"uuid": "old", "gearTypeName": "Shoes"}])
    set_activity_gear(db, garmin, a, None)
    assert garmin.client.calls == [("PUT", "/gear-service/gear/unlink/old/activity/1")]
    assert a.gear_uuid is None


# --- endpoints -----------------------------------------------------------------

def _login(client):
    r = client.post("/api/auth/login", json={"username": "will", "password": "secret1"})
    assert r.status_code == 200


def test_gear_list_and_image_roundtrip(db, user, client):
    _login(client)
    make_gear(db, user.id, "daily", "Daily Trainer",
              total_distance_m=491315.6, total_activities=93,
              maximum_meters=800000.0)

    r = client.get("/api/gear")
    assert r.status_code == 200
    [g] = r.json()
    assert g["name"] == "Daily Trainer"
    assert g["distance_km"] == 491.3
    assert g["limit_km"] == 800
    assert g["has_image"] is False

    png = b"\x89PNG\r\n\x1a\n" + b"0" * 32
    r = client.post("/api/gear/daily/image",
                    files={"file": ("shoe.png", io.BytesIO(png), "image/png")})
    assert r.status_code == 200 and r.json()["has_image"] is True

    r = client.get("/api/gear/daily/image")
    assert r.status_code == 200 and r.content == png

    r = client.delete("/api/gear/daily/image")
    assert r.status_code == 200 and r.json()["has_image"] is False
    assert client.get("/api/gear/daily/image").status_code == 404


def test_gear_image_rejects_wrong_type(db, user, client):
    _login(client)
    make_gear(db, user.id, "daily", "Daily Trainer")
    r = client.post("/api/gear/daily/image",
                    files={"file": ("shoe.gif", io.BytesIO(b"GIF89a"), "image/gif")})
    assert r.status_code == 422


def test_gear_tenant_isolation(db, user, client):
    from tests.conftest import make_user

    other = make_user(db, username="mal", password="secret1")
    make_gear(db, other.id, "theirs", "Their Shoe")
    _login(client)  # logs in as will
    assert client.get("/api/gear").json() == []
    r = client.post("/api/gear/theirs/image",
                    files={"file": ("x.png", io.BytesIO(b"\x89PNG"), "image/png")})
    assert r.status_code == 404


def test_set_activity_gear_endpoint_validates_ownership(db, user, client):
    _login(client)
    r = client.put("/api/activities/999/gear", json={"gear_uuid": None})
    assert r.status_code == 404


def test_dismiss_endpoint(db, user, client):
    _login(client)
    make_run(db, user.id, 1, 0, "X - Base", None)
    r = client.post("/api/activities/1/gear/dismiss")
    assert r.status_code == 200
    assert db.get(Activity, 1).gear_suggestion_dismissed is True
