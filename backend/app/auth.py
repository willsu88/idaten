"""Authentication: bcrypt passwords + server-side sessions in SQLite.

One layer, no JWT: the httpOnly cookie holds an opaque token that maps to an
auth_sessions row. `current_user` is the tenant boundary — every data route
depends on it, and everything downstream (queries, chat tools, Garmin clients)
takes the resolved User. Client input never chooses the account.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import logging
import os
import secrets
import shutil

import bcrypt
from fastapi import Cookie, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from . import crypto
from .config import config
from .db import LEGACY_USER_ID, get_db, session
from .models import AuthSession, InviteToken, User, utcnow

log = logging.getLogger(__name__)

COOKIE_NAME = "gb_session"
SESSION_DAYS = 90
INVITE_DAYS = 7


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:
        return False


def create_session(db: Session, user: User) -> str:
    token = secrets.token_hex(32)
    db.add(AuthSession(
        token=token,
        user_id=user.id,
        expires_at=utcnow() + dt.timedelta(days=SESSION_DAYS),
    ))
    db.commit()
    return token


def destroy_session(db: Session, token: str) -> None:
    db.execute(delete(AuthSession).where(AuthSession.token == token))
    db.commit()


def _as_utc(value: dt.datetime) -> dt.datetime:
    # SQLite hands datetimes back naive; they were written as UTC.
    return value if value.tzinfo else value.replace(tzinfo=dt.timezone.utc)


def current_user(
    gb_session: str | None = Cookie(default=None, alias=COOKIE_NAME),
    db: Session = Depends(get_db),
) -> User:
    if not gb_session:
        raise HTTPException(401, "not logged in")
    sess = db.get(AuthSession, gb_session)
    if sess is None or _as_utc(sess.expires_at) < utcnow():
        raise HTTPException(401, "session expired")
    user = db.get(User, sess.user_id)
    if user is None:
        raise HTTPException(401, "user no longer exists")
    return user


def admin_user(user: User = Depends(current_user)) -> User:
    """Dependency for membership management (invites, removals, resets)."""
    if not user.is_admin:
        raise HTTPException(403, "admin only")
    return user


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_invite_token(db: Session, created_by: int, kind: str,
                        user_id: int | None = None) -> tuple[str, InviteToken]:
    """Mint a one-time link token. Returns (raw_token, row) — the raw token is
    never stored and never shown again."""
    token = secrets.token_urlsafe(32)
    row = InviteToken(
        token_hash=_hash_token(token), kind=kind, user_id=user_id,
        created_by=created_by,
        expires_at=utcnow() + dt.timedelta(days=INVITE_DAYS),
    )
    db.add(row)
    db.commit()
    return token, row


def get_valid_invite(db: Session, token: str) -> InviteToken | None:
    row = db.scalars(
        select(InviteToken).where(InviteToken.token_hash == _hash_token(token))
    ).first()
    if row is None or row.used_at is not None or _as_utc(row.expires_at) < utcnow():
        return None
    return row


def delete_user_data(db: Session, user_id: int) -> None:
    """Remove a member and every row they own, plus their Garmin token cache."""
    from sqlalchemy import text

    from .db import Base
    from .garmin.client import drop_client

    for table in Base.metadata.sorted_tables:
        if "user_id" in table.columns:
            db.execute(text(f'DELETE FROM "{table.name}" WHERE user_id = :uid'),
                       {"uid": user_id})
    db.execute(delete(User).where(User.id == user_id))
    db.commit()
    drop_client(user_id)
    shutil.rmtree(os.path.join(config.garmin_token_dir, str(user_id)),
                  ignore_errors=True)


def ensure_admin() -> None:
    """Idempotent startup step: the earliest user becomes the admin if none is
    (covers both fresh bootstraps and databases upgraded in place)."""
    db = session()
    try:
        if db.scalars(select(User).where(User.is_admin.is_(True)).limit(1)).first():
            return
        first = db.scalars(select(User).order_by(User.id).limit(1)).first()
        if first is not None:
            first.is_admin = True
            db.commit()
            log.info("made user %r (id=%d) the admin", first.username, first.id)
    finally:
        db.close()


def encrypt_existing_credentials() -> None:
    """Startup migration: encrypt any legacy plaintext Garmin passwords in place.

    Idempotent - already-encrypted values (tagged) are skipped, so it is a no-op
    on every run after the first. Runs before the app serves traffic."""
    db = session()
    try:
        rows = db.scalars(select(User).where(User.garmin_password.is_not(None))).all()
        changed = 0
        for u in rows:
            if u.garmin_password and not crypto.is_encrypted(u.garmin_password):
                u.garmin_password = crypto.encrypt(u.garmin_password)
                changed += 1
        if changed:
            db.commit()
            log.info("encrypted %d legacy Garmin password(s) at rest", changed)
    finally:
        db.close()


def ensure_initial_user() -> None:
    """Bootstrap on startup: if no users exist, create the first one from env
    and adopt any pre-multi-user Garmin token cache into its per-user dir."""
    db = session()
    try:
        if db.scalars(select(User).limit(1)).first() is not None:
            return
        user = User(
            id=LEGACY_USER_ID,
            username=config.initial_username,
            display_name=config.initial_username.capitalize(),
            password_hash=hash_password(config.initial_password),
            garmin_email=config.garmin_email or None,
            garmin_password=crypto.encrypt(config.garmin_password)
            if config.garmin_password else None,
        )
        db.add(user)
        db.commit()
        log.info("bootstrapped initial user %r (id=%d)", user.username, user.id)
        _adopt_legacy_tokens(user.id)
    finally:
        db.close()


def _adopt_legacy_tokens(user_id: int) -> None:
    """Token files used to live directly in garmin_token_dir; move them into
    the first user's subdirectory."""
    root = config.garmin_token_dir
    if not os.path.isdir(root):
        return
    loose = [f for f in os.listdir(root) if os.path.isfile(os.path.join(root, f))]
    if not loose:
        return
    dest = os.path.join(root, str(user_id))
    os.makedirs(dest, exist_ok=True)
    for f in loose:
        shutil.move(os.path.join(root, f), os.path.join(dest, f))
    log.info("moved %d legacy Garmin token file(s) into %s", len(loose), dest)
