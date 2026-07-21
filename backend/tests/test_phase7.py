"""Phase 7 — honest shortcuts, stop button, admin-only provider, page hints."""

from __future__ import annotations

import json
from typing import Any, Callable

import pytest
from sqlalchemy import select

from app import rate_limit
from app.chat import agent as chat_agent
from app.chat.shortcuts import SHORTCUTS, expand
from app.config import config
from app.llm import Response
from app.models import ChatMessage
from app.settings_store import get_settings, put_settings

from conftest import make_user


@pytest.fixture(autouse=True)
def fresh_limits():
    rate_limit.reset()
    yield
    rate_limit.reset()


# --- shortcut expansion --------------------------------------------------------

def test_expand_known_commands_bare_and_with_args():
    for cmd in SHORTCUTS:
        text, is_shortcut = expand(cmd)
        assert is_shortcut and text == SHORTCUTS[cmd]["bare"]
    text, is_shortcut = expand("/sport surfing saturday ~90min")
    assert is_shortcut and "surfing saturday ~90min" in text and "/sport" not in text
    text, is_shortcut = expand("  /WEEK  ")  # whitespace + case tolerant
    assert is_shortcut and text == SHORTCUTS["/week"]["bare"]


def test_expand_passes_through_everything_else():
    for raw in ("hello coach", "/unknown thing", "/helpme", "week"):
        assert expand(raw) == (raw, False)


# --- chat turn: raw text displayed, expansion for the model ---------------------

class StubLLM:
    """Streams fixed deltas; optionally presses stop after the Nth delta."""

    def __init__(self, deltas: list[str], stop_after: int | None = None,
                 stop_user_id: int | None = None):
        self.deltas = deltas
        self.stop_after = stop_after
        self.stop_user_id = stop_user_id
        self.seen_messages: list[dict[str, Any]] | None = None

    def stream(self, system, messages, tools, on_text: Callable[[str], None]) -> Response:
        self.seen_messages = [dict(m) for m in messages]
        for i, delta in enumerate(self.deltas):
            on_text(delta)
            if self.stop_after == i and self.stop_user_id is not None:
                rate_limit.request_cancel(self.stop_user_id)
        return Response(content="".join(self.deltas))


def _run(db, user, message: str, stub: StubLLM, monkeypatch) -> list[dict]:
    monkeypatch.setattr(chat_agent, "make_client", lambda provider=None, **_kw: stub)
    llm_text, is_shortcut = expand(message)
    return list(chat_agent.run_chat(
        db, user, None, message,
        llm_text=llm_text, kind="shortcut" if is_shortcut else "text"))


def test_shortcut_persists_raw_but_model_sees_expansion(db, user, monkeypatch):
    stub = StubLLM(["Sounds ", "good."])
    events = _run(db, user, "/week", stub, monkeypatch)
    assert events[-1] == {"type": "done"}

    row = db.scalars(select(ChatMessage).where(ChatMessage.role == "user")).one()
    assert row.content == "/week"
    assert row.kind == "shortcut"
    assert row.payload == {"llm_text": SHORTCUTS["/week"]["bare"]}
    # The model got the expansion, not the raw command
    assert stub.seen_messages[-1] == {"role": "user",
                                      "content": SHORTCUTS["/week"]["bare"]}
    # History replay also feeds the expansion back to the model
    history = chat_agent._load_history(db, user.id, row.session_id)
    assert SHORTCUTS["/week"]["bare"] in [m["content"] for m in history]
    assert "/week" not in [m["content"] for m in history]


def test_proposal_markers_replayed_with_live_status(db, user):
    """History replay stamps each proposal marker with the edit's CURRENT status,
    so the model can tell a dead (dismissed/superseded) proposal from a live one
    and re-proposes instead of narrating a stale card."""
    from app.models import PendingEdit

    session_id = "sess-status"
    edits = {}
    for status in ("dismissed", "superseded", "pending"):
        e = PendingEdit(user_id=user.id, summary=f"{status} change",
                        changes=[], current=[], status=status)
        db.add(e)
        db.flush()
        edits[status] = e
        db.add(ChatMessage(user_id=user.id, session_id=session_id, role="assistant",
                           kind="edit_proposed", payload={"edit_id": e.id},
                           content=f"[Proposed plan edit #{e.id}: {status} change]"))
    db.commit()

    history = chat_agent._load_history(db, user.id, session_id)
    by_id = {edits[s].id: s for s in edits}
    stamped = {}
    for m in history:
        for eid, status in by_id.items():
            if f"#{eid}:" in m["content"]:
                stamped[status] = m["content"]
    assert "DISMISSED" in stamped["dismissed"]
    assert "SUPERSEDED" in stamped["superseded"]
    assert "PENDING" in stamped["pending"]


