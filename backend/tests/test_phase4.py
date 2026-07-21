"""Phase 4: chat rate limits, coach styles, tutorial flag."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app import rate_limit
from app.planner import STYLE_PROMPTS, style_prompt
from app.settings_store import get_settings, put_settings

from conftest import make_user


@pytest.fixture(autouse=True)
def fresh_limits():
    rate_limit.reset()
    yield
    rate_limit.reset()
    rate_limit.clock = __import__("time").monotonic


def _tick(start=0.0):
    """Injectable clock advancing only when told."""
    state = {"t": start}

    def clock():
        return state["t"]

    return clock, state


def test_window_and_day_limits_for_members(db):
    member = make_user(db, "gf", "secret2")  # is_admin False
    clock, state = _tick()
    rate_limit.clock = clock

    for _ in range(rate_limit.WINDOW_LIMIT):
        rate_limit.check_message(member, "hi")
    with pytest.raises(HTTPException) as e:
        rate_limit.check_message(member, "hi")
    assert e.value.status_code == 429 and "5 minutes" in e.value.detail

    # Window clears after 5 minutes; day limit still applies
    sent = rate_limit.WINDOW_LIMIT
    while sent < rate_limit.DAY_LIMIT:
        state["t"] += rate_limit.WINDOW_S + 1
        for _ in range(min(rate_limit.WINDOW_LIMIT, rate_limit.DAY_LIMIT - sent)):
            rate_limit.check_message(member, "hi")
            sent += 1
    state["t"] += rate_limit.WINDOW_S + 1
    with pytest.raises(HTTPException) as e:
        rate_limit.check_message(member, "hi")
    assert e.value.status_code == 429 and "today" in e.value.detail.lower()

    # ...and resets after 24 h
    state["t"] += 24 * 3600 + 1
    rate_limit.check_message(member, "hi")


def test_admin_is_exempt_from_counts(db):
    admin = make_user(db, "will")
    admin.is_admin = True
    db.commit()
    for _ in range(rate_limit.DAY_LIMIT * 3):
        rate_limit.check_message(admin, "hi")


def test_message_length_cap_applies_to_everyone(db):
    admin = make_user(db, "will")
    admin.is_admin = True
    db.commit()
    with pytest.raises(HTTPException) as e:
        rate_limit.check_message(admin, "x" * (rate_limit.MAX_MESSAGE_CHARS + 1))
    assert e.value.status_code == 400


def test_one_concurrent_stream_per_user():
    g1 = rate_limit.acquire_stream(1)
    with pytest.raises(HTTPException) as e:
        rate_limit.acquire_stream(1)
    assert e.value.status_code == 429
    rate_limit.acquire_stream(2)  # other users unaffected
    rate_limit.release_stream(1, g1)
    rate_limit.acquire_stream(1)


def test_stale_stream_is_stolen_and_cancelled(monkeypatch):
    """A zombie stream (dead client, frozen SSE write) must not lock the user
    out forever: past STREAM_TTL_S the next send cancels it and takes the slot."""
    t = [0.0]
    monkeypatch.setattr(rate_limit, "clock", lambda: t[0])
    g1 = rate_limit.acquire_stream(1)
    with pytest.raises(HTTPException):
        rate_limit.acquire_stream(1)  # fresh stream still holds the slot
    t[0] += rate_limit.STREAM_TTL_S + 1
    g2 = rate_limit.acquire_stream(1)      # stolen, no 429
    assert rate_limit.cancel_requested(1, g1)      # zombie told to stop
    assert not rate_limit.cancel_requested(1, g2)  # new stream unaffected
    rate_limit.release_stream(1, g2)


def test_stopping_stream_frees_the_slot_immediately(monkeypatch):
    """After the user presses stop, a resend must not have to wait out the TTL."""
    g1 = rate_limit.acquire_stream(1)
    with pytest.raises(HTTPException):
        rate_limit.acquire_stream(1)
    assert rate_limit.request_cancel(1) is True
    g2 = rate_limit.acquire_stream(1)  # no 429: the old stream is winding down
    assert rate_limit.cancel_requested(1, g1)
    assert not rate_limit.cancel_requested(1, g2)
    rate_limit.release_stream(1, g1)   # zombie's late release must not evict g2
    with pytest.raises(HTTPException):
        rate_limit.acquire_stream(1)
    rate_limit.release_stream(1, g2)


def test_coach_style_setting_and_prompt_merge(db, user):
    s = get_settings(db, user.id)
    assert s["coach_style"] == "default" and s["tutorial_done"] is False
    # default adds no persona tone, but every style carries the house rule (no em-dashes)
    assert "em-dash" in style_prompt(s)

    s = put_settings(db, user.id, {"coach_style": "chill", "tutorial_done": True})
    assert s["coach_style"] == "chill" and s["tutorial_done"] is True
    # chill merges a non-empty tone prompt that forbids surfacing raw metrics
    assert "raw metric" in style_prompt(s)
    assert put_settings(db, user.id, {"coach_style": "bogus"})["coach_style"] == "chill"

    # Every style is tone-only: no style may weaken the approval/recovery rules
    assert "override" in STYLE_PROMPTS["strict"]


def test_chat_endpoint_enforces_limits(db, client):
    u = make_user(db, "gf", "secret2")
    client.post("/api/auth/login", json={"username": "gf", "password": "secret2"})
    long = client.post("/api/chat", json={"message": "x" * 3000})
    assert long.status_code == 400
    for _ in range(rate_limit.WINDOW_LIMIT):
        rate_limit.check_message(u, "hi")  # fill the window out-of-band
    r = client.post("/api/chat", json={"message": "hello"})
    assert r.status_code == 429
