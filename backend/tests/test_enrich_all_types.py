"""RPE/feel/body-battery import covers ALL activity types; the heavier run-only
metrics (zones, HR drift, splits, weather) stay gated to runs."""

from __future__ import annotations

import datetime as dt

from app.garmin.enrich import enrich_pending
from app.models import Activity

TODAY = dt.date(2026, 7, 17)


class FakeGarmin:
    """Records which per-activity endpoints get called, per activity id."""

    def __init__(self):
        self.run_calls: list[int] = []

    def get_activity(self, aid):
        return {"summaryDTO": {"directWorkoutRpe": 40, "directWorkoutFeel": 75}}

    def get_activity_hr_in_timezones(self, aid):
        self.run_calls.append(aid)
        return []

    def get_activity_details(self, aid, maxchart=None, maxpoly=None):
        self.run_calls.append(aid)
        return {"activityDetailMetrics": [], "metricDescriptors": []}

    def get_activity_splits(self, aid):
        self.run_calls.append(aid)
        return {}

    def get_activity_weather(self, aid):
        self.run_calls.append(aid)
        return {}


def _act(db, user_id, aid, atype, bb=None):
    db.add(Activity(id=aid, user_id=user_id, date=TODAY, type=atype,
                    name=atype, enriched=False,
                    raw={"differenceBodyBattery": bb} if bb is not None else {}))
    db.commit()


def test_rpe_feel_imported_for_run_and_walk(db, user):
    _act(db, user.id, 1, "running", bb=-6)
    _act(db, user.id, 2, "walking", bb=-3)
    g = FakeGarmin()

    enrich_pending(db, user.id, g, throttle_s=0)

    run = db.get(Activity, 1)
    walk = db.get(Activity, 2)
    # Both get effort/feel/body-battery.
    assert run.garmin_rpe == 4 and run.feel == 4 and run.body_battery_change == -6
    assert walk.garmin_rpe == 4 and walk.feel == 4 and walk.body_battery_change == -3
    # Both are marked processed so they aren't re-fetched every sync.
    assert run.enriched and walk.enriched


def test_run_only_metrics_skipped_for_non_run(db, user):
    _act(db, user.id, 1, "running")
    _act(db, user.id, 2, "walking")
    g = FakeGarmin()

    enrich_pending(db, user.id, g, throttle_s=0)

    # The run triggers zones/details/splits/weather; the walk triggers none.
    assert 1 in g.run_calls
    assert 2 not in g.run_calls
