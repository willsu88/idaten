"""Garmin Connect session management (unofficial `garminconnect` library).

One Garmin client per user. `Garmin.login(tokenstore)` handles the whole token
lifecycle itself: it loads cached OAuth tokens from the user's directory if
present, otherwise performs a password login and saves fresh tokens there.
Password logins are aggressively rate-limited by Garmin, so the token cache
directory must be persisted (it is a Docker volume — see docker-compose.yml).
"""

from __future__ import annotations

import os
import threading

from garminconnect import Garmin

from .. import crypto
from ..config import config
from ..models import User

_clients: dict[int, Garmin] = {}
_lock = threading.Lock()


def token_dir(user_id: int) -> str:
    return os.path.join(config.garmin_token_dir, str(user_id))


def _lock_down(user_dir: str) -> None:
    """Owner-only perms on the token store. The library writes token files with
    umask-default modes (world-readable on a stock Linux host), so enforce
    0700/0600 explicitly rather than trusting the deployment's umask."""
    os.chmod(os.path.dirname(user_dir), 0o700)
    os.chmod(user_dir, 0o700)
    for name in os.listdir(user_dir):
        os.chmod(os.path.join(user_dir, name), 0o600)


def has_garmin(user: User) -> bool:
    """Connected = cached tokens on disk, or credentials to log in with."""
    d = token_dir(user.id)
    if os.path.isdir(d) and os.listdir(d):
        return True
    return bool(user.garmin_email and user.garmin_password)


def get_garmin(user: User) -> Garmin:
    with _lock:
        client = _clients.get(user.id)
        if client is not None:
            return client

        tokens = token_dir(user.id)
        os.makedirs(tokens, mode=0o700, exist_ok=True)
        has_tokens = bool(os.listdir(tokens))
        if not has_tokens and not (user.garmin_email and user.garmin_password):
            raise RuntimeError(f"user {user.username} has no Garmin credentials connected")

        garmin = Garmin(
            email=user.garmin_email or None,
            password=crypto.decrypt(user.garmin_password) or None,
        )
        garmin.login(tokens)  # load cached tokens, or log in and save them
        _lock_down(tokens)

        _clients[user.id] = garmin
        return garmin


def drop_client(user_id: int) -> None:
    """Forget a cached client (e.g. after credentials change)."""
    with _lock:
        _clients.pop(user_id, None)
