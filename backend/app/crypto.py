"""Encryption at rest for stored third-party credentials (the Garmin password).

App passwords are bcrypt-hashed (one-way). A Garmin password is different: the
`garminconnect` library needs it to re-authenticate when cached OAuth tokens
expire, so it must be RECOVERABLE - it is symmetrically encrypted, never stored
plaintext.

Key resolution (first hit wins):
1. `SECRET_KEY` env var  -> a Fernet key derived from it (any passphrase works).
2. `<data_dir>/.secret_key` -> an auto-generated Fernet key, created 0600 on the
   first run and persisted on the data volume.

The key lives OUTSIDE the database and is NOT part of a `.db` backup, so a
database or backup leak alone cannot decrypt the credentials - which is the
whole point (see the security-hardening section of ROADMAP.md).

Stored values are tagged `gb1:<token>`. A value without the tag is treated as
legacy plaintext (from before encryption) and returned unchanged on read, so
reads never break mid-migration; `encrypt_existing_credentials` rewrites them.
"""

from __future__ import annotations

import base64
import hashlib
import os
import threading

from cryptography.fernet import Fernet, InvalidToken

from .config import config

_PREFIX = "gb1:"
_lock = threading.Lock()
_fernet: Fernet | None = None


def _data_dir() -> str:
    return os.path.dirname(config.db_path) or "."


def _load_key() -> bytes:
    """A urlsafe-base64 32-byte Fernet key, from SECRET_KEY or the key file."""
    if config.secret_key:
        # Any passphrase -> a valid Fernet key. Stable for a given SECRET_KEY.
        digest = hashlib.sha256(config.secret_key.encode()).digest()
        return base64.urlsafe_b64encode(digest)
    path = os.path.join(_data_dir(), ".secret_key")
    if os.path.exists(path):
        with open(path, "rb") as fh:
            return fh.read().strip()
    key = Fernet.generate_key()
    os.makedirs(_data_dir(), exist_ok=True)
    # O_EXCL + 0600: only the app user can read it, and we never clobber an
    # existing key (a concurrent creator wins; we re-read below).
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        with open(path, "rb") as fh:
            return fh.read().strip()
    with os.fdopen(fd, "wb") as fh:
        fh.write(key)
    return key


def _cipher() -> Fernet:
    global _fernet
    if _fernet is None:
        with _lock:
            if _fernet is None:
                _fernet = Fernet(_load_key())
    return _fernet


def is_encrypted(value: str | None) -> bool:
    return bool(value) and value.startswith(_PREFIX)


def encrypt(plaintext: str) -> str:
    return _PREFIX + _cipher().encrypt(plaintext.encode()).decode()


def decrypt(value: str | None) -> str | None:
    """Plaintext for a stored value. Untagged values are legacy plaintext,
    returned unchanged. A tagged value that will not decrypt means the key
    changed - fail loudly rather than hand ciphertext to Garmin as a password."""
    if not value or not value.startswith(_PREFIX):
        return value
    try:
        return _cipher().decrypt(value[len(_PREFIX):].encode()).decode()
    except InvalidToken as exc:
        raise RuntimeError(
            "cannot decrypt a stored credential - did SECRET_KEY / the key file "
            "change? The Garmin password must be re-entered."
        ) from exc
