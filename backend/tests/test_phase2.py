"""Phase 2: athlete profile from Garmin, training modes, activity series/splits,
and one-way Garmin race import."""

from __future__ import annotations

import datetime as dt

from app import metrics, settings_store
from app.garmin.profile import parse_user_data, sync_profile
from app.garmin.races_import import _distance_km, sync_races
from app.garmin.series import fetch_and_cache, parse_route, parse_series, parse_splits
from app.models import Activity, PlanDay, Race
from app.planner import PLAN_SCHEMA, _athlete_block, apply_plan_days, build_snapshot
from app.settings_store import get_settings, put_settings

from conftest import make_user

TODAY = dt.date.today()

USER_DATA = {
    "gender": "MALE",
    "weight": 67000.0,
    "height": 170.0,
    "birthDate": "1998-10-29",
    "vo2MaxRunning": 52.0,
    "lactateThresholdHeartRate": 186,
}


class StubGarmin:
    """Only the methods each test exercises; everything else raises."""

    def __init__(self, **payloads):
        self._payloads = payloads

    def get_user_profile(self):
        return {"userData": self._payloads["user_data"]}

    def connectapi(self, path):
        return self._payloads["calendar"].get(path, {"calendarItems": []})

    def get_activity_details(self, activity_id, maxchart=300, maxpoly=500):
        return self._payloads["details"]

    def get_activity_splits(self, activity_id):
        return self._payloads["splits"]


# --- 5b: athlete profile -------------------------------------------------------

def test_parse_user_data_units_and_case():
    p = parse_user_data(USER_DATA)
    assert p["gender"] == "male"
    assert p["weight_kg"] == 67.0
    assert p["height_cm"] == 170.0
    assert p["lthr"] == 186
    assert p["vo2max_running"] == 52.0
    assert p["birth_date"] == "1998-10-29"


def test_sync_profile_and_athlete_auto(db, user):
    sync_profile(db, user.id, StubGarmin(user_data=USER_DATA))
    auto = settings_store.athlete_auto(db, user.id)
    born = dt.date(1998, 10, 29)
    expected_age = TODAY.year - born.year - ((TODAY.month, TODAY.day) < (born.month, born.day))
    assert auto["age"] == expected_age
    assert auto["lthr"] == 186
    # Internal key is invisible to the settings API surface
    assert "garmin_profile" not in get_settings(db, user.id)
    assert "garmin_profile" not in put_settings(db, user.id, {"garmin_profile": {"lthr": 1}})


def test_athlete_block_prefers_auto_over_manual(db, user):
    put_settings(db, user.id, {"athlete": {"age": 99, "weekly_km": 5, "notes": "hi"}})
    sync_profile(db, user.id, StubGarmin(user_data=USER_DATA))
    block = _athlete_block(db, user.id, get_settings(db, user.id))
    assert block["age"] != 99          # Garmin birthDate wins
    assert block["lactate_threshold_hr"] == 186
    assert block["notes"] == "hi"      # manual notes survive


def test_hr_zones_from_lthr():
    zones = metrics.hr_zones_from_lthr(186)
    assert zones["z2"] == [158, 166]
    assert zones["z5"] == [186, 197]
    assert metrics.hr_zones_from_lthr(None) is None


def test_snapshot_has_mode_and_zones(db, user):
    sync_profile(db, user.id, StubGarmin(user_data=USER_DATA))
    snap = build_snapshot(db, user.id, TODAY)
    assert snap["training_mode"] == "hybrid"
    assert snap["hr_zones"]["z1"][1] == round(186 * 0.85)
    assert snap["athlete"]["weight_kg"] == 67.0


# --- 6: training modes ---------------------------------------------------------

def test_training_mode_validation(db, user):
    assert get_settings(db, user.id)["training_mode"] == "hybrid"
    assert put_settings(db, user.id, {"training_mode": "hr"})["training_mode"] == "hr"
    assert put_settings(db, user.id, {"training_mode": "bogus"})["training_mode"] == "hr"


def test_plan_schema_requires_hr_targets():
    day_schema = PLAN_SCHEMA["properties"]["days"]["items"]
    assert "target_hr_low" in day_schema["properties"]
    assert "target_hr_low" in day_schema["required"]


