"""Phase 3 membership: admin role, one-time invite links, password resets,
member removal (with full data wipe)."""

from __future__ import annotations

import datetime as dt

from app.auth import ensure_admin
from app.models import Activity, InviteToken, PlanDay, Setting, User

from conftest import make_user

TODAY = dt.date.today()


def _admin(db, client):
    u = make_user(db, "will", "secret1")
    u.is_admin = True
    db.commit()
    client.post("/api/auth/login", json={"username": "will", "password": "secret1"})
    return u


def _member(db, client_admin, username="gf", password="secret2"):
    path = client_admin.post("/api/auth/invites").json()["path"]
    token = path.rsplit("/", 1)[1]
    r = client_admin.post(f"/api/auth/invites/{token}/accept",
                          json={"username": username, "password": password})
    assert r.status_code == 200
    return r.json()["user"]


def test_ensure_admin_promotes_first_user(db):
    make_user(db, "will")
    make_user(db, "gf", "secret2")
    ensure_admin()
    db.expire_all()
    assert db.scalars(db.query(User).statement).first().is_admin
    ensure_admin()  # idempotent: second call changes nothing
    admins = [u for u in db.query(User) if u.is_admin]
    assert [u.username for u in admins] == ["will"]


def test_invite_roundtrip_and_single_use(db, client):
    _admin(db, client)
    path = client.post("/api/auth/invites").json()["path"]
    token = path.rsplit("/", 1)[1]

    check = client.get(f"/api/auth/invites/{token}").json()
    assert check == {"valid": True, "kind": "invite"}

    r = client.post(f"/api/auth/invites/{token}/accept",
                    json={"username": "gf", "password": "secret2"})
    assert r.status_code == 200
    user = r.json()["user"]
    assert user["username"] == "gf" and user["is_admin"] is False
    # Accepting logs the invitee straight in (cookie replaced the admin's)
    assert client.get("/api/auth/me").json()["username"] == "gf"

    # One-time: the same link is dead now
    assert client.get(f"/api/auth/invites/{token}").json() == {"valid": False}
    assert client.post(f"/api/auth/invites/{token}/accept",
                       json={"username": "xx", "password": "secret9"}).status_code == 410


def test_invite_requires_admin(db, client):
    _admin(db, client)
    _member(db, client)  # leaves the session logged in as the non-admin member
    assert client.post("/api/auth/invites").status_code == 403
    assert client.post("/api/auth/users/1/reset_link").status_code == 403
    assert client.delete("/api/auth/users/1").status_code == 403


def test_invite_expiry_and_username_conflict(db, client):
    _admin(db, client)
    path = client.post("/api/auth/invites").json()["path"]
    token = path.rsplit("/", 1)[1]
    assert client.post(f"/api/auth/invites/{token}/accept",
                       json={"username": "will", "password": "secret9"}).status_code == 409
    row = db.query(InviteToken).one()
    row.expires_at = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)
    db.commit()
    assert client.get(f"/api/auth/invites/{token}").json() == {"valid": False}
    assert client.post(f"/api/auth/invites/{token}/accept",
                       json={"username": "gf", "password": "secret2"}).status_code == 410


def test_password_reset_link(db, client):
    admin = _admin(db, client)
    member = _member(db, client)
    # Log back in as admin (accept switched the cookie to the member)
    client.post("/api/auth/login", json={"username": "will", "password": "secret1"})
    path = client.post(f"/api/auth/users/{member['id']}/reset_link").json()["path"]
    token = path.rsplit("/", 1)[1]
    check = client.get(f"/api/auth/invites/{token}").json()
    assert check == {"valid": True, "kind": "password_reset", "username": "gf"}

    r = client.post(f"/api/auth/invites/{token}/accept", json={"password": "brandnew1"})
    assert r.status_code == 200
    assert client.get("/api/auth/me").json()["username"] == "gf"
    # Old password dead, new one works
    assert client.post("/api/auth/login",
                       json={"username": "gf", "password": "secret2"}).status_code == 401
    assert client.post("/api/auth/login",
                       json={"username": "gf", "password": "brandnew1"}).status_code == 200
    assert admin.is_admin  # untouched


def test_members_list(db, client):
    _admin(db, client)
    _member(db, client)
    client.post("/api/auth/login", json={"username": "will", "password": "secret1"})
    members = client.get("/api/auth/members").json()
    assert [(m["username"], m["is_admin"], m["is_me"]) for m in members] == [
        ("will", True, True), ("gf", False, False)]


def test_members_list_is_admin_only(db, client):
    _admin(db, client)
    _member(db, client)  # accepting the invite logs the member in
    # The non-admin roster read is now forbidden (household administration).
    assert client.get("/api/auth/members").status_code == 403


def test_remove_user_wipes_data_and_protects_self(db, client):
    _admin(db, client)
    member = _member(db, client)
    uid = member["id"]
    db.add(Activity(id=1, user_id=uid, date=TODAY, type="running", name="r"))
    db.add(PlanDay(user_id=uid, date=TODAY))
    db.add(Setting(user_id=uid, key="athlete", value={}))
    db.commit()

    client.post("/api/auth/login", json={"username": "will", "password": "secret1"})
    assert client.delete("/api/auth/users/9999").status_code == 404
    me = client.get("/api/auth/me").json()
    assert client.delete(f"/api/auth/users/{me['id']}").status_code == 400  # not self

    assert client.delete(f"/api/auth/users/{uid}").json() == {"ok": True}
    db.expire_all()
    assert db.get(User, uid) is None
    assert db.query(Activity).filter_by(user_id=uid).count() == 0
    assert db.query(PlanDay).filter_by(user_id=uid).count() == 0
    assert db.query(Setting).filter_by(user_id=uid).count() == 0
    # The removed user's session is gone too
    assert client.post("/api/auth/login",
                       json={"username": "gf", "password": "secret2"}).status_code == 401
