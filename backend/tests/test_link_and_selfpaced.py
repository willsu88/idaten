"""ADR 0026: attribution, not scoring, links a run to its plan day.

A self-paced (zero-axis) day links and completes unscored; the stamped
attempted_prescription is the durable link; manual links (endpoint + chat
tool approval) run the full pipeline against the chosen day.
"""
from __future__ import annotations

import datetime as dt

from app import execution
from app.models import Activity, PendingEdit, PlanDay
from app.settings_store import put_garmin_hr_zones

TODAY = dt.date(2026, 7, 16)
ZONES = {"z1": [130, 144], "z2": [144, 161], "z3": [161, 173],
         "z4": [173, 192], "z5": [192, 212]}
SERIES_Z2 = {"t_s": [i * 30 for i in range(41)], "hr": [150] * 41}


def _run(db, user_id, aid, date, **kw):
    a = Activity(id=aid, user_id=user_id, date=date, type="running", name="run",
                 distance_m=10000, duration_s=1200, series=SERIES_Z2, **kw)
    db.add(a)
    db.commit()
    return a


def _self_paced_day(db, user_id, date, *, pushed=True, status="planned"):
    """A zero-axis day: distance only - no pace, no HR band, no steps."""
    day = PlanDay(user_id=user_id, date=date, workout_type="easy_run",
                  title="Self-paced 10K", distance_km=10.0, status=status,
                  garmin_workout_id="w1" if pushed else None)
    db.add(day)
    db.commit()
    return day


def _hr_day(db, user_id, date, *, status="planned", pushed=False):
    day = PlanDay(user_id=user_id, date=date, workout_type="easy_run",
                  title="Easy", duration_min=20, target_hr_low=144,
                  target_hr_high=161, status=status,
                  garmin_workout_id="w2" if pushed else None)
    db.add(day)
    db.commit()
    return day


def _login(client):
    assert client.post("/api/auth/login",
                       json={"username": "will", "password": "secret1"}).status_code == 200


# --- score_run: a zero-axis pushed day links unscored -----------------------

def test_zero_axis_pushed_day_attributes_without_score(db, user):
    day = _self_paced_day(db, user.id, TODAY)
    a = _run(db, user.id, 1, TODAY)
    res = execution.score_run(db, a, {}, ZONES)
    assert res.attributed
    assert res.score is None and res.source is None
    assert res.prescription["title"] == "Self-paced 10K"
    assert res.prescription["plan_date"] == day.date.isoformat()


def test_free_run_stays_unattributed(db, user):
    a = _run(db, user.id, 1, TODAY)  # no plan day at all
    res = execution.score_run(db, a, {}, ZONES)
    assert not res.attributed and res.prescription is None


def test_scoreable_pushed_day_still_scores(db, user):
    _hr_day(db, user.id, TODAY, pushed=True)
    a = _run(db, user.id, 1, TODAY)
    res = execution.score_run(db, a, {}, ZONES)
    assert res.attributed and res.score == 100 and res.source == "idaten"


def test_is_self_paced(db, user):
    assert execution.is_self_paced(_self_paced_day(db, user.id, TODAY))
    assert not execution.is_self_paced(_hr_day(db, user.id, TODAY + dt.timedelta(days=1)))


# --- attribution endpoint: Yes on a zero-axis day completes it --------------

def test_confirmed_yes_on_self_paced_day_links_and_completes(db, user, client):
    _login(client)
    put_garmin_hr_zones(db, user.id, ZONES, TODAY.isoformat())
    day = _self_paced_day(db, user.id, TODAY, pushed=False)
    a = _run(db, user.id, 1, TODAY)

    r = client.post(f"/api/activities/{a.id}/attribution", json={"attempted": True})
    assert r.status_code == 200 and r.json()["execution_score"] is None
    db.refresh(a)
    db.refresh(day)
    assert a.execution_attributed is True
    assert a.attempted_prescription["title"] == "Self-paced 10K"
    assert day.status == "completed"


def test_no_severs_the_link(db, user, client):
    _login(client)
    put_garmin_hr_zones(db, user.id, ZONES, TODAY.isoformat())
    _self_paced_day(db, user.id, TODAY, pushed=False)
    a = _run(db, user.id, 1, TODAY)
    client.post(f"/api/activities/{a.id}/attribution", json={"attempted": True})
    client.post(f"/api/activities/{a.id}/attribution", json={"attempted": False})
    db.refresh(a)
    assert a.attempted_prescription is None and a.execution_attributed is False


# --- prompt suppression: a linked-unscored run is never re-asked ------------

def test_no_prompt_for_linked_unscored_run(db, user):
    _self_paced_day(db, user.id, TODAY, pushed=False)
    a = _run(db, user.id, 1, TODAY,
             attempted_prescription={"source": "plan_day", "title": "Self-paced 10K"})
    assert execution.prompt_label(db, a) is None


