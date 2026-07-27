"""HR target bands are always real ranges (ADR 0017).

Layers 1-2: the widening rule as a pure function, and every enforcement point -
mirror write, proposal clamp, check_week warnings, generation retry, and the
execution-scoring guard.
"""

from __future__ import annotations

from app import metrics

# Generic zone table for tests (not any real athlete's values).
ZONES = {
    "z1": [110, 130],
    "z2": [130, 145],
    "z3": [145, 160],
    "z4": [160, 172],
    "z5": [172, 190],
}


def test_widen_resolves_containing_zone():
    assert metrics.widen_hr_target(140, ZONES) == [130, 145]  # inside z2
    assert metrics.widen_hr_target(165, ZONES, quality=True) == [160, 172]  # inside z4


def test_widen_boundary_lower_zone_wins_for_easy():
    # 145 is z2 high AND z3 low; an easy prescription means the lower zone.
    assert metrics.widen_hr_target(145, ZONES) == [130, 145]


def test_widen_boundary_higher_zone_wins_for_quality():
    # 160 is z3 high AND z4 low; a quality prescription means the higher zone.
    assert metrics.widen_hr_target(160, ZONES, quality=True) == [160, 172]


def test_widen_without_zones_falls_back_to_fixed_halfwidth():
    assert metrics.widen_hr_target(150, None) == [143, 157]


def test_widen_outside_all_zones_falls_back_not_snaps():
    assert metrics.widen_hr_target(100, ZONES) == [93, 107]
    assert metrics.widen_hr_target(200, ZONES, quality=True) == [193, 207]


def test_ensure_band_keeps_real_bands():
    assert metrics.ensure_hr_band(130, 145, ZONES) == (130, 145)
    assert metrics.ensure_hr_band(150, 155, ZONES) == (150, 155)  # width 5 is legal


def test_ensure_band_widens_degenerate_band_around_midpoint():
    # 152-152 -> midpoint 152 sits in z3 -> the zone band.
    assert metrics.ensure_hr_band(152, 152, ZONES) == (145, 160)
    # width 4 is still degenerate.
    assert metrics.ensure_hr_band(150, 154, ZONES) == (145, 160)


def test_ensure_band_passes_through_missing_targets():
    assert metrics.ensure_hr_band(None, None, ZONES) == (None, None)
    assert metrics.ensure_hr_band(150, None, ZONES) == (150, None)


# --- mirror write: a single coach bpm becomes the athlete's zone band --------


def _cache_zones(db, user_id):
    from app.settings_store import put_garmin_hr_zones

    put_garmin_hr_zones(db, user_id, ZONES, "2026-01-01")
    db.commit()


def test_coach_day_widens_single_hr_to_zone_band(db, user):
    import datetime as dt

    from app.planner import _coach_day_fields

    _cache_zones(db, user.id)
    fields = _coach_day_fields(db, user.id, dt.date.today(),
                               {"name": "Base", "description": "30:00@140bpm"})
    assert (fields["target_hr_low"], fields["target_hr_high"]) == (130, 145)


def test_coach_day_quality_boundary_takes_higher_zone(db, user):
    import datetime as dt

    from app.planner import _coach_day_fields

    _cache_zones(db, user.id)
    fields = _coach_day_fields(db, user.id, dt.date.today(),
                               {"name": "Threshold", "training_effect": "TEMPO",
                                "description": "18:00@160bpm"})
    assert (fields["target_hr_low"], fields["target_hr_high"]) == (160, 172)


def test_coach_day_without_zones_gets_fallback_band(db, user):
    import datetime as dt

    from app.planner import _coach_day_fields

    fields = _coach_day_fields(db, user.id, dt.date.today(),
                               {"name": "Base", "description": "30:00@140bpm"})
    assert (fields["target_hr_low"], fields["target_hr_high"]) == (133, 147)


def test_coach_day_without_hr_stays_null(db, user):
    import datetime as dt

    from app.planner import _coach_day_fields

    fields = _coach_day_fields(db, user.id, dt.date.today(),
                               {"name": "Base", "description": "30 min easy"})
    assert (fields["target_hr_low"], fields["target_hr_high"]) == (None, None)


# --- check_week: warn on degenerate bands and zone-implausible bands ---------


