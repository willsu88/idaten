"""Per-user daily chat message limit (spec: .scratch/coach-chat-cap).

The limit counts user-sent chat messages per calendar day (app timezone),
applies to everyone including the admin, and is enforced at POST /api/chat
before any LLM spend. Source of truth is the chat_messages table, so the
count survives restarts and matches what the admin page displays.
"""
from __future__ import annotations

import datetime as dt

from app.models import ChatMessage
from conftest import make_user

DEFAULT_CAP = 8  # everyone's cap until the admin edits it


class StubChatLLM:
    """Minimal stream-capable client: one final text round, no tools."""

    class _Resp:
        content = "Sounds good — keep it easy today."
        tool_calls = []
        is_final = True

    def stream(self, system, messages, tools, on_text=None):
        if on_text:
            on_text(self._Resp.content)
        return self._Resp()


def _login(client, username="will", password="secret1"):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200


def _stub_llm(monkeypatch):
    import app.chat.agent as agent

    monkeypatch.setattr(agent, "make_client", lambda *a, **kw: StubChatLLM())


def _seed_messages(db, user_id, n, *, days_ago=0, role="user"):
    ts = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days_ago)
    for _ in range(n):
        db.add(ChatMessage(user_id=user_id, session_id="s1", role=role,
                           content="hi", created_at=ts))
    db.commit()


def _send(client, text="how was my run?"):
    return client.post("/api/chat", json={"message": text})


# --- enforcement at POST /api/chat ------------------------------------------

def test_chat_blocked_at_default_cap(db, client, monkeypatch):
    make_user(db, "will")
    _seed_messages(db, 1, DEFAULT_CAP)
    _login(client)
    r = _send(client)
    assert r.status_code == 429
    assert "midnight" in r.json()["detail"].lower()


def test_admin_is_capped_like_everyone(db, client, monkeypatch):
    u = make_user(db, "will")
    u.is_admin = True
    db.commit()
    _seed_messages(db, u.id, DEFAULT_CAP)
    _login(client)
    assert _send(client).status_code == 429


def test_yesterdays_messages_do_not_count(db, client, monkeypatch):
    make_user(db, "will")
    _stub_llm(monkeypatch)
    _seed_messages(db, 1, DEFAULT_CAP, days_ago=2)
    _login(client)
    assert _send(client).status_code == 200


def test_assistant_rows_do_not_count(db, client, monkeypatch):
    make_user(db, "will")
    _stub_llm(monkeypatch)
    _seed_messages(db, 1, DEFAULT_CAP, role="assistant")
    _login(client)
    assert _send(client).status_code == 200


def test_send_consumes_quota(db, client, monkeypatch):
    """A successful send is counted: seed cap-1, send one (ok), next blocks."""
    make_user(db, "will")
    _stub_llm(monkeypatch)
    _seed_messages(db, 1, DEFAULT_CAP - 1)
    _login(client)
    ok = _send(client)
    assert ok.status_code == 200
    ok.read()  # drain the SSE stream so the message is persisted
    assert _send(client).status_code == 429


def test_cap_zero_disables_chat(db, client, monkeypatch):
    from app import chat_quota

    u = make_user(db, "will")
    chat_quota.set_cap(db, u.id, 0)
    _login(client)
    assert _send(client).status_code == 429


def test_cap_unlimited_never_blocks(db, client, monkeypatch):
    from app import chat_quota

    u = make_user(db, "will")
    _stub_llm(monkeypatch)
    chat_quota.set_cap(db, u.id, None)
    _seed_messages(db, u.id, DEFAULT_CAP + 5)
    _login(client)
    assert _send(client).status_code == 200


def test_burst_guard_fires_independently_of_daily_cap(db, client, monkeypatch):
    """A generous daily cap does not disable the 5-per-5-minutes burst guard."""
    from app import chat_quota, rate_limit

    u = make_user(db, "will")
    _stub_llm(monkeypatch)
    chat_quota.set_cap(db, u.id, None)
    _login(client)
    for _ in range(rate_limit.WINDOW_LIMIT):
        r = _send(client)
        assert r.status_code == 200
        r.read()
    assert _send(client).status_code == 429


