"""Coach-quality feedback: capture, provenance freezing, upsert, admin summary."""

from __future__ import annotations

import datetime as dt

from app import feedback
from app.models import Activity, DailyReview, PendingEdit
from tests.conftest import make_user

TODAY = dt.date.today()


def _seed_review(db, user_id, note="Solid week - keep it easy today."):
    r = DailyReview(user_id=user_id, date=TODAY, state="done_full", mode="editor",
                    coach_note=note, snapshot={"readiness_today": {"ok": True}},
                    prompt_version="abc123def456")
    db.merge(r)
    db.commit()
    return r


def _seed_analysis(db, user_id):
    a = Activity(id=42, user_id=user_id, date=TODAY, type="running",
                 distance_m=8000, duration_s=2400,
                 execution_score=72, execution_score_source="idaten",
                 execution_analysis="Nice control through the reps.",
                 execution_analysis_context={"execution_score": 72},
                 execution_analysis_prompt_version="feedbeef0001")
    db.add(a)
    db.commit()
    return a


# --- capture + provenance --------------------------------------------------------

def test_coach_note_rating_freezes_provenance(db, user):
    _seed_review(db, user.id)
    row = feedback.record(db, user.id, "coach_note", TODAY.isoformat(), 1)
    assert row is not None and row.rating == 1
    assert row.artifact_text.startswith("Solid week")
    assert row.context == {"readiness_today": {"ok": True}}
    assert row.prompt_version == "abc123def456"


def test_analysis_rating_freezes_provenance(db, user):
    _seed_analysis(db, user.id)
    row = feedback.record(db, user.id, "execution_analysis", "42", -1,
                          tags=["wrong", "bogus_tag"], comment="score contradicted")
    assert row.rating == -1
    assert row.tags == ["wrong"]  # unknown tags dropped
    assert row.context == {"execution_score": 72}
    assert row.prompt_version == "feedbeef0001"


def test_dismiss_reason_on_proposal(db, user):
    e = PendingEdit(user_id=user.id, summary="Ease Thursday", rationale="HRV low",
                    changes=[], current=[], status="dismissed")
    db.add(e)
    db.commit()
    row = feedback.record(db, user.id, "edit_proposal", str(e.id), None,
                          tags=["reasoning_wrong"])
    assert row.rating is None and row.tags == ["reasoning_wrong"]
    assert "Ease Thursday" in row.artifact_text


def test_upsert_updates_in_place(db, user):
    _seed_review(db, user.id)
    feedback.record(db, user.id, "coach_note", TODAY.isoformat(), 1)
    feedback.record(db, user.id, "coach_note", TODAY.isoformat(), -1, tags=["too_long"])
    state = feedback.feedback_state(db, user.id, "coach_note", TODAY.isoformat())
    assert state == {"rating": -1, "tags": ["too_long"], "comment": ""}
    from app.models import Feedback
    assert db.query(Feedback).count() == 1


def test_missing_or_foreign_artifact_rejected(db, user):
    other = make_user(db, username="julianne")
    _seed_review(db, other.id)
    # No review of Will's own on that date, and no cross-tenant rating.
    assert feedback.record(db, user.id, "coach_note", TODAY.isoformat(), 1) is None
    a = _seed_analysis(db, other.id)
    assert feedback.record(db, user.id, "execution_analysis", str(a.id), 1) is None


def test_prompt_version_is_stable_hash():
    v1 = feedback.prompt_version("You are a coach.")
    assert v1 == feedback.prompt_version("You are a coach.")
    assert v1 != feedback.prompt_version("You are a coach!")
    assert len(v1) == 12


# --- summary ---------------------------------------------------------------------

def test_summary_aggregates_and_lists_negatives(db, user):
    other = make_user(db, username="julianne")
    _seed_review(db, user.id)
    _seed_analysis(db, other.id)
    feedback.record(db, user.id, "coach_note", TODAY.isoformat(), 1)
    feedback.record(db, other.id, "execution_analysis", "42", -1,
                    tags=["off_tone"], comment="too clinical")
    s = feedback.summary(db, days=30)
    by_surface = {d["surface"]: d for d in s["by_surface"]}
    assert by_surface["coach_note"]["up"] == 1
    assert by_surface["execution_analysis"]["down"] == 1
    neg = s["recent_negative"]
    assert len(neg) == 1 and neg[0]["tags"] == ["off_tone"]
    assert neg[0]["has_context"] is True


# --- endpoints -------------------------------------------------------------------

def _login(client, db, username="will"):
    from app.auth import ensure_admin

    make_user(db, username=username, password="secret1")
    ensure_admin()  # promotes the earliest user
    r = client.post("/api/auth/login", json={"username": username, "password": "secret1"})
    assert r.status_code == 200


def test_feedback_endpoint_roundtrip(client, db):
    _login(client, db)  # first user = admin
    _seed_review(db, 1)
    r = client.post("/api/feedback", json={
        "surface": "coach_note", "ref": TODAY.isoformat(), "rating": -1,
        "tags": ["not_useful"], "comment": "generic"})
    assert r.status_code == 200
    assert r.json()["feedback"]["rating"] == -1

    # State rides the review payload.
    rv = client.get("/api/dashboard/review").json()["review"]
    assert rv["my_feedback"]["tags"] == ["not_useful"]

    # Admin summary sees it; validation rejects junk.
    s = client.get("/api/feedback/summary").json()
    assert s["by_surface"][0]["down"] == 1
    assert client.post("/api/feedback", json={
        "surface": "nope", "ref": "x", "rating": 1}).status_code == 422
    assert client.post("/api/feedback", json={
        "surface": "coach_note", "ref": TODAY.isoformat(), "rating": 5}).status_code == 422
    assert client.post("/api/feedback", json={
        "surface": "coach_note", "ref": "2020-01-01", "rating": 1}).status_code == 404


def test_summary_is_admin_only(client, db):
    # Second user is not admin (ensure_admin promotes the first).
    make_user(db, username="will")  # user 1
    _login(client, db, username="julianne")  # user 2, non-admin
    assert client.get("/api/feedback/summary").status_code == 403
