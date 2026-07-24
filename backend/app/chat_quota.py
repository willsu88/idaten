"""Per-user daily chat message limit — admin-set policy, unlike rate_limit's
in-memory accident guards.

Counts user-sent chat messages (one POST /api/chat = one message, however many
LLM calls the agent loop fans out into) per calendar day in the app timezone.
Source of truth is the chat_messages table so enforcement, the admin page's
"Msgs today" column, and the member's remaining count all agree and survive
restarts. Applies to everyone, admin included — raising a cap happens on the
admin page, which never goes through the coach.
"""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import config
from .models import ChatMessage, User
from .settings_store import get_internal, put_internal

DEFAULT_DAILY_CAP = 8
CHAT_DAILY_CAP_KEY = "chat_daily_cap"  # server-owned: not in DEFAULTS, so the
# member-facing settings API can neither read nor write it.
UNLIMITED = "unlimited"  # stored sentinel (None in a JSON column reads as unset)
CAP_MAX = 1000


def day_start_utc(now: dt.datetime | None = None) -> dt.datetime:
    """Local midnight (app timezone) of the current day, as a UTC instant."""
    tz = ZoneInfo(config.timezone)
    local_now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(tz)
    return local_now.replace(hour=0, minute=0, second=0, microsecond=0) \
                    .astimezone(dt.timezone.utc)


def get_cap(db: Session, user_id: int) -> int | None:
    """The account's daily cap; None means unlimited."""
    v = get_internal(db, user_id, CHAT_DAILY_CAP_KEY)
    if v == UNLIMITED:
        return None
    if isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= CAP_MAX:
        return v
    return DEFAULT_DAILY_CAP


def set_cap(db: Session, user_id: int, cap: int | None) -> None:
    put_internal(db, user_id, CHAT_DAILY_CAP_KEY, UNLIMITED if cap is None else cap)


def used_today(db: Session, user_id: int) -> int:
    return db.scalar(
        select(func.count(ChatMessage.id)).where(
            ChatMessage.user_id == user_id,
            ChatMessage.role == "user",
            ChatMessage.created_at >= day_start_utc())) or 0


def quota_dict(db: Session, user_id: int) -> dict:
    """{"used": n, "cap": int | None} — None cap means unlimited."""
    return {"used": used_today(db, user_id), "cap": get_cap(db, user_id)}


def check(db: Session, user: User) -> None:
    """Raise 429 before any LLM spend when today's cap is used up."""
    cap = get_cap(db, user.id)
    if cap is None:
        return
    if used_today(db, user.id) >= cap:
        raise HTTPException(
            429, f"You've used today's {cap} coach messages. "
                 "The coach is back at midnight.")
