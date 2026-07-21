"""Shared test setup.

The app reads config (and creates the SQLite engine) at import time, so the
test database path must be in the environment before any `app.*` import.
"""

from __future__ import annotations

import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="garmin_bot_test_")
os.environ["DB_PATH"] = os.path.join(_tmp, "test.db")
os.environ["GARMIN_TOKEN_DIR"] = os.path.join(_tmp, "tokens")
os.environ["GEAR_IMAGE_DIR"] = os.path.join(_tmp, "gear_images")
# TestClient talks plain HTTP; a Secure cookie would not flow back, breaking every
# authed test. Production defaults to secure=True (HTTPS behind the tunnel).
os.environ["COOKIE_SECURE"] = "false"
# setdefault so `pytest -m eval` can use a real key from the environment;
# ordinary unit tests stub the LLM and never touch the key.
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-used")

import pytest  # noqa: E402

from app.auth import hash_password  # noqa: E402
from app.db import Base, SessionLocal, engine, init_db  # noqa: E402
from app.models import User  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    """In-memory rate-limit + login-throttle state is process-global; clear it
    before each test so counters never leak between tests."""
    from app import rate_limit

    rate_limit.reset()
    yield


@pytest.fixture
def db():
    """A fresh database per test."""
    Base.metadata.drop_all(engine)
    init_db()
    s = SessionLocal()
    yield s
    s.close()


def make_user(db, username: str = "will", password: str = "secret1") -> User:
    u = User(username=username, display_name=username.capitalize(),
             password_hash=hash_password(password))
    db.add(u)
    db.commit()
    return u


@pytest.fixture
def user(db) -> User:
    return make_user(db)


@pytest.fixture
def client(db):
    """TestClient against a lifespan-free app (no scheduler threads in tests)."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api import auth_router, router

    test_app = FastAPI()
    test_app.include_router(auth_router)
    test_app.include_router(router)
    with TestClient(test_app) as c:
        yield c