def test_rejected_send_does_not_consume_quota(db, client):
    """A send refused before processing (too long / burst-limited) must not
    burn the member's daily budget."""
    from app import rate_limit

    make_user(db, "will")
    _login(client)
    assert _send(client, "x" * (rate_limit.MAX_MESSAGE_CHARS + 1)).status_code == 400
    assert client.get("/api/chat/sessions").json()["quota"]["used"] == 0


# --- admin: set-cap endpoint and usage columns -------------------------------

def _make_admin(db, username="will"):
    u = make_user(db, username)
    u.is_admin = True
    db.commit()
    return u


def test_admin_can_set_and_clear_a_members_cap(db, client):
    from app import chat_quota

    _make_admin(db)
    member = make_user(db, "julianne", "secret2")
    _login(client)
    r = client.put(f"/api/auth/users/{member.id}/chat_cap", json={"cap": 3})
    assert r.status_code == 200
    assert chat_quota.get_cap(db, member.id) == 3
    r = client.put(f"/api/auth/users/{member.id}/chat_cap", json={"cap": None})
    assert r.status_code == 200
    assert chat_quota.get_cap(db, member.id) is None  # unlimited


def test_set_cap_validates_input(db, client):
    _make_admin(db)
    member = make_user(db, "julianne", "secret2")
    _login(client)
    assert client.put(f"/api/auth/users/{member.id}/chat_cap",
                      json={"cap": -1}).status_code == 422
    assert client.put(f"/api/auth/users/{member.id}/chat_cap",
                      json={"cap": 99999}).status_code == 422
    assert client.put("/api/auth/users/999/chat_cap",
                      json={"cap": 3}).status_code == 404


def test_members_cannot_set_caps(db, client):
    _make_admin(db)
    member = make_user(db, "julianne", "secret2")
    _login(client, "julianne", "secret2")
    assert client.put(f"/api/auth/users/{member.id}/chat_cap",
                      json={"cap": 999}).status_code == 403


def test_usage_rows_carry_msgs_today_and_cap_for_every_account(db, client):
    from app import chat_quota

    admin = _make_admin(db)
    member = make_user(db, "julianne", "secret2")
    chat_quota.set_cap(db, member.id, 3)
    _seed_messages(db, member.id, 2)
    _seed_messages(db, member.id, 4, days_ago=2)  # older: not "today"
    _login(client)
    rows = {r["user_id"]: r for r in client.get("/api/auth/usage").json()["by_user"]}
    # Every account gets a row (even with zero LLM usage) so its cap is editable.
    assert rows[admin.id]["msgs_today"] == 0
    assert rows[admin.id]["chat_daily_cap"] == DEFAULT_CAP
    assert rows[member.id]["msgs_today"] == 2
    assert rows[member.id]["chat_daily_cap"] == 3


# --- member-facing quota visibility ------------------------------------------

def test_chat_sessions_reports_quota(db, client):
    u = make_user(db, "will")
    _seed_messages(db, u.id, 3)
    _login(client)
    body = client.get("/api/chat/sessions").json()
    assert body["quota"] == {"used": 3, "cap": DEFAULT_CAP}
    assert [s["id"] for s in body["sessions"]] == ["s1"]


def test_chat_stream_ends_with_fresh_quota(db, client, monkeypatch):
    """The SSE stream's final event carries the post-send count so the client
    can show "N left today" without refetching."""
    make_user(db, "will")
    _stub_llm(monkeypatch)
    _login(client)
    r = _send(client)
    assert r.status_code == 200
    events = [__import__("json").loads(line[len("data: "):])
              for line in r.text.splitlines() if line.startswith("data: ")]
    assert events[-1] == {"type": "quota", "used": 1, "cap": DEFAULT_CAP}


def test_settings_api_cannot_see_or_change_the_cap(db, client):
    from app import chat_quota

    u = make_user(db, "will")
    _login(client)
    assert "chat_daily_cap" not in client.get("/api/settings").json()
    client.put("/api/settings", json={"chat_daily_cap": 9999})
    assert chat_quota.get_cap(db, u.id) == DEFAULT_CAP
