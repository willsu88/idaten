"""Encryption-at-rest for the stored Garmin password (app/crypto.py) + the
startup migration that encrypts legacy plaintext rows."""

from __future__ import annotations

from app import crypto
from app.auth import encrypt_existing_credentials
from app.models import User

from conftest import make_user


def test_encrypt_decrypt_roundtrip():
    token = crypto.encrypt("garmin-pw-123")
    assert token != "garmin-pw-123"
    assert crypto.is_encrypted(token)
    assert crypto.decrypt(token) == "garmin-pw-123"


def test_encrypt_is_nondeterministic():
    # Fernet embeds a random IV, so two encryptions of the same value differ but
    # both decrypt back - defends against equality analysis on the ciphertext.
    a, b = crypto.encrypt("same"), crypto.encrypt("same")
    assert a != b
    assert crypto.decrypt(a) == crypto.decrypt(b) == "same"


def test_legacy_plaintext_is_passed_through():
    # A pre-encryption value carries no tag: read it unchanged, never try to
    # decrypt it (that would corrupt a real password that happens to be stored).
    assert not crypto.is_encrypted("plainpw")
    assert crypto.decrypt("plainpw") == "plainpw"
    assert crypto.decrypt(None) is None
    assert crypto.decrypt("") == ""


def test_encrypt_existing_credentials_migrates_only_plaintext(db):
    plain = make_user(db, "will", "secret1")
    plain.garmin_password = "legacy-plain"  # a pre-encryption row
    already = make_user(db, "gf", "secret2")
    already.garmin_password = crypto.encrypt("already-enc")
    none_user = make_user(db, "nc", "secret3")  # no Garmin password at all
    db.commit()
    already_before = already.garmin_password

    encrypt_existing_credentials()

    db.expire_all()
    assert crypto.decrypt(db.get(User, plain.id).garmin_password) == "legacy-plain"
    assert crypto.is_encrypted(db.get(User, plain.id).garmin_password)
    # Already-encrypted row is untouched (not double-wrapped).
    assert db.get(User, already.id).garmin_password == already_before
    assert db.get(User, none_user.id).garmin_password is None