def _week_day(**kw):
    d = {"date": "2026-01-05", "workout_type": "easy_run", "title": "Easy",
         "duration_min": 40}
    d.update(kw)
    return d


def test_check_week_warns_on_degenerate_day_band():
    from app.planner import check_week

    days = [_week_day(target_hr_low=150, target_hr_high=150)]
    assert any("band" in w for w in check_week(days, budget=2))


def test_check_week_warns_on_degenerate_step_band():
    from app.planner import check_week

    days = [_week_day(
        workout_type="tempo",
        steps=[{"repeat": 1, "steps": [
            {"kind": "work", "duration_min": 20, "distance_km": None,
             "target_pace": None, "target_hr_low": 165, "target_hr_high": 165,
             "note": ""}]}],
    )]
    assert any("band" in w for w in check_week(days, budget=2))


def test_check_week_warns_on_zone_implausible_band():
    from app.planner import check_week

    # An easy run prescribed in z5 is implausible even as a real band.
    days = [_week_day(target_hr_low=172, target_hr_high=190)]
    assert any("zone" in w for w in check_week(days, budget=2, hr_zones=ZONES))


def test_check_week_warns_when_band_reaches_far_beyond_plausible_zones():
    from app.planner import check_week

    # Midpoint sits in z3, but the band spans z2-z5: not contained in z1-z3.
    days = [_week_day(target_hr_low=130, target_hr_high=190)]
    assert any("zone" in w for w in check_week(days, budget=2, hr_zones=ZONES))


def test_check_week_warns_on_zone_implausible_work_step():
    from app.planner import check_week

    days = [_week_day(
        workout_type="tempo",
        steps=[{"repeat": 1, "steps": [
            {"kind": "work", "duration_min": 20, "distance_km": None,
             "target_pace": None, "target_hr_low": 110, "target_hr_high": 130,
             "note": ""}]}],
    )]
    assert any("zone" in w for w in check_week(days, budget=2, hr_zones=ZONES))


def test_check_week_allows_easy_recovery_step_on_quality_day():
    from app.planner import check_week

    # A z1 recovery float inside an interval session is correct, not implausible.
    days = [_week_day(
        workout_type="intervals",
        steps=[{"repeat": 4, "steps": [
            {"kind": "work", "duration_min": 4, "distance_km": None,
             "target_pace": None, "target_hr_low": 160, "target_hr_high": 172,
             "note": ""},
            {"kind": "recovery", "duration_min": 2, "distance_km": None,
             "target_pace": None, "target_hr_low": 110, "target_hr_high": 130,
             "note": ""}]}],
        duration_min=24,
    ),
        _week_day(date="2026-01-06", duration_min=60),
        _week_day(date="2026-01-08", duration_min=60)]
    assert check_week(days, budget=2, hr_zones=ZONES) == []


def test_check_week_accepts_real_zone_bands():
    from app.planner import check_week

    days = [_week_day(target_hr_low=130, target_hr_high=145)]
    assert check_week(days, budget=2, hr_zones=ZONES) == []


# --- execution scoring: a stored degenerate band is widened before scoring ---


def test_scoring_segment_widens_stored_degenerate_band(db):
    import datetime as dt

    from app.execution import _idaten_segments
    from app.models import PlanDay

    day = PlanDay(user_id=1, date=dt.date.today(), workout_type="easy_run",
                  title="Easy", duration_min=40,
                  target_hr_low=150, target_hr_high=150)
    segs = _idaten_segments(day, ZONES)
    assert len(segs) == 1
    assert (segs[0]["low"], segs[0]["high"]) == (145, 160)  # z3 contains 150


def test_scoring_segment_widens_degenerate_step_band(db):
    import datetime as dt

    from app.execution import _idaten_segments
    from app.models import PlanDay

    day = PlanDay(
        user_id=1, date=dt.date.today(), workout_type="tempo", title="Tempo",
        steps=[{"repeat": 2, "steps": [
            {"kind": "work", "duration_min": 10, "distance_km": None,
             "target_pace": None, "target_hr_low": 165, "target_hr_high": 165,
             "note": ""}]}],
    )
    segs = _idaten_segments(day, ZONES)
    assert len(segs) == 2
    assert all((s["low"], s["high"]) == (160, 172) for s in segs)  # z4