def test_plain_message_has_no_payload(db, user, monkeypatch):
    events = _run(db, user, "how was my run?", StubLLM(["Great."]), monkeypatch)
    assert events[-1] == {"type": "done"}
    row = db.scalars(select(ChatMessage).where(ChatMessage.role == "user")).one()
    assert row.kind == "text" and row.payload is None


# --- stop ----------------------------------------------------------------------

def test_stop_mid_stream_keeps_partial_and_releases(db, user, monkeypatch):
    gen = rate_limit.acquire_stream(user.id)
    stub = StubLLM(["Let me think. ", "NEVER-SENT"], stop_after=0,
                   stop_user_id=user.id)
    events = _run(db, user, "hello", stub, monkeypatch)

    assert {"type": "stopped"} in events
    assert {"type": "done"} not in events
    deltas = [e["delta"] for e in events if e["type"] == "text"]
    assert "NEVER-SENT" not in "".join(deltas)

    partial = db.scalars(select(ChatMessage).where(ChatMessage.role == "assistant")).one()
    assert partial.content == "Let me think."
    assert partial.payload == {"stopped": True}

    rate_limit.release_stream(user.id, gen)
    assert not rate_limit.cancel_requested(user.id, gen)


def test_cancel_flag_semantics():
    assert rate_limit.request_cancel(1) is False  # nothing streaming -> no-op
    g1 = rate_limit.acquire_stream(1)
    assert rate_limit.request_cancel(1) is True
    assert rate_limit.cancel_requested(1, g1)
    rate_limit.release_stream(1, g1)
    g2 = rate_limit.acquire_stream(1)  # a fresh stream never inherits a stale stop
    assert not rate_limit.cancel_requested(1, g2)
    rate_limit.release_stream(1, g2)


def test_stop_endpoint(db, client):
    make_user(db, "gf", "secret2")
    client.post("/api/auth/login", json={"username": "gf", "password": "secret2"})
    r = client.post("/api/chat/stop")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "stopping": False}


def test_chat_endpoint_expands_server_side(db, client, monkeypatch):
    make_user(db, "gf", "secret2")
    client.post("/api/auth/login", json={"username": "gf", "password": "secret2"})
    stub = StubLLM(["On it."])
    monkeypatch.setattr(chat_agent, "make_client", lambda provider=None, **_kw: stub)

    r = client.post("/api/chat", json={"message": "/replan"})
    assert r.status_code == 200
    types = [json.loads(line[6:])["type"]
             for line in r.text.splitlines() if line.startswith("data: ")]
    assert types[0] == "session" and types[-1] == "done"

    session_id = db.scalars(select(ChatMessage.session_id)).first()
    h = client.get(f"/api/chat/history?session_id={session_id}").json()
    assert h[0]["kind"] == "shortcut" and h[0]["content"] == "/replan"


# --- settings: admin-only provider + page hints ----------------------------------

def test_llm_provider_is_admin_only(db, client):
    admin = make_user(db, "will", "secret1")
    admin.is_admin = True
    member = make_user(db, "gf", "secret2")
    db.commit()

    client.post("/api/auth/login", json={"username": "gf", "password": "secret2"})
    s = client.put("/api/settings", json={"llm_provider": "openai"}).json()
    assert "llm_provider" not in s
    assert "llm_provider" not in client.get("/api/settings").json()
    # Even a pre-gate row (written before the rule) is ignored at read time
    put_settings(db, member.id, {"llm_provider": "openai"})  # simulates legacy row
    assert get_settings(db, member.id)["llm_provider"] == config.llm_provider

    client.post("/api/auth/login", json={"username": "will", "password": "secret1"})
    s = client.put("/api/settings", json={"llm_provider": "openai"}).json()
    assert s["llm_provider"] == "openai"
    assert get_settings(db, admin.id)["llm_provider"] == "openai"


def test_page_hints_seen_roundtrip_and_validation(db, user):
    assert get_settings(db, user.id)["page_hints_seen"] == []
    s = put_settings(db, user.id, {"page_hints_seen": ["week", "trends"]})
    assert s["page_hints_seen"] == ["week", "trends"]
    # Malformed values are dropped, the stored list survives
    assert put_settings(db, user.id, {"page_hints_seen": "week"})["page_hints_seen"] == ["week", "trends"]
    assert put_settings(db, user.id, {"page_hints_seen": [1, 2]})["page_hints_seen"] == ["week", "trends"]
