"""One target axis per step (ADR 0025): the dual-target guard, the chat-path
clamp, and the scorer's pace-first precedence that matches what the UI shows.

Born from a real session: easy steps carried both a pace band (which the app
displayed) and an HR band (which the scorer silently graded against), so the
athlete ran to a target they were never scored on.
"""
from __future__ import annotations

import datetime as dt

from app import planner

TODAY = dt.date(2026, 9, 10)


def _step(kind="work", **kw):
    base = dict(kind=kind, duration_min=1.0, distance_km=None, target_pace=None,
                target_hr_low=None, target_hr_high=None, note="", terrain="flat")
    base.update(kw)
    return base


def _day(**kw):
    d = {"date": TODAY.isoformat(), "workout_type": "tempo", "title": "Tempo",
         "description": "", "duration_min": 30, "distance_km": None,
         "target_pace": None, "target_hr_low": None, "target_hr_high": None,
         "steps": None, "rationale": "test"}
    d.update(kw)
    return d


# --- the guard ---------------------------------------------------------------

def test_dual_target_guard_flags_a_step_with_both_axes():
    day = _day(steps=[{"repeat": 1, "steps": [
        _step("warmup", duration_min=5, target_pace="9:29-8:05",
              target_hr_low=138, target_hr_high=152)]}])
    violations = planner.dual_target_violations([day])
    assert len(violations) == 1
    assert "warmup" in violations[0] and "both" in violations[0]


def test_dual_target_guard_flags_day_level_dual_targets():
    day = _day(target_pace="6:50", target_hr_low=138, target_hr_high=152)
    violations = planner.dual_target_violations([day])
    assert len(violations) == 1 and "day" in violations[0]


def test_dual_target_guard_passes_single_axis_steps():
    day = _day(steps=[{"repeat": 1, "steps": [
        _step("warmup", duration_min=5, target_hr_low=138, target_hr_high=152),
        _step("work", duration_min=7, target_pace="7:01-6:46"),
    ]}])
    assert planner.dual_target_violations([day]) == []


def test_dual_target_guard_ignores_half_open_hr_bands():
    # A lone bound is not a band; the HR-band guard owns that failure mode.
    day = _day(steps=[{"repeat": 1, "steps": [
        _step("work", target_pace="4:10", target_hr_low=150)]}])
    assert planner.dual_target_violations([day]) == []


# --- the chat-path clamp -----------------------------------------------------

def test_drop_dual_targets_keeps_the_displayed_pace():
    day = _day(steps=[{"repeat": 1, "steps": [
        _step("warmup", duration_min=5, target_pace="9:29-8:05",
              target_hr_low=138, target_hr_high=152)]}])
    out = planner._drop_dual_targets(day)
    s = out["steps"][0]["steps"][0]
    assert s["target_pace"] == "9:29-8:05"
    assert s["target_hr_low"] is None and s["target_hr_high"] is None
    assert planner.dual_target_violations([out]) == []


def test_drop_dual_targets_clears_day_level_hr():
    out = planner._drop_dual_targets(
        _day(target_pace="6:50", target_hr_low=138, target_hr_high=152))
    assert out["target_pace"] == "6:50"
    assert out["target_hr_low"] is None and out["target_hr_high"] is None


def test_drop_dual_targets_leaves_single_axis_days_alone():
    day = _day(steps=[{"repeat": 1, "steps": [
        _step("warmup", duration_min=5, target_hr_low=138, target_hr_high=152)]}])
    assert planner._drop_dual_targets(day) == day