# --- analysis gate: attribution, not score ----------------------------------

def test_analysis_rejects_unlinked_but_accepts_linked_unscored(db, user, client):
    _login(client)
    free = _run(db, user.id, 1, TODAY)
    r = client.post(f"/api/activities/{free.id}/analysis")
    assert r.status_code == 400 and "not linked" in r.json()["detail"]

    # Linked but unscored, and old: passes the link gate, hits the age guard -
    # proof the score is no longer what gates the analysis.
    linked = _run(db, user.id, 2, TODAY,
                  attempted_prescription={"source": "plan_day", "title": "X"})
    r = client.post(f"/api/activities/{linked.id}/analysis")
    assert r.status_code == 400 and "recent" in r.json()["detail"]


# --- manual link endpoint ----------------------------------------------------

def test_link_candidates_window_and_filters(db, user, client):
    _login(client)
    a = _run(db, user.id, 1, TODAY)
    _hr_day(db, user.id, TODAY - dt.timedelta(days=1))                      # in window
    _self_paced_day(db, user.id, TODAY + dt.timedelta(days=2))              # in window
    _hr_day(db, user.id, TODAY - dt.timedelta(days=2), status="completed")  # completed: out
    db.add(PlanDay(user_id=user.id, date=TODAY, workout_type="rest",
                   title="Rest day"))                                       # rest: out
    _hr_day(db, user.id, TODAY + dt.timedelta(days=4))                      # too far: out
    db.commit()
    r = client.get(f"/api/activities/{a.id}/link-candidates")
    assert r.status_code == 200
    dates = [c["date"] for c in r.json()["candidates"]]
    assert dates == [(TODAY - dt.timedelta(days=1)).isoformat(),
                     (TODAY + dt.timedelta(days=2)).isoformat()]


def test_cross_date_link_scores_and_completes_that_day(db, user, client):
    _login(client)
    put_garmin_hr_zones(db, user.id, ZONES, TODAY.isoformat())
    day = _hr_day(db, user.id, TODAY - dt.timedelta(days=1))
    a = _run(db, user.id, 1, TODAY, execution_attributed=False)  # prior "No"
    r = client.post(f"/api/activities/{a.id}/link",
                    json={"plan_date": day.date.isoformat()})
    assert r.status_code == 200 and r.json()["execution_score"] == 100
    db.refresh(a)
    db.refresh(day)
    assert day.status == "completed"           # the LINKED day, not the run's day
    assert a.execution_attributed is True      # the link overrides the "No"
    assert a.attempted_prescription["plan_date"] == day.date.isoformat()


def test_link_rejects_rest_completed_and_far_days(db, user, client):
    _login(client)
    a = _run(db, user.id, 1, TODAY)
    db.add(PlanDay(user_id=user.id, date=TODAY, workout_type="rest", title="Rest day"))
    _hr_day(db, user.id, TODAY + dt.timedelta(days=1), status="completed")
    _hr_day(db, user.id, TODAY + dt.timedelta(days=4))
    db.commit()
    for date in [TODAY, TODAY + dt.timedelta(days=1), TODAY + dt.timedelta(days=4),
                 TODAY + dt.timedelta(days=6)]:
        r = client.post(f"/api/activities/{a.id}/link",
                        json={"plan_date": date.isoformat()})
        assert r.status_code == 400


def test_link_is_tenant_scoped(db, user, client):
    from tests.conftest import make_user

    other = make_user(db, "other", "secret2")
    theirs = _run(db, other.id, 99, TODAY)
    _login(client)
    r = client.post(f"/api/activities/{theirs.id}/link",
                    json={"plan_date": TODAY.isoformat()})
    assert r.status_code == 404


# --- chat tool: link proposal through the approval queue --------------------

def test_link_tool_proposes_and_accept_applies(db, user, client):
    from app.chat.tools import dispatch
    import json as _json

    _login(client)
    put_garmin_hr_zones(db, user.id, ZONES, TODAY.isoformat())
    day = _self_paced_day(db, user.id, TODAY, pushed=False)
    a = _run(db, user.id, 1, TODAY)

    result, edit = dispatch(db, user.id, "link_activity",
                            {"activity_id": a.id, "plan_date": TODAY.isoformat()})
    payload = _json.loads(result)
    assert payload["status"] == "proposed" and edit is not None
    assert edit.link["self_paced"] is True
    assert "no score" in payload["note"]
    db.refresh(day)
    assert day.status == "planned"  # nothing changes before the approval

    r = client.post(f"/api/edits/{edit.id}/accept")
    assert r.status_code == 200
    db.refresh(day)
    db.refresh(a)
    assert day.status == "completed"
    assert a.attempted_prescription["title"] == "Self-paced 10K"
    assert a.execution_score is None  # self-paced: linked, nothing to grade


