"""The strength lane (Idea F Phase 2): weekly-target settings contract, the
deterministic signal, auto-matching, author placement, the proposal path, and
the manual endpoints."""

from __future__ import annotations

import datetime as dt

from app import support
from app.chat.tools import dispatch
from app.models import Activity, PendingEdit, SupportSession
from app.settings_store import get_settings, normalize_strength, put_settings
from tests.conftest import make_user

TODAY = dt.date.today()
MONDAY = TODAY - dt.timedelta(days=TODAY.weekday())


def _login(client, username="will", password="secret1"):
    assert client.post("/api/auth/login",
                       json={"username": username, "password": password}).status_code == 200


def _opt_in(db, uid, n=2, focus="coach"):
    put_settings(db, uid, {"strength": {"sessions_per_week": n, "focus": focus}})


# --- settings contract --------------------------------------------------------

def test_normalize_strength_clamps():
    assert normalize_strength(None) == {"sessions_per_week": 0, "focus": "coach"}
    assert normalize_strength({"sessions_per_week": 9, "focus": "biceps"}) == {
        "sessions_per_week": 0, "focus": "coach"}
    assert normalize_strength({"sessions_per_week": True}) == {
        "sessions_per_week": 0, "focus": "coach"}
    assert normalize_strength({"sessions_per_week": 3, "focus": "lower"}) == {
        "sessions_per_week": 3, "focus": "lower"}


def test_settings_roundtrip(db, user):
    _opt_in(db, user.id, 2, "upper")
    assert get_settings(db, user.id)["strength"] == {
        "sessions_per_week": 2, "focus": "upper"}


# --- signal + matching --------------------------------------------------------

def test_signal_none_until_opted_in(db, user):
    assert support.strength_signal(db, user.id, TODAY) is None


def test_signal_counts_and_remaining(db, user):
    _opt_in(db, user.id, 2)
    # A completed session Monday + an unplanned strength activity: both honor
    # the contract, but the same DAY only counts once.
    db.add(SupportSession(user_id=user.id, date=MONDAY, status="completed",
                          source="author"))
    db.add(Activity(id=1, user_id=user.id, date=MONDAY, type="strength_training",
                    name="Gym", duration_s=1800))
    db.commit()
    sig = support.strength_signal(db, user.id, TODAY)
    assert sig["target_per_week"] == 2
    assert sig["done_this_week"] == 1
    assert sig["remaining_to_plan"] == 1
    assert sig["planned_upcoming"] == []


def test_match_completes_planned_session(db, user):
    s = SupportSession(user_id=user.id, date=TODAY, source="author")
    db.add(s)
    db.add(Activity(id=7, user_id=user.id, date=TODAY, type="strength_training",
                    name="Gym", duration_s=1500))
    db.commit()
    assert support.match_completed(db, user.id, TODAY) == 1
    db.refresh(s)
    assert s.status == "completed" and s.activity_id == 7


def test_match_ignores_runs(db, user):
    db.add(SupportSession(user_id=user.id, date=TODAY, source="author"))
    db.add(Activity(id=8, user_id=user.id, date=TODAY, type="running",
                    name="Run", duration_s=1500))
    db.commit()
    assert support.match_completed(db, user.id, TODAY) == 0


# --- author placement ---------------------------------------------------------

def test_apply_sessions_clamps_and_validates(db, user):
    placed = support.apply_sessions(
        db, user.id,
        [
            {"date": TODAY.isoformat(), "duration_min": 25, "focus": "full body"},
            {"date": TODAY.isoformat(), "duration_min": 30},  # dup date dropped
            {"date": "bogus"},                                # bad date dropped
            {"date": (TODAY + dt.timedelta(days=2)).isoformat(), "duration_min": 30},
            {"date": (TODAY + dt.timedelta(days=4)).isoformat(), "duration_min": 30},
        ],
        source="author", today=TODAY, target=2, replace=True)
    assert len(placed) == 2  # clamped to target
    assert {s.date for s in placed} == {TODAY, TODAY + dt.timedelta(days=2)}


