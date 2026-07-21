from __future__ import annotations

import datetime as dt
import json

from app.chat.tools import TOOL_SCHEMAS, dispatch
from app.models import Activity, DayIntent, PendingEdit, PlanDay

TODAY = dt.date.today()


def _call(db, name, args, user_id=1):
    result, edit = dispatch(db, user_id, name, args)
    return json.loads(result), edit


def test_schema_names_match_dispatch():
    names = {t["function"]["name"] for t in TOOL_SCHEMAS}
    assert names == {
        "get_training_data", "get_current_plan", "get_plan_history",
        "set_day_intent", "clear_day_intent", "propose_plan_edit",
        "log_niggle", "resolve_niggle",
    }


def test_unknown_tool(db):
    result, edit = _call(db, "drop_all_tables", {})
    assert "error" in result and edit is None


def test_get_training_data_caps_range(db):
    start = TODAY - dt.timedelta(days=400)
    old = Activity(id=1, user_id=1, date=start + dt.timedelta(days=1), type="running",
                   distance_m=5000, duration_s=1800)
    recent = Activity(id=2, user_id=1, date=TODAY - dt.timedelta(days=5), type="running",
                      distance_m=5000, duration_s=1800)
    db.add_all([old, recent])
    db.commit()
    result, _ = _call(db, "get_training_data",
                      {"start_date": start.isoformat(), "end_date": TODAY.isoformat()})
    dates = [a["date"] for a in result["activities"]]
    # The 400-day-old activity is outside the 92-day cap
    assert recent.date.isoformat() in dates
    assert old.date.isoformat() not in dates
    assert len(result["load_metrics"]) <= 93


def test_set_and_clear_day_intent(db):
    d = (TODAY + dt.timedelta(days=2)).isoformat()
    result, _ = _call(db, "set_day_intent",
                      {"date": d, "sport": "surfing", "duration_min": 90, "effort": "hard"})
    assert result["status"] == "set"
    row = db.get(DayIntent, (1, dt.date.fromisoformat(d)))
    assert row is not None and row.sport == "surfing" and row.source == "chat"

    result, _ = _call(db, "clear_day_intent", {"date": d})
    assert result["status"] == "cleared"
    assert db.get(DayIntent, (1, dt.date.fromisoformat(d))) is None


def test_set_day_intent_invalid_date(db):
    result, _ = _call(db, "set_day_intent", {"date": "not-a-date", "sport": "surfing"})
    assert "error" in result


def test_propose_plan_edit_creates_pending(db):
    db.add(PlanDay(user_id=1, date=TODAY, workout_type="tempo", title="Tempo"))
    db.commit()
    days = [{
        "date": TODAY.isoformat(), "workout_type": "easy_run", "title": "Easy run",
        "description": "swap", "rationale": "tired",
    }]
    result, edit = _call(db, "propose_plan_edit",
                         {"summary": "ease off", "rationale": "low HRV", "days": days})
    assert result["status"] == "proposed"
    assert edit is not None and edit.status == "pending"
    # Current (pre-edit) state captured for the diff
    assert edit.current[0]["workout_type"] == "tempo"
    # Nothing applied yet
    assert db.get(PlanDay, (1, TODAY)).workout_type == "tempo"


def test_new_proposal_supersedes_pending(db):
    days = [{
        "date": TODAY.isoformat(), "workout_type": "rest", "title": "Rest",
        "description": "", "rationale": "r",
    }]
    _, first = _call(db, "propose_plan_edit", {"summary": "one", "rationale": "r", "days": days})
    _, second = _call(db, "propose_plan_edit", {"summary": "two", "rationale": "r", "days": days})
    assert db.get(PendingEdit, first.id).status == "superseded"
    assert db.get(PendingEdit, second.id).status == "pending"


def test_propose_plan_edit_rejects_empty_and_bad_dates(db):
    result, edit = _call(db, "propose_plan_edit", {"summary": "s", "rationale": "r", "days": []})
    assert "error" in result and edit is None
    result, edit = _call(db, "propose_plan_edit", {
        "summary": "s", "rationale": "r",
        "days": [{"date": "bogus", "workout_type": "rest", "title": "t",
                  "description": "", "rationale": "r"}],
    })
    assert "error" in result and edit is None


def test_get_current_plan_scoped_to_future(db):
    db.add(PlanDay(user_id=1, date=TODAY - dt.timedelta(days=1), workout_type="tempo", title="Yesterday"))
    db.add(PlanDay(user_id=1, date=TODAY, workout_type="easy_run", title="Today"))
    db.commit()
    result, _ = _call(db, "get_current_plan", {})
    titles = [d["title"] for d in result["days"]]
    assert "Today" in titles and "Yesterday" not in titles
