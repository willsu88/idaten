"""Week reorder: POST /api/plan/reorder swaps whole-day content between dates.

Spec: .scratch/week-reorder/spec.md. Semantics are date reassignment (no order
column): a drag swaps content between planned future days. Locked: past days,
completed/skipped days. Intents and planned strength ride with their day.
Pushed days are deleted from the watch and re-pushed in the new arrangement.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select

from app.models import DayIntent, PlanDay, PlanVersion, SupportSession

TODAY = dt.date.today()
# All-future dates guaranteed to share one ISO week: next week's Monday onward.
MON = TODAY + dt.timedelta(days=7 - TODAY.weekday())
TUE = MON + dt.timedelta(days=1)
WED = MON + dt.timedelta(days=2)


def _login(client):
    assert client.post("/api/auth/login",
                       json={"username": "will", "password": "secret1"}).status_code == 200


def _day(db, user_id, date, wt="easy_run", title=None, **kw):
    row = PlanDay(user_id=user_id, date=date, workout_type=wt,
                  title=title or wt.replace("_", " ").title(), **kw)
    db.add(row)
    db.commit()
    return row


def _swap(client, a: dt.date, b: dt.date):
    return client.post("/api/plan/reorder", json={"moves": [
        {"date": a.isoformat(), "content_from": b.isoformat()},
        {"date": b.isoformat(), "content_from": a.isoformat()},
    ]})


class FakeGarmin:
    def __init__(self, fail_upload=False):
        self.deleted: list[str] = []
        self.scheduled: list[tuple[str, str]] = []
        self.fail_upload = fail_upload
        self._next_id = 500

    def delete_workout(self, workout_id):
        self.deleted.append(str(workout_id))

    def upload_workout(self, payload):
        if self.fail_upload:
            raise RuntimeError("garmin down")
        self._next_id += 1
        return {"workoutId": self._next_id}

    def schedule_workout(self, workout_id, date):
        self.scheduled.append((str(workout_id), date))


def test_reorder_swaps_content_and_records_version(client, db, user):
    _day(db, user.id, MON, "tempo", "Tempo 40", duration_min=40, rationale="quality")
    _day(db, user.id, TUE, "easy_run", "Easy 30", duration_min=30)
    _login(client)
    r = _swap(client, MON, TUE)
    assert r.status_code == 200
    assert sorted(r.json()["moved"]) == sorted([MON.isoformat(), TUE.isoformat()])

    db.expire_all()
    mon, tue = db.get(PlanDay, (user.id, MON)), db.get(PlanDay, (user.id, TUE))
    assert (mon.workout_type, mon.title, mon.duration_min) == ("easy_run", "Easy 30", 30)
    assert (tue.workout_type, tue.title, tue.duration_min) == ("tempo", "Tempo 40", 40)
    assert tue.rationale == "quality"

    version = db.scalars(  # the reorder event the daily review grounds on
        select(PlanVersion)
        .where(PlanVersion.user_id == user.id, PlanVersion.source == "reorder")).first()
    assert version is not None
    assert mon.version_id == version.id and tue.version_id == version.id


def test_reorder_reflected_in_week_payload(client, db, user):
    _day(db, user.id, MON, "tempo", "Tempo 40")
    _day(db, user.id, TUE, "easy_run", "Easy 30")
    _login(client)
    assert _swap(client, MON, TUE).status_code == 200
    days = {d["date"]: d for d in
            client.get(f"/api/plan/week?start={MON.isoformat()}").json()["days"]}
    assert days[MON.isoformat()]["title"] == "Easy 30"
    assert days[TUE.isoformat()]["title"] == "Tempo 40"


def test_reorder_rejects_past_days(client, db, user):
    last_mon = MON - dt.timedelta(days=14)
    _day(db, user.id, last_mon, "tempo")
    _day(db, user.id, last_mon + dt.timedelta(days=1), "easy_run")
    _login(client)
    r = _swap(client, last_mon, last_mon + dt.timedelta(days=1))
    assert r.status_code == 422
    db.expire_all()
    assert db.get(PlanDay, (user.id, last_mon)).workout_type == "tempo"  # untouched


def test_reorder_rejects_completed_day(client, db, user):
    _day(db, user.id, MON, "tempo", status="completed")
    _day(db, user.id, TUE, "easy_run")
    _login(client)
    assert _swap(client, MON, TUE).status_code == 422


def test_reorder_rejects_non_permutation(client, db, user):
    _day(db, user.id, MON, "tempo")
    _day(db, user.id, TUE, "easy_run")
    _login(client)
    r = client.post("/api/plan/reorder", json={"moves": [
        {"date": MON.isoformat(), "content_from": TUE.isoformat()},
    ]})
    assert r.status_code == 422


def test_reorder_rejects_cross_week(client, db, user):
    next_mon = MON + dt.timedelta(days=7)
    _day(db, user.id, MON, "tempo")
    _day(db, user.id, next_mon, "easy_run")
    _login(client)
    assert _swap(client, MON, next_mon).status_code == 422


def test_reorder_rejects_missing_day(client, db, user):
    _day(db, user.id, MON, "tempo")
    _login(client)
    assert _swap(client, MON, TUE).status_code == 422


def test_reorder_moves_intent_with_its_day(client, db, user):
    _day(db, user.id, MON, "cross_train", "Climbing")
    _day(db, user.id, TUE, "easy_run", "Easy 30")
    db.add(DayIntent(user_id=user.id, date=MON, sport="climbing", note="with friends"))
    db.commit()
    _login(client)
    assert _swap(client, MON, TUE).status_code == 200
    db.expire_all()
    assert db.get(DayIntent, (user.id, MON)) is None
    moved = db.get(DayIntent, (user.id, TUE))
    assert moved is not None and moved.sport == "climbing" and moved.note == "with friends"


def test_reorder_moves_planned_strength_with_its_day(client, db, user):
    _day(db, user.id, MON, "easy_run")
    _day(db, user.id, TUE, "rest")
    db.add(SupportSession(user_id=user.id, date=MON, kind="strength",
                          focus="hips", status="planned"))
    db.commit()
    _login(client)
    assert _swap(client, MON, TUE).status_code == 200
    db.expire_all()
    sessions = db.query(SupportSession).filter_by(user_id=user.id).all()
    assert [s.date for s in sessions] == [TUE]


def test_reorder_repushes_moved_pushed_day(client, db, user, monkeypatch):
    fake = FakeGarmin()
    from app.garmin import push as push_mod
    monkeypatch.setattr(push_mod, "get_garmin", lambda u: fake)

    _day(db, user.id, MON, "tempo", "Tempo 40", duration_min=40,
         garmin_workout_id="111",
         pushed_at=dt.datetime.now(dt.timezone.utc))
    _day(db, user.id, TUE, "easy_run", "Easy 30", duration_min=30)
    _login(client)
    assert _swap(client, MON, TUE).status_code == 200

    # Old workout deleted from the watch; the moved (previously pushed) content
    # re-pushed at its new date; the never-pushed content stays unpushed.
    assert fake.deleted == ["111"]
    assert [d for _, d in fake.scheduled] == [TUE.isoformat()]
    db.expire_all()
    mon, tue = db.get(PlanDay, (user.id, MON)), db.get(PlanDay, (user.id, TUE))
    assert mon.pushed_at is None and mon.garmin_workout_id is None
    assert tue.pushed_at is not None and tue.garmin_workout_id is not None


def test_reorder_push_failure_clears_pushed_state(client, db, user, monkeypatch):
    fake = FakeGarmin(fail_upload=True)
    from app.garmin import push as push_mod
    monkeypatch.setattr(push_mod, "get_garmin", lambda u: fake)

    _day(db, user.id, MON, "tempo", garmin_workout_id="111",
         pushed_at=dt.datetime.now(dt.timezone.utc))
    _day(db, user.id, TUE, "easy_run")
    _login(client)
    r = _swap(client, MON, TUE)
    assert r.status_code == 200  # the reorder itself succeeded
    assert r.json()["push_errors"]  # ...but the re-push is reported as failed
    db.expire_all()
    # pushed state cleared everywhere so the UI shows the push affordance
    assert db.get(PlanDay, (user.id, MON)).pushed_at is None
    assert db.get(PlanDay, (user.id, TUE)).pushed_at is None


def test_reordered_days_become_revertible_in_editor_mode(client, db, user):
    """A reordered day diverges from the Garmin base -> revertible recomputes true."""
    from app.models import TrainingPlan
    from app.planner import materialize_coach_plan

    tasks = [
        {"date": MON.isoformat(), "week": 8, "name": "Threshold",
         "training_effect": "LACTATE_THRESHOLD", "rest_day": False,
         "duration_min": 38, "description": "18:00@172bpm"},
        {"date": TUE.isoformat(), "week": 8, "name": "Base",
         "training_effect": "AEROBIC_BASE", "rest_day": False,
         "duration_min": 45, "description": "45:00@150bpm"},
    ]
    db.add(TrainingPlan(
        user_id=user.id, garmin_plan_id=1, name="SUPERACE",
        start_date=TODAY - dt.timedelta(days=10), end_date=TODAY + dt.timedelta(days=100),
        duration_weeks=25, phases=[], upcoming_tasks=tasks,
    ))
    db.commit()
    materialize_coach_plan(db, user.id, TODAY)
    _login(client)
    assert _swap(client, MON, TUE).status_code == 200
    days = {d["date"]: d for d in
            client.get(f"/api/plan/week?start={MON.isoformat()}").json()["days"]}
    assert days[MON.isoformat()]["revertible"] is True
    assert days[TUE.isoformat()]["revertible"] is True


def test_reorder_requires_auth(client, db, user):
    assert _swap(client, MON, TUE).status_code in (401, 403)


# --- coach grounding: the rearrangement reaches the next daily review --------

class _StubReviewLLM:
    """Fixed structured result; records the prompt the review actually sent."""

    def __init__(self):
        self.seen: dict | None = None

    def complete_structured(self, system, messages, schema, name):
        self.seen = {"system": system, "messages": messages, "name": name}
        return {"coach_note": "Noted.", "should_propose": False}


def _editor_review(db, user_id, monkeypatch):
    """An editor-mode daily review with real health data and a stubbed LLM;
    returns the stub so tests can assert on the prompt it was sent."""
    import app.planner as planner_mod
    from app.models import DailyHealth, TrainingPlan

    db.add(TrainingPlan(
        user_id=user_id, garmin_plan_id=1, name="Plan",
        start_date=TODAY - dt.timedelta(days=10), end_date=TODAY + dt.timedelta(days=100),
        duration_weeks=25, phases=[], upcoming_tasks=[],
    ))
    db.add(DailyHealth(user_id=user_id, date=TODAY, sleep_score=80,
                       hrv=50, hrv_baseline=50))
    db.commit()
    stub = _StubReviewLLM()
    monkeypatch.setattr(planner_mod, "make_client", lambda provider=None, **_kw: stub)
    planner_mod.evaluate_today(db, user_id, TODAY)
    return stub


def test_reorder_reaches_next_daily_review_prompt(client, db, user, monkeypatch):
    """After a reorder, the next daily review's prompt carries the rearrangement
    — the deferred-feedback channel (no reactive chat message; the coach picks
    it up in the normal daily flow)."""
    _day(db, user.id, MON, "tempo", "Tempo 40")
    _day(db, user.id, TUE, "easy_run", "Easy 30")
    _login(client)
    assert _swap(client, MON, TUE).status_code == 200

    stub = _editor_review(db, user.id, monkeypatch)
    prompt = stub.seen["messages"][0]["content"]
    assert "recent_week_rearrangement" in prompt
    assert MON.isoformat() in prompt and TUE.isoformat() in prompt


def test_review_prompt_carries_no_rearrangement_without_reorder(db, user, monkeypatch):
    stub = _editor_review(db, user.id, monkeypatch)
    prompt = stub.seen["messages"][0]["content"]
    assert '"recent_week_rearrangement": null' in prompt