def test_apply_plan_days_stores_hr_targets_and_marks_stale(db, user):
    day = {
        "date": TODAY.isoformat(), "workout_type": "easy_run", "title": "Easy",
        "description": "", "duration_min": 40, "distance_km": None,
        "target_pace": None, "target_hr_low": 140, "target_hr_high": 155,
        "rationale": "test",
    }
    apply_plan_days(db, user.id, [day], source="test", summary="")
    row = db.get(PlanDay, (user.id, TODAY))
    assert (row.target_hr_low, row.target_hr_high) == (140, 155)
    row.pushed_at = dt.datetime.now(dt.timezone.utc)
    db.commit()
    # Changing only the HR band is a material change -> needs re-push
    changed = apply_plan_days(db, user.id, [{**day, "target_hr_high": 150}],
                              source="test", summary="")
    assert len(changed) == 1 and changed[0].pushed_at is None


def test_push_payload_hr_band(db, user):
    from app.garmin.push import _workout_payload

    day = PlanDay(user_id=user.id, date=TODAY, workout_type="easy_run", title="Easy",
                  duration_min=40, target_hr_low=140, target_hr_high=155)
    step = _workout_payload(day)["workoutSegments"][0]["workoutSteps"][0]
    assert step["targetType"]["workoutTargetTypeKey"] == "heart.rate.zone"
    assert (step["targetValueOne"], step["targetValueTwo"]) == (140.0, 155.0)
    # Pace wins when both are present (planner should never set both)
    day.target_pace = "5:30"
    step = _workout_payload(day)["workoutSegments"][0]["workoutSteps"][0]
    assert step["targetType"]["workoutTargetTypeKey"] == "pace.zone"


def test_edit_tool_schema_has_hr_fields():
    from app.chat.tools import TOOL_SCHEMAS

    propose = next(t for t in TOOL_SCHEMAS if t["function"]["name"] == "propose_plan_edit")
    props = propose["function"]["parameters"]["properties"]["days"]["items"]["properties"]
    assert "target_hr_low" in props and "target_hr_high" in props


# --- 7: series / splits / type filter ------------------------------------------

DETAILS = {
    "metricDescriptors": [
        {"key": "sumDuration", "metricsIndex": 0},
        {"key": "directHeartRate", "metricsIndex": 1},
        {"key": "directSpeed", "metricsIndex": 2},
        {"key": "directElevation", "metricsIndex": 3},
        {"key": "directDoubleCadence", "metricsIndex": 4},
        {"key": "sumDistance", "metricsIndex": 5},
    ],
    "activityDetailMetrics": [
        {"metrics": [float(t), 120 + t, 3.0, 12.0, 170.0, t * 3.0]} for t in range(10)
    ],
}

SPLITS = {"lapDTOs": [
    {"lapIndex": 1, "distance": 1000.0, "movingDuration": 330.0, "averageHR": 148,
     "maxHR": 155, "averageMovingSpeed": 3.03, "elevationGain": 4.0,
     "averageRunCadence": 172.0, "intensityType": "INTERVAL", "wktStepIndex": 2},
]}


def test_parse_series_columnar():
    s = parse_series(DETAILS)
    assert len(s["t_s"]) == 10
    assert s["hr"][0] == 120 and s["hr"][9] == 129
    assert s["distance_m"][9] == 27.0
    assert parse_series({"metricDescriptors": [], "activityDetailMetrics": []}) is None


def test_parse_splits():
    s = parse_splits(SPLITS)
    assert s[0]["distance_m"] == 1000.0 and s[0]["avg_hr"] == 148
    assert s[0]["intensity"] == "INTERVAL" and s[0]["step_index"] == 2
    assert parse_splits({"lapDTOs": []}) is None


ROUTE_DETAILS = {**DETAILS, "geoPolylineDTO": {"polyline": [
    {"lat": 24.980843, "lon": 121.524870},
    {"lat": 24.981102, "lon": 121.525311},
    {"lat": None, "lon": 121.526},  # GPS dropout — skipped
]}}
ROUTE = [[24.980843, 121.52487], [24.981102, 121.525311]]


