"""The token store must be owner-only regardless of the deployment's umask.

The garminconnect library writes token files with umask-default modes (world-
readable on a stock Linux host), so `get_garmin` enforces 0700/0600 itself
(ADR 0015).
"""

import os
import stat

from conftest import make_user

from app import crypto
from app.garmin import client as gclient


class FakeGarmin:
    """Stands in for garminconnect.Garmin: login() writes a token file the way
    the real library does - via the process umask, no explicit mode."""

    def __init__(self, email=None, password=None):
        pass

    def login(self, tokenstore):
        with open(os.path.join(tokenstore, "garmin_tokens.json"), "w") as f:
            f.write("{}")


def _mode(path: str) -> int:
    return stat.S_IMODE(os.stat(path).st_mode)


def test_token_store_is_owner_only(db, tmp_path, monkeypatch):
    monkeypatch.setattr(gclient.config, "garmin_token_dir", str(tmp_path / "garmin_tokens"))
    monkeypatch.setattr(gclient, "Garmin", FakeGarmin)
    old_umask = os.umask(0o022)  # the permissive stock-Linux default
    try:
        user = make_user(db)
        user.garmin_email = "runner@example.com"
        user.garmin_password = crypto.encrypt("garmin-pass")
        db.commit()

        gclient.get_garmin(user)

        user_dir = gclient.token_dir(user.id)
        assert _mode(os.path.dirname(user_dir)) == 0o700
        assert _mode(user_dir) == 0o700
        assert _mode(os.path.join(user_dir, "garmin_tokens.json")) == 0o600
    finally:
        os.umask(old_umask)
        gclient.drop_client(user.id)
