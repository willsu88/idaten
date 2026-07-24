"""Chat rate limiting — in-memory accident guards, not policy.

The burst guard (a few messages per 5 minutes) catches runaway clients; the
admin, whose API key it is, is exempt. The *daily* message cap is policy, not
plumbing: it lives in chat_quota (DB-backed, admin-configurable, applies to
everyone). One concurrent stream per user applies to everyone — that's about
correctness, not spend. In-memory on purpose: single process, two users.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException

from .models import User

WINDOW_S = 5 * 60
WINDOW_LIMIT = 5      # messages per 5 minutes (non-admin burst guard)
MAX_MESSAGE_CHARS = 2000

# Login brute-force throttle: after LOGIN_MAX failures in LOGIN_WINDOW_S, further
# attempts for that username are refused until the window rolls off. Keyed by the
# submitted username (lowercased) so guessing one account can't lock out others.
LOGIN_WINDOW_S = 15 * 60
LOGIN_MAX = 10
# A stream older than this is presumed dead (client vanished mid-stream, or the
# SSE write froze behind a tunnel) and gets cancelled + stolen by the next send.
# Real turns finish in well under this even at MAX_TOOL_ROUNDS.
STREAM_TTL_S = 5 * 60

_lock = threading.Lock()
_sent: dict[int, deque[float]] = defaultdict(deque)  # user_id -> message timestamps
_streaming: dict[int, tuple[int, float]] = {}        # user_id -> (gen, acquired_at)
_cancelled: dict[int, int] = {}                      # user_id -> cancel gens <= this
_gen: dict[int, int] = defaultdict(int)              # user_id -> last issued gen
_login_fails: dict[str, deque[float]] = defaultdict(deque)  # username -> fail times

clock = time.monotonic  # injectable for tests


def check_login(username: str) -> None:
    """Raise 429 if this username has too many recent failed logins. Call BEFORE
    verifying the password so lockout applies even to wrong-password attempts."""
    now = clock()
    with _lock:
        q = _login_fails[username]
        while q and now - q[0] > LOGIN_WINDOW_S:
            q.popleft()
        if len(q) >= LOGIN_MAX:
            raise HTTPException(
                429, "Too many failed sign-in attempts. Wait a few minutes and try again.")


def record_login_failure(username: str) -> None:
    now = clock()
    with _lock:
        q = _login_fails[username]
        while q and now - q[0] > LOGIN_WINDOW_S:
            q.popleft()
        q.append(now)


def clear_login_failures(username: str) -> None:
    """Wipe the failure count on a successful login."""
    with _lock:
        _login_fails.pop(username, None)


def check_message(user: User, message: str) -> None:
    """Raise 4xx before any LLM work happens. Records the message on success."""
    if len(message) > MAX_MESSAGE_CHARS:
        raise HTTPException(
            400, f"That message is too long (over {MAX_MESSAGE_CHARS} characters) — "
                 "try splitting it up.")
    if user.is_admin:
        return
    now = clock()
    with _lock:
        q = _sent[user.id]
        while q and now - q[0] > WINDOW_S:
            q.popleft()
        if len(q) >= WINDOW_LIMIT:
            raise HTTPException(
                429, "Give the coach a breather — a few messages every 5 minutes "
                     "is the limit. Try again shortly.")
        q.append(now)


def acquire_stream(user_id: int) -> int:
    """Take the user's one-stream slot; returns this stream's generation token.

    Cancellation is generation-scoped so a stale stop (or a stolen zombie's
    cancel) never kills a newer stream for the same user.
    """
    with _lock:
        held = _streaming.get(user_id)
        if held is not None:
            gen, acquired_at = held
            threshold = _cancelled.get(user_id)
            stopping = threshold is not None and threshold >= gen
            if not stopping and clock() - acquired_at < STREAM_TTL_S:
                raise HTTPException(
                    429, "The coach is still answering your last message — "
                         "wait for it to finish, or press stop.")
            # Already-stopping or zombie stream (dead client / frozen SSE
            # write): cancel it and take the slot right away.
            _cancelled[user_id] = max(_cancelled.get(user_id, 0), gen)
        _gen[user_id] += 1
        g = _gen[user_id]
        _streaming[user_id] = (g, clock())
        return g


def release_stream(user_id: int, gen: int) -> None:
    with _lock:
        held = _streaming.get(user_id)
        if held is not None and held[0] == gen:
            del _streaming[user_id]
        if _cancelled.get(user_id, 0) <= gen:
            _cancelled.pop(user_id, None)


def request_cancel(user_id: int) -> bool:
    """Ask the user's live stream to stop. False (no-op) if nothing is streaming."""
    with _lock:
        held = _streaming.get(user_id)
        if held is None:
            return False
        _cancelled[user_id] = max(_cancelled.get(user_id, 0), held[0])
        return True


def cancel_requested(user_id: int, gen: int) -> bool:
    with _lock:
        threshold = _cancelled.get(user_id)
        return threshold is not None and threshold >= gen


def reset() -> None:
    """Test helper."""
    with _lock:
        _sent.clear()
        _streaming.clear()
        _cancelled.clear()
        _gen.clear()
        _login_fails.clear()
