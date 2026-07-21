from __future__ import annotations

from app.auth import hash_password, verify_password
from conftest import make_user


def test_password_hash_roundtrip():
    h = hash_password("hunter22")
    assert h != "hunter22"
    assert verify_password("hunter22", h)
    assert not verify_password("wrong", h)
    assert not verify_password("hunter22", "not-a-hash")


def test_login_sets_cookie_and_me_works(db, client):
    make_user(db, "will", "secret1")
    r = client.post("/api/auth/login", json={"username": "will", "password": "secret1"})
    assert r.status_code == 200
    assert "gb_session" in r.cookies
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["username"] == "will"


def test_login_rejects_bad_credentials(db, client):
    make_user(db, "will", "secret1")
    assert client.post("/api/auth/login",
                       json={"username": "will", "password": "nope"}).status_code == 401
    assert client.post("/api/auth/login",
                       json={"username": "ghost", "password": "secret1"}).status_code == 401


def test_login_throttle_locks_out_after_repeated_failures(db, client):
    make_user(db, "will", "secret1")
    from app import rate_limit

    # The allowed budget of wrong-password attempts each returns 401...
    for _ in range(rate_limit.LOGIN_MAX):
        assert client.post("/api/auth/login",
                           json={"username": "will", "password": "nope"}).status_code == 401
    # ...the next attempt is refused with 429, even with the CORRECT password.
    assert client.post("/api/auth/login",
                       json={"username": "will", "password": "secret1"}).status_code == 429


def test_login_lockout_is_per_username(db, client):
    make_user(db, "will", "secret1")
    make_user(db, "gf", "secret2")
    from app import rate_limit

    for _ in range(rate_limit.LOGIN_MAX):
        client.post("/api/auth/login", json={"username": "will", "password": "nope"})
    # Guessing "will" must not lock out a different account.
    assert client.post("/api/auth/login",
                       json={"username": "gf", "password": "secret2"}).status_code == 200


def test_login_success_clears_failure_count(db, client):
    make_user(db, "will", "secret1")
    from app import rate_limit

    for _ in range(rate_limit.LOGIN_MAX - 1):
        client.post("/api/auth/login", json={"username": "will", "password": "nope"})
    # A success resets the counter, so a fresh run of failures does not lock out.
    assert client.post("/api/auth/login",
                       json={"username": "will", "password": "secret1"}).status_code == 200
    for _ in range(rate_limit.LOGIN_MAX):
        assert client.post("/api/auth/login",
                           json={"username": "will", "password": "nope"}).status_code == 401


def test_routes_require_auth(db, client):
    for path in ("/api/dashboard/today", "/api/plan/week", "/api/races",
                 "/api/activities", "/api/settings", "/api/sync/status",
                 "/api/chat/sessions", "/api/auth/me"):
        assert client.get(path).status_code == 401, path
    assert client.post("/api/sync").status_code == 401
    assert client.post("/api/chat", json={"message": "hi"}).status_code == 401


def test_logout_invalidates_session(db, client):
    make_user(db, "will", "secret1")
    client.post("/api/auth/login", json={"username": "will", "password": "secret1"})
    assert client.get("/api/auth/me").status_code == 200
    client.post("/api/auth/logout")
    assert client.get("/api/auth/me").status_code == 401


def test_users_are_created_via_invites_only(db, client):
    # The old direct add-member endpoint is gone (replaced by invite links)
    make_user(db, "will", "secret1")
    client.post("/api/auth/login", json={"username": "will", "password": "secret1"})
    body = {"username": "gf", "password": "secret2", "display_name": "GF"}
    assert client.post("/api/auth/users", json=body).status_code in (404, 405)


def test_change_password(db, client):
    make_user(db, "will", "secret1")
    client.post("/api/auth/login", json={"username": "will", "password": "secret1"})
    bad = client.post("/api/auth/password",
                      json={"current_password": "wrong", "new_password": "newpass1"})
    assert bad.status_code == 401
    ok = client.post("/api/auth/password",
                     json={"current_password": "secret1", "new_password": "newpass1"})
    assert ok.status_code == 200
    client.post("/api/auth/logout")
    assert client.post("/api/auth/login",
                       json={"username": "will", "password": "newpass1"}).status_code == 200