def test_parse_route():
    assert parse_route(ROUTE_DETAILS) == ROUTE
    assert parse_route(DETAILS) == []  # no geoPolylineDTO = confirmed no GPS


def test_fetch_and_cache_backfills_route_for_gps_activity(db, user):
    a = _add_activity(db, user.id, 5, series=parse_series(DETAILS), splits=parse_splits(SPLITS))
    a.start_lat = 24.98
    db.commit()
    fetch_and_cache(db, StubGarmin(details=ROUTE_DETAILS, splits=SPLITS), a)
    assert a.route == ROUTE
    assert a.series["hr"][0] == 120  # cached series untouched


def test_fetch_and_cache_settles_indoor_route_without_garmin(db, user):
    a = _add_activity(db, user.id, 6, series=parse_series(DETAILS), splits=parse_splits(SPLITS))
    fetch_and_cache(db, None, a)  # start_lat None: any Garmin touch would raise
    assert a.route == []


def _add_activity(db, user_id, aid, type_="running", series=None, splits=None, date=TODAY):
    a = Activity(id=aid, user_id=user_id, date=date, type=type_, name=f"a{aid}",
                 distance_m=5000, duration_s=1500, series=series, splits=splits)
    db.add(a)
    db.commit()
    return a


def _login(client, username="will", password="secret1"):
    assert client.post("/api/auth/login",
                       json={"username": username, "password": password}).status_code == 200


def test_activities_type_filter_and_types(db, user, client):
    _add_activity(db, user.id, 1, "running")
    _add_activity(db, user.id, 2, "running")
    _add_activity(db, user.id, 3, "lap_swimming")
    _login(client)
    assert len(client.get("/api/activities?type=running").json()) == 2
    types = client.get("/api/activities/types").json()
    assert types[0] == {"type": "running", "count": 2}
    assert {"type": "lap_swimming", "count": 1} in types


def test_activities_days_filter(db, user, client):
    _add_activity(db, user.id, 1, date=TODAY)
    _add_activity(db, user.id, 2, date=TODAY - dt.timedelta(days=45))
    _add_activity(db, user.id, 3, date=TODAY - dt.timedelta(days=200))
    _login(client)
    assert len(client.get("/api/activities").json()) == 3
    assert len(client.get("/api/activities?days=30").json()) == 1
    assert len(client.get("/api/activities?days=90").json()) == 2
    assert len(client.get("/api/activities?days=365").json()) == 3


def test_series_endpoint_serves_cache_without_garmin(db, user, client):
    _add_activity(db, user.id, 1, series=parse_series(DETAILS), splits=parse_splits(SPLITS))
    sync_profile(db, user.id, StubGarmin(user_data=USER_DATA))
    _login(client)
    body = client.get("/api/activities/1/series").json()
    assert body["series"]["hr"][0] == 120
    assert body["splits"][0]["avg_pace"] == "5:30"
    assert body["hr_zones"]["z5"][0] == 186


def test_series_endpoint_returns_cached_route(db, user, client):
    a = _add_activity(db, user.id, 2, series=parse_series(DETAILS), splits=parse_splits(SPLITS))
    a.route = ROUTE
    db.commit()
    _login(client)
    assert client.get("/api/activities/2/series").json()["route"] == ROUTE


def test_series_endpoint_is_tenant_scoped(db, user, client):
    other = make_user(db, "gf", "secret2")
    _add_activity(db, other.id, 99, series=parse_series(DETAILS))
    _login(client)
    assert client.get("/api/activities/99/series").status_code == 404


# --- 8: Garmin race import -------------------------------------------------------

def _race_item(name, date, km=21.13, primary=False, uuid="uuid-1"):
    return {
        "itemType": "event", "isRace": True, "title": name, "date": date,
        "shareableEventUuid": uuid, "primaryEvent": primary,
        "completionTarget": {"value": km, "unit": "kilometer", "unitType": "distance"},
    }


def _calendar_garmin(items):
    """StubGarmin whose every calendar month returns the same items."""
    g = StubGarmin(calendar={})

    def connectapi(path):
        return {"calendarItems": items}

    g.connectapi = connectapi
    return g


