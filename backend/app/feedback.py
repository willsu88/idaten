"""Coach-quality feedback (Idea D) — capture layer of the four-stage loop.

See COACH_QUALITY.md at the repo root for the full operating model. This module
is Stage 1: every rating freezes the rated output AND the inputs that produced
it into one row, so a thumbs-down arrives pre-packaged as a reproducible eval
case. Nothing here feeds back into the live coach — raw feedback never touches
a prompt; it is reviewed by a human (Stages 3-4).
"""

from __future__ import annotations

import datetime as dt
import hashlib

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Activity, DailyReview, Feedback, PendingEdit

SURFACES = ("coach_note", "execution_analysis", "edit_proposal")

# Preset reason chips. The first four are the thumbs-down chips; the last two
# are the proposal-dismiss reasons ("didn't want the change" is a preference,
# "the reasoning was wrong" is the quality signal).
TAGS = ("wrong", "off_tone", "too_long", "not_useful",
        "didnt_want_change", "reasoning_wrong")


def prompt_version(system: str) -> str:
    """Short stable hash of a system prompt, stamped on generated artifacts so
    quality can be attributed to prompt revisions."""
    return hashlib.sha256(system.encode()).hexdigest()[:12]


def _resolve_artifact(db: Session, user_id: int, surface: str,
                      ref: str) -> tuple[str, dict | None, str | None] | None:
    """Locate the rated artifact (ownership-checked) and freeze its text,
    producing context, and prompt version. None = not found / not the user's."""
    if surface == "coach_note":
        try:
            date = dt.date.fromisoformat(ref)
        except ValueError:
            return None
        r = db.get(DailyReview, (user_id, date))
        if r is None or not r.coach_note:
            return None
        return r.coach_note, r.snapshot, r.prompt_version
    if surface == "execution_analysis":
        try:
            a = db.get(Activity, int(ref))
        except ValueError:
            return None
        if a is None or a.user_id != user_id or not a.execution_analysis:
            return None
        return a.execution_analysis, a.execution_analysis_context, \
            a.execution_analysis_prompt_version
    if surface == "edit_proposal":
        try:
            e = db.get(PendingEdit, int(ref))
        except ValueError:
            return None
        if e is None or e.user_id != user_id:
            return None
        text = f"{e.summary}\n\n{e.rationale}".strip()
        return text, {"changes": e.changes, "current": e.current}, None
    return None


def record(db: Session, user_id: int, surface: str, ref: str,
           rating: int | None, tags: list[str] | None = None,
           comment: str = "") -> Feedback | None:
    """Upsert one rating per (user, surface, artifact). Returns None when the
    artifact doesn't exist or isn't the user's."""
    resolved = _resolve_artifact(db, user_id, surface, str(ref))
    if resolved is None:
        return None
    text, context, pv = resolved
    tags = [t for t in (tags or []) if t in TAGS]
    row = db.scalars(
        select(Feedback).where(Feedback.user_id == user_id,
                               Feedback.surface == surface,
                               Feedback.artifact_ref == str(ref))
    ).first()
    if row is None:
        row = Feedback(user_id=user_id, surface=surface, artifact_ref=str(ref))
        db.add(row)
    row.rating = rating
    row.tags = tags
    row.comment = comment or ""
    row.artifact_text = text
    row.context = context
    row.prompt_version = pv
    db.commit()
    return row


def feedback_state(db: Session, user_id: int, surface: str, ref) -> dict | None:
    """The caller's existing rating on an artifact, for UI state."""
    row = db.scalars(
        select(Feedback).where(Feedback.user_id == user_id,
                               Feedback.surface == surface,
                               Feedback.artifact_ref == str(ref))
    ).first()
    if row is None:
        return None
    return {"rating": row.rating, "tags": row.tags or [], "comment": row.comment}


def summary(db: Session, days: int = 90) -> dict:
    """Stage-2 admin aggregation: per-surface and per-user thumb rates plus the
    recent negative list (each entry a ready-made eval case)."""
    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
    rows = db.scalars(
        select(Feedback).where(Feedback.updated_at >= since)
        .order_by(Feedback.updated_at.desc())
    ).all()

    def bucket() -> dict:
        return {"up": 0, "down": 0, "dismiss_reasons": 0}

    by_surface: dict[str, dict] = {}
    by_user: dict[int, dict] = {}
    negatives = []
    for r in rows:
        for d in (by_surface.setdefault(r.surface, bucket()),
                  by_user.setdefault(r.user_id, bucket())):
            if r.rating == 1:
                d["up"] += 1
            elif r.rating == -1:
                d["down"] += 1
            else:
                d["dismiss_reasons"] += 1
        if r.rating == -1 or (r.rating is None and "reasoning_wrong" in (r.tags or [])):
            negatives.append({
                "surface": r.surface, "user_id": r.user_id,
                "artifact_ref": r.artifact_ref, "tags": r.tags or [],
                "comment": r.comment, "artifact_text": r.artifact_text,
                "prompt_version": r.prompt_version,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
                "has_context": r.context is not None,
            })
    return {
        "days": days,
        "by_surface": [{"surface": s, **d} for s, d in sorted(by_surface.items())],
        "by_user": [{"user_id": u, **d} for u, d in sorted(by_user.items())],
        "recent_negative": negatives[:50],
    }
