from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .api import auth_router, router
from .auth import encrypt_existing_credentials, ensure_admin, ensure_initial_user
from .db import init_db
from .scheduler import start_scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    ensure_initial_user()
    ensure_admin()
    encrypt_existing_credentials()
    sched = start_scheduler()
    yield
    sched.shutdown(wait=False)


# No CORS middleware: the Next.js rewrite proxy makes the API same-origin,
# which also lets the session cookie flow without cross-site rules.
app = FastAPI(title="Idaten", lifespan=lifespan)
app.include_router(auth_router)
app.include_router(router)


@app.get("/health")
def health():
    return {"ok": True}
