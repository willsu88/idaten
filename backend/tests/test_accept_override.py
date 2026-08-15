"""Accepting a plan edit overrides a day intent (the approval is the authority).

Regression for the silent-coercion bug: an accepted run on an intent-reserved
day was rewritten back to cross_train by apply_plan_days' guard while the
accept still reported success, so the athlete's approved run never existed and
nothing could be pushed to the watch. The guard stays for model-driven sources
(covered in test_planner_apply.py); a user-approved edit now clears the intent.
"""
from __future__ import annotations

import datetime as dt
import json

from app.chat.tools import dispatch
from app.models import DayIntent, PendingEdit, PlanDay
from tests.conftest import make_user

TODAY = dt.date.today()


def _login(client, db):
    from app.auth import create_session

    u = make_user(db)
    client.cookies.set("gb_session", create_session(db, u))
    return u


def _run_day(date, **kw):
    d = {
        "date": date.isoformat(), "workout_type": "easy_run",
        "title": "20-minute easy run", "description": "20 min easy",
        "duration_min": 20, "rationale": "asked for a short run",
    }
    d.update(kw)
    return d


def test_accept_clears_intent_and_applies_run(client, db):
    u = _login(client, db)
    db.add(DayIntent(user_id=u.id, date=TODAY, sport="strength training",
                     note="short strength session", source="chat"))
    edit = PendingEdit(user_id=u.id, summary="add run", rationale="r",
                       changes=[_run_day(TODAY)], current=[])
    db.add(edit)
    db.commit()

    assert client.post(f"/api/edits/{edit.id}/accept").status_code == 200
    day = db.get(PlanDay, (u.id, TODAY))
    assert day.workout_type == "easy_run"
    assert day.title == "20-minute easy run"
    assert db.get(DayIntent, (u.id, TODAY)) is None


def test_accept_without_run_keeps_intent(client, db):
    u = _login(client, db)
    db.add(DayIntent(user_id=u.id, date=TODAY, sport="freediving",
                     note="no run", source="chat"))
    edit = PendingEdit(user_id=u.id, summary="rest instead", rationale="r",
                       changes=[_run_day(TODAY, workout_type="rest", title="Rest",
                                         duration_min=None)],
                       current=[])
    db.add(edit)
    db.commit()

    assert client.post(f"/api/edits/{edit.id}/accept").status_code == 200
    assert db.get(PlanDay, (u.id, TODAY)).workout_type == "rest"
    assert db.get(DayIntent, (u.id, TODAY)) is not None


def test_accept_only_clears_intents_on_run_days(client, db):
    u = _login(client, db)
    other = TODAY + dt.timedelta(days=2)
    db.add(DayIntent(user_id=u.id, date=TODAY, sport="strength training"))
    db.add(DayIntent(user_id=u.id, date=other, sport="surfing"))
    edit = PendingEdit(user_id=u.id, summary="add run today", rationale="r",
                       changes=[_run_day(TODAY)], current=[])
    db.add(edit)
    db.commit()

    assert client.post(f"/api/edits/{edit.id}/accept").status_code == 200
    assert db.get(DayIntent, (u.id, TODAY)) is None
    assert db.get(DayIntent, (u.id, other)) is not None


def test_propose_warns_about_reserved_days(db):
    db.add(DayIntent(user_id=1, date=TODAY, sport="strength training"))
    db.commit()
    result, edit = dispatch(db, 1, "propose_plan_edit", {
        "summary": "add run", "rationale": "r", "days": [_run_day(TODAY)]})
    result = json.loads(result)
    assert result["status"] == "proposed" and edit is not None
    assert result["reserved_day_conflicts"] == [
        {"date": TODAY.isoformat(), "sport": "strength training"}]
    assert "reserved" in result["note"]


def test_propose_no_warning_without_intent(db):
    result, edit = dispatch(db, 1, "propose_plan_edit", {
        "summary": "add run", "rationale": "r", "days": [_run_day(TODAY)]})
    result = json.loads(result)
    assert result["status"] == "proposed"
    assert "reserved_day_conflicts" not in result