def test_distance_units():
    assert _distance_km(_race_item("x", "2026-01-01", km=13.1) |
                        {"completionTarget": {"value": 13.1, "unit": "mile",
                                              "unitType": "distance"}}) == 21.08
    assert _distance_km({"completionTarget": None}) is None


def test_race_import_creates_and_dedupes(db, user):
    future = (TODAY + dt.timedelta(days=60)).isoformat()
    g = _calendar_garmin([_race_item("Big Race", future, primary=True)])
    assert sync_races(db, user.id, g) == 1
    race = db.query(Race).filter_by(user_id=user.id).one()
    assert (race.source, race.distance_km, race.is_primary) == ("garmin", 21.13, True)
    # Second sync: no duplicate, and app-side edits win
    race.distance_km = 21.5
    db.commit()
    assert sync_races(db, user.id, g) == 0
    assert db.query(Race).filter_by(user_id=user.id).one().distance_km == 21.5


def test_race_import_adopts_manual_duplicate(db, user):
    future = TODAY + dt.timedelta(days=60)
    db.add(Race(user_id=user.id, name="Big Race", date=future, distance_km=21.1,
                is_primary=True))
    db.commit()
    g = _calendar_garmin([_race_item("Big Race", future.isoformat())])
    assert sync_races(db, user.id, g) == 0
    race = db.query(Race).filter_by(user_id=user.id).one()
    assert race.garmin_uuid == "uuid-1" and race.distance_km == 21.1


def test_race_import_respects_manual_primary_and_tombstones(db, user):
    future = (TODAY + dt.timedelta(days=60)).isoformat()
    manual = Race(user_id=user.id, name="My pick", date=TODAY + dt.timedelta(days=30),
                  distance_km=10.0, is_primary=True)
    db.add(manual)
    db.commit()
    settings_store.put_internal(db, user.id, settings_store.RACE_PRIMARY_OVERRIDE_KEY, True)
    g = _calendar_garmin([_race_item("Garmin Race", future, primary=True)])
    sync_races(db, user.id, g)
    assert db.get(Race, manual.id).is_primary          # override respected
    # Tombstoned races never come back
    imported = db.query(Race).filter_by(garmin_uuid="uuid-1").one()
    settings_store.put_internal(db, user.id, settings_store.DELETED_GARMIN_RACES_KEY,
                                ["uuid-1"])
    db.delete(imported)
    db.commit()
    assert sync_races(db, user.id, g) == 0
    assert db.query(Race).filter_by(garmin_uuid="uuid-1").count() == 0


def test_race_import_skips_past_and_distanceless(db, user):
    past = (TODAY - dt.timedelta(days=10)).isoformat()
    future = (TODAY + dt.timedelta(days=10)).isoformat()
    no_dist = _race_item("No dist", future, uuid="uuid-2") | {"completionTarget": None}
    g = _calendar_garmin([_race_item("Past", past), no_dist])
    assert sync_races(db, user.id, g) == 0


def test_delete_imported_race_tombstones_via_api(db, user, client):
    future = TODAY + dt.timedelta(days=60)
    race = Race(user_id=user.id, name="R", date=future, distance_km=10.0,
                source="garmin", garmin_uuid="uuid-9")
    db.add(race)
    db.commit()
    _login(client)
    assert client.delete(f"/api/races/{race.id}").json() == {"ok": True}
    assert settings_store.get_internal(
        db, user.id, settings_store.DELETED_GARMIN_RACES_KEY) == ["uuid-9"]


def test_settings_includes_athlete_auto(db, user, client):
    sync_profile(db, user.id, StubGarmin(user_data=USER_DATA))
    _login(client)
    body = client.get("/api/settings").json()
    assert body["athlete_auto"]["lthr"] == 186
    assert body["training_mode"] == "hybrid"
    # PUT ignores athlete_auto entirely — and returns the same shape as GET
    # (a bare-settings PUT response once crashed the settings page)
    put = client.put("/api/settings", json={**body, "athlete_auto": {"lthr": 1}})
    assert put.status_code == 200
    assert put.json()["athlete_auto"]["lthr"] == 186
    assert client.get("/api/settings").json()["athlete_auto"]["lthr"] == 186