def test_replace_preserves_manual_and_completed(db, user):
    manual = SupportSession(user_id=user.id, date=TODAY + dt.timedelta(days=1),
                            source="manual")
    done = SupportSession(user_id=user.id, date=TODAY, status="completed",
                          source="author")
    stale = SupportSession(user_id=user.id, date=TODAY + dt.timedelta(days=3),
                           source="author")
    db.add_all([manual, done, stale])
    db.commit()
    support.apply_sessions(
        db, user.id, [{"date": (TODAY + dt.timedelta(days=5)).isoformat(),
                       "duration_min": 25, "focus": "lower"}],
        source="author", today=TODAY, target=3, replace=True)
    dates = {s.date: s for s in support.week_sessions(
        db, user.id, TODAY, TODAY + dt.timedelta(days=6))}
    assert TODAY + dt.timedelta(days=3) not in dates       # stale author row dropped
    assert dates[TODAY + dt.timedelta(days=1)].source == "manual"   # kept
    assert dates[TODAY].status == "completed"              # kept
    assert TODAY + dt.timedelta(days=5) in dates           # new placement


# --- proposal path ------------------------------------------------------------

def test_proposal_requires_opt_in(db, user):
    edit, error = support.create_strength_proposal(
        db, user.id, [{"date": TODAY.isoformat()}], "s", "r")
    assert edit is None and "not opted in" in error["error"]


def test_proposal_and_accept_endpoint(client, db, user):
    _opt_in(db, user.id, 2)
    edit, error = support.create_strength_proposal(
        db, user.id,
        [{"date": (TODAY + dt.timedelta(days=1)).isoformat(),
          "duration_min": 25, "focus": "hips & glutes", "rationale": "after easy day"}],
        "One strength session", "knee niggle prevention")
    assert error is None and edit.strength[0]["focus"] == "hips & glutes"
    _login(client)
    assert client.post(f"/api/edits/{edit.id}/accept").status_code == 200
    rows = support.week_sessions(db, user.id, TODAY, TODAY + dt.timedelta(days=6))
    assert len(rows) == 1 and rows[0].source == "chat_edit"


def test_chat_tool_dispatch(db, user):
    import json

    result, edit = dispatch(db, user.id, "propose_strength_sessions",
                            {"sessions": [{"date": TODAY.isoformat()}],
                             "summary": "s", "rationale": "r"})
    assert "error" in json.loads(result) and edit is None  # not opted in
    _opt_in(db, user.id, 1)
    result, edit = dispatch(db, user.id, "propose_strength_sessions",
                            {"sessions": [{"date": TODAY.isoformat(),
                                           "duration_min": 20, "focus": "full body",
                                           "rationale": "x"}],
                             "summary": "s", "rationale": "r"})
    assert json.loads(result)["status"] == "proposed" and edit is not None


# --- endpoints + payloads -----------------------------------------------------

def test_manual_add_complete_delete(client, db, user):
    _login(client)
    res = client.post("/api/strength", json={"date": TODAY.isoformat(),
                                             "duration_min": 30, "focus": "core"})
    assert res.status_code == 200
    sid = res.json()["id"]
    assert res.json()["source"] == "manual"
    done = client.post(f"/api/strength/{sid}/complete")
    assert done.json()["status"] == "completed"
    # A completed session on the date blocks a second manual add.
    assert client.post("/api/strength",
                       json={"date": TODAY.isoformat()}).status_code == 409
    assert client.delete(f"/api/strength/{sid}").json() == {"ok": True}


def test_tenant_isolation(client, db, user):
    other = make_user(db, "julianne", "secret2")
    s = SupportSession(user_id=other.id, date=TODAY, source="manual")
    db.add(s)
    db.commit()
    _login(client)
    assert client.post(f"/api/strength/{s.id}/complete").status_code == 404
    assert client.delete(f"/api/strength/{s.id}").status_code == 404