def test_link_tool_rejects_invalid_targets(db, user):
    from app.chat.tools import dispatch
    import json as _json

    a = _run(db, user.id, 1, TODAY)
    result, edit = dispatch(db, user.id, "link_activity",
                            {"activity_id": a.id, "plan_date": TODAY.isoformat()})
    assert edit is None and "error" in _json.loads(result)  # no plan day

    result, edit = dispatch(db, user.id, "link_activity",
                            {"activity_id": 12345, "plan_date": TODAY.isoformat()})
    assert edit is None and "error" in _json.loads(result)  # no such activity


def test_accept_revalidates_a_stale_link(db, user, client):
    from app.chat.tools import dispatch

    _login(client)
    day = _hr_day(db, user.id, TODAY)
    a = _run(db, user.id, 1, TODAY)
    _, edit = dispatch(db, user.id, "link_activity",
                       {"activity_id": a.id, "plan_date": TODAY.isoformat()})
    day.status = "completed"  # another run claimed the day since the proposal
    db.commit()
    r = client.post(f"/api/edits/{edit.id}/accept")
    assert r.status_code == 409


def test_get_run_execution_reports_link_state(db, user):
    from app.chat.tools import dispatch
    import json as _json

    _self_paced_day(db, user.id, TODAY, pushed=False, status="completed")
    _run(db, user.id, 1, TODAY,
         attempted_prescription={"source": "plan_day", "title": "Self-paced 10K"})
    _run(db, user.id, 2, TODAY - dt.timedelta(days=1))  # free run
    # TODAY is a fixed past date; widen the lookback so the query reaches it.
    result, edit = dispatch(db, user.id, "get_run_execution", {"days": 92})
    assert edit is None
    runs = _json.loads(result)["runs"]
    by_id = {r["activity_id"]: r for r in runs}
    assert by_id[1]["linked_to_plan"] is True
    assert by_id[1]["attempted_workout"] == "Self-paced 10K"
    assert by_id[1]["execution_score"] is None
    assert by_id[1]["plan_day"]["status"] == "completed"
    assert by_id[2]["linked_to_plan"] is False


# --- review findings: JSON-null sever + relink reverting the old day ---------

def test_sever_stores_sql_null_not_json_null(db, user, client):
    """A severed link must be invisible to SQL is_not(None) predicates - the
    Today query and the sibling checks all filter in SQL, and a JSON 'null'
    would keep matching them."""
    from sqlalchemy import select as sa_select

    _login(client)
    put_garmin_hr_zones(db, user.id, ZONES, TODAY.isoformat())
    _self_paced_day(db, user.id, TODAY, pushed=False)
    a = _run(db, user.id, 1, TODAY)
    client.post(f"/api/activities/{a.id}/attribution", json={"attempted": True})
    client.post(f"/api/activities/{a.id}/attribution", json={"attempted": False})
    linked = db.scalar(sa_select(Activity).where(
        Activity.id == a.id, Activity.attempted_prescription.is_not(None)))
    assert linked is None


def test_sever_reverts_the_completed_day(db, user, client):
    _login(client)
    put_garmin_hr_zones(db, user.id, ZONES, TODAY.isoformat())
    day = _self_paced_day(db, user.id, TODAY, pushed=False)
    a = _run(db, user.id, 1, TODAY)
    client.post(f"/api/activities/{a.id}/attribution", json={"attempted": True})
    db.refresh(day)
    assert day.status == "completed"
    client.post(f"/api/activities/{a.id}/attribution", json={"attempted": False})
    db.refresh(day)
    assert day.status == "planned"


def test_relink_reverts_the_previously_linked_day(db, user, client):
    """Moving a run's link to another day must not leave the old day completed
    forever with no run attached (and self-locked against relinking)."""
    _login(client)
    put_garmin_hr_zones(db, user.id, ZONES, TODAY.isoformat())
    day_a = _self_paced_day(db, user.id, TODAY, pushed=False)
    day_b = _hr_day(db, user.id, TODAY - dt.timedelta(days=1))
    a = _run(db, user.id, 1, TODAY)
    client.post(f"/api/activities/{a.id}/attribution", json={"attempted": True})
    db.refresh(day_a)
    assert day_a.status == "completed"

    r = client.post(f"/api/activities/{a.id}/link",
                    json={"plan_date": day_b.date.isoformat()})
    assert r.status_code == 200
    db.refresh(day_a)
    db.refresh(day_b)
    assert day_b.status == "completed"
    assert day_a.status == "planned"  # freed for the run that actually did it
