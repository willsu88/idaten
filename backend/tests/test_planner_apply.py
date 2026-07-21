from __future__ import annotations

import datetime as dt

from app.models import DayIntent, PlanDay, PlanVersion
from app.planner import apply_plan_days

TODAY = dt.date.today()


def _day_dict(date, **kw):
    d = {
        "date": date.isoformat(),
        "workout_type": "easy_run",
        "title": "Easy run",
        "description": "40 min conversational",
        "duration_min": 40,
        "distance_km": None,
        "target_pace": "6:00",
        "rationale": "test",
    }
    d.update(kw)
    return d


def test_apply_creates_days_and_version(db):
    changed = apply_plan_days(db, 1, [_day_dict(TODAY), _day_dict(TODAY + dt.timedelta(days=1))],
                              source="daily_job", summary="initial")
    assert len(changed) == 2
    assert db.get(PlanDay, (1, TODAY)).workout_type == "easy_run"
    versions = db.query(PlanVersion).all()
    assert len(versions) == 1 and versions[0].source == "daily_job"


def test_unchanged_day_not_marked_changed(db):
    apply_plan_days(db, 1, [_day_dict(TODAY)], source="daily_job", summary="a")
    changed = apply_plan_days(db, 1, [_day_dict(TODAY)], source="daily_job", summary="b")
    assert changed == []


def test_material_change_clears_pushed_at(db):
    apply_plan_days(db, 1, [_day_dict(TODAY)], source="daily_job", summary="a")
    day = db.get(PlanDay, (1, TODAY))
    day.garmin_workout_id = "w123"
    day.pushed_at = dt.datetime.now(dt.timezone.utc)
    db.commit()

    changed = apply_plan_days(db, 1, [_day_dict(TODAY, workout_type="tempo", title="Tempo")],
                              source="chat_edit", summary="swap")
    assert len(changed) == 1
    day = db.get(PlanDay, (1, TODAY))
    assert day.pushed_at is None            # stale on the watch
    assert day.garmin_workout_id == "w123"  # kept, so re-push replaces it


def test_rationale_only_change_keeps_push_current(db):
    apply_plan_days(db, 1, [_day_dict(TODAY)], source="daily_job", summary="a")
    day = db.get(PlanDay, (1, TODAY))
    pushed = dt.datetime.now(dt.timezone.utc)
    day.pushed_at = pushed
    db.commit()

    changed = apply_plan_days(db, 1, [_day_dict(TODAY, rationale="new words, same workout")],
                              source="daily_job", summary="b")
    assert changed == []
    assert db.get(PlanDay, (1, TODAY)).pushed_at is not None


def test_never_overwrites_completed_day(db):
    apply_plan_days(db, 1, [_day_dict(TODAY)], source="daily_job", summary="a")
    day = db.get(PlanDay, (1, TODAY))
    day.status = "completed"
    db.commit()

    apply_plan_days(db, 1, [_day_dict(TODAY, workout_type="intervals", title="Intervals")],
                    source="daily_job", summary="b")
    day = db.get(PlanDay, (1, TODAY))
    assert day.workout_type == "easy_run"
    assert day.status == "completed"


def test_intent_day_coerced_to_cross_train(db):
    db.add(DayIntent(user_id=1, date=TODAY, sport="surfing", note="dawn patrol",
                     duration_min=90, effort="moderate"))
    db.commit()

    apply_plan_days(db, 1, [_day_dict(TODAY, workout_type="long_run", title="Long run")],
                    source="daily_job", summary="model ignored the intent")
    day = db.get(PlanDay, (1, TODAY))
    assert day.workout_type == "cross_train"
    assert day.title == "Surfing"
    assert day.target_pace is None
    assert day.distance_km is None


def test_intent_day_allows_rest(db):
    db.add(DayIntent(user_id=1, date=TODAY, sport="hiking"))
    db.commit()
    apply_plan_days(db, 1, [_day_dict(TODAY, workout_type="rest", title="Rest",
                                   duration_min=None, target_pace=None)],
                    source="daily_job", summary="rest is fine on intent days")
    assert db.get(PlanDay, (1, TODAY)).workout_type == "rest"