def test_today_and_week_payloads(client, db, user):
    _opt_in(db, user.id, 2)
    db.add(SupportSession(user_id=user.id, date=TODAY, duration_min=25,
                          focus="hips & glutes", rationale="why", source="author"))
    db.commit()
    _login(client)
    today = client.get("/api/dashboard/today").json()
    assert today["strength_session"]["focus"] == "hips & glutes"
    week = client.get(f"/api/plan/week?start={MONDAY.isoformat()}").json()
    assert week["summary"]["strength"] == {"target": 2, "done": 0}
    # No plan days exist, so days[] is empty — the summary is the week signal.


def test_snapshot_carries_strength(db, user):
    from app.planner import build_snapshot

    assert build_snapshot(db, user.id, TODAY)["strength"] is None
    _opt_in(db, user.id, 1)
    snap = build_snapshot(db, user.id, TODAY)
    assert snap["strength"]["target_per_week"] == 1


# --- review-initiated placements (editor mode) --------------------------------

REVIEW_TODAY = dt.date(2026, 7, 17)


class _StubReviewLLM:
    def __init__(self, result):
        self.result = result

    def complete_structured(self, system, messages, schema, name):
        return self.result


def _editor_setup(db, uid):
    from app.models import DailyHealth, TrainingPlan

    db.add(TrainingPlan(
        user_id=uid, garmin_plan_id=1, name="Plan",
        start_date=REVIEW_TODAY - dt.timedelta(days=50),
        end_date=REVIEW_TODAY + dt.timedelta(days=100),
        duration_weeks=25, phases=[],
        upcoming_tasks=[{"date": REVIEW_TODAY.isoformat(), "week": 8, "name": "Easy",
                         "training_effect": "AEROBIC_BASE", "rest_day": False,
                         "duration_min": 40}],
    ))
    db.add(DailyHealth(user_id=uid, date=REVIEW_TODAY, sleep_score=80,
                       hrv=50, hrv_baseline=50))
    db.commit()


def test_pending_edit_strength_only(db, user):
    from app.planner import create_pending_edit

    _opt_in(db, user.id, 2)
    edit, error = create_pending_edit(
        db, user.id, [], "Two strength sessions", "unplaced this week",
        TODAY, strength=[{"date": (TODAY + dt.timedelta(days=1)).isoformat(),
                          "duration_min": 25, "focus": "full body",
                          "rationale": "after easy day"}])
    assert error is None and edit.changes == [] and len(edit.strength) == 1


def test_pending_edit_rejects_empty_both(db, user):
    from app.planner import create_pending_edit

    edit, error = create_pending_edit(db, user.id, [], "s", "r", TODAY, strength=[])
    assert edit is None and error["error"] == "no days provided"


def test_muted_after_dismissed_strength_proposal(db, user):
    _opt_in(db, user.id, 2)
    edit, _ = support.create_strength_proposal(
        db, user.id, [{"date": TODAY.isoformat(), "duration_min": 25,
                       "focus": "x", "rationale": "y"}], "s", "r")
    assert support.strength_proposal_muted(db, user.id, TODAY) is False
    edit.status = "dismissed"
    db.commit()
    assert support.strength_proposal_muted(db, user.id, TODAY) is True


def test_run_only_dismissal_does_not_mute(db, user):
    db.add(PendingEdit(user_id=user.id, summary="run edit", changes=[{"date": "x"}],
                       current=[], status="dismissed"))
    db.commit()
    assert support.strength_proposal_muted(db, user.id, TODAY) is False