def test_scoring_segment_keeps_real_band(db):
    import datetime as dt

    from app.execution import _idaten_segments
    from app.models import PlanDay

    day = PlanDay(user_id=1, date=dt.date.today(), workout_type="easy_run",
                  title="Easy", duration_min=40,
                  target_hr_low=130, target_hr_high=145)
    segs = _idaten_segments(day, ZONES)
    assert (segs[0]["low"], segs[0]["high"]) == (130.0, 145.0)


# --- proposal clamp: a degenerate band in an edit is widened, not stored -----


def test_pending_edit_widens_degenerate_bands_incl_steps(db, user):
    import datetime as dt

    from app.planner import create_pending_edit

    _cache_zones(db, user.id)
    day = {
        "date": dt.date.today().isoformat(), "workout_type": "tempo",
        "title": "Threshold", "description": "", "duration_min": 38,
        "distance_km": None, "target_pace": None,
        "target_hr_low": 165, "target_hr_high": 165,
        "steps": [{"repeat": 1, "steps": [
            {"kind": "work", "duration_min": 18, "distance_km": None,
             "target_pace": None, "target_hr_low": 165, "target_hr_high": 165,
             "note": ""}]}],
        "rationale": "test",
    }
    edit, error = create_pending_edit(db, user.id, [day], "s", "r")
    assert error is None
    stored = edit.changes[0]
    assert (stored["target_hr_low"], stored["target_hr_high"]) == (160, 172)
    step = stored["steps"][0]["steps"][0]
    assert (step["target_hr_low"], step["target_hr_high"]) == (160, 172)


def test_pending_edit_keeps_real_bands(db, user):
    import datetime as dt

    from app.planner import create_pending_edit

    _cache_zones(db, user.id)
    day = {
        "date": dt.date.today().isoformat(), "workout_type": "easy_run",
        "title": "Easy", "description": "", "duration_min": 40,
        "distance_km": None, "target_pace": None,
        "target_hr_low": 130, "target_hr_high": 145, "steps": None,
        "rationale": "test",
    }
    edit, error = create_pending_edit(db, user.id, [day], "s", "r")
    assert error is None
    stored = edit.changes[0]
    assert (stored["target_hr_low"], stored["target_hr_high"]) == (130, 145)


# --- generate_plan: one corrective retry on a degenerate band ----------------


class QueueLLM:
    """Returns queued structured results, recording every call's messages."""

    def __init__(self, results):
        self.results = list(results)
        self.calls = 0
        self.messages_seen = []

    def complete_structured(self, system, messages, schema, name):
        self.calls += 1
        self.messages_seen.append(messages)
        return self.results.pop(0)


def _plan_day(date, low, high):
    return {"date": date.isoformat(), "workout_type": "easy_run", "title": "Easy",
            "description": "40 min easy", "duration_min": 40, "distance_km": None,
            "target_pace": None, "target_hr_low": low, "target_hr_high": high,
            "steps": None, "rationale": "test"}


def test_generate_plan_retries_once_on_degenerate_band(db, user, monkeypatch):
    import datetime as dt

    import app.planner as planner
    from app.models import PlanDay

    today = dt.date.today()
    stub = QueueLLM([
        {"days": [_plan_day(today, 150, 150)], "adjustment_note": "", "strength_sessions": []},
        {"days": [_plan_day(today, 130, 145)], "adjustment_note": "", "strength_sessions": []},
    ])
    monkeypatch.setattr(planner, "make_client", lambda provider=None, **_kw: stub)
    planner.generate_plan(db, user.id)
    assert stub.calls == 2
    correction = stub.messages_seen[1][-1]["content"]
    assert "HR band" in correction
    row = db.get(PlanDay, (user.id, today))
    assert (row.target_hr_low, row.target_hr_high) == (130, 145)


def test_generate_plan_no_retry_when_bands_are_real(db, user, monkeypatch):
    import datetime as dt

    import app.planner as planner

    stub = QueueLLM([
        {"days": [_plan_day(dt.date.today(), 130, 145)], "adjustment_note": "",
         "strength_sessions": []},
    ])
    monkeypatch.setattr(planner, "make_client", lambda provider=None, **_kw: stub)
    planner.generate_plan(db, user.id)
    assert stub.calls == 1