def test_editor_review_attaches_strength_placements(db, user, monkeypatch):
    import app.planner as planner
    from app.planner import evaluate_today, plan_mode

    _editor_setup(db, user.id)
    _opt_in(db, user.id, 2)
    assert plan_mode(db, user.id, REVIEW_TODAY) == "editor"
    place_date = (REVIEW_TODAY + dt.timedelta(days=2)).isoformat()
    stub = _StubReviewLLM({
        "coach_note": "All steady — I've suggested a strength session Sunday.",
        "should_propose": True,
        "proposal": {"summary": "One strength session", "rationale": "target unmet",
                     "days": [],
                     "strength_sessions": [{"date": place_date, "duration_min": 25,
                                            "focus": "hips & glutes",
                                            "rationale": "day after easy run"}]},
    })
    monkeypatch.setattr(planner, "make_client", lambda provider=None, **_kw: stub)
    review = evaluate_today(db, user.id, REVIEW_TODAY)
    assert review.proposal_id is not None
    edit = db.get(PendingEdit, review.proposal_id)
    assert edit.changes == [] and edit.strength[0]["date"] == place_date


def test_editor_review_strength_muted_by_dismissal(db, user, monkeypatch):
    import app.planner as planner
    from app.planner import evaluate_today

    _editor_setup(db, user.id)
    _opt_in(db, user.id, 2)
    # created_at (now) falls on/after the Monday of any current-or-past review
    # week, so this dismissal mutes the review's placements.
    db.add(PendingEdit(user_id=user.id, summary="s", changes=[], current=[],
                       strength=[{"date": REVIEW_TODAY.isoformat()}],
                       status="dismissed"))
    db.commit()
    stub = _StubReviewLLM({
        "coach_note": "Steady.",
        "should_propose": True,
        "proposal": {"summary": "One strength session", "rationale": "r",
                     "days": [],
                     "strength_sessions": [{"date": REVIEW_TODAY.isoformat(),
                                            "duration_min": 25, "focus": "x",
                                            "rationale": "y"}]},
    })
    monkeypatch.setattr(planner, "make_client", lambda provider=None, **_kw: stub)
    review = evaluate_today(db, user.id, REVIEW_TODAY)
    # Placements stripped -> empty proposal -> no pending edit created.
    assert review.proposal_id is None
    assert review.state == "done_full"


# --- accept-path regressions (code-review findings 2026-07-24) ----------------

def test_late_accept_keeps_dated_sessions(client, db, user):
    """Accepting days after the proposal was created must not drop sessions
    whose dates have since passed - the approval is the authority."""
    _opt_in(db, user.id, 2)
    created = TODAY - dt.timedelta(days=5)
    session_date = created + dt.timedelta(days=1)  # now 4 days in the past
    edit, error = support.create_strength_proposal(
        db, user.id,
        [{"date": session_date.isoformat(), "duration_min": 25,
          "focus": "full body", "rationale": "r"}],
        "s", "r", today=created)
    assert error is None
    edit.created_at = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=5)
    db.commit()
    _login(client)
    assert client.post(f"/api/edits/{edit.id}/accept").status_code == 200
    rows = support.week_sessions(db, user.id, created, created + dt.timedelta(days=6))
    assert [s.date for s in rows] == [session_date]


def test_accept_survives_target_lowered_after_proposal(client, db, user):
    """Lowering (or zeroing) the weekly target between proposal and accept must
    not silently no-op the accept - the athlete approved these exact sessions."""
    _opt_in(db, user.id, 2)
    edit, error = support.create_strength_proposal(
        db, user.id,
        [{"date": (TODAY + dt.timedelta(days=1)).isoformat(), "duration_min": 25,
          "focus": "full body", "rationale": "r"},
         {"date": (TODAY + dt.timedelta(days=3)).isoformat(), "duration_min": 25,
          "focus": "lower", "rationale": "r"}],
        "s", "r")
    assert error is None
    _opt_in(db, user.id, 0)  # feature turned off after the proposal
    _login(client)
    assert client.post(f"/api/edits/{edit.id}/accept").status_code == 200
    rows = support.week_sessions(db, user.id, TODAY, TODAY + dt.timedelta(days=6))
    assert len(rows) == 2
