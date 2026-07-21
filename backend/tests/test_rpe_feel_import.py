"""Feature 1: convert Garmin's raw RPE (x10) and feel (0/25/50/75/100) to our
1-10 / 1-5 scales when importing per-activity summary data."""

from __future__ import annotations

from app.garmin.enrich import _rpe_feel


def test_rpe_feel_typical():
    # Garmin stores RPE x10 and feel in 25-point steps.
    assert _rpe_feel({"directWorkoutRpe": 30, "directWorkoutFeel": 50}) == (3, 3)
    assert _rpe_feel({"directWorkoutRpe": 100, "directWorkoutFeel": 100}) == (10, 5)
    assert _rpe_feel({"directWorkoutRpe": 10, "directWorkoutFeel": 0}) == (1, 1)


def test_rpe_feel_absent():
    assert _rpe_feel({}) == (None, None)
    assert _rpe_feel({"directWorkoutRpe": None, "directWorkoutFeel": None}) == (None, None)


def test_rpe_zero_treated_as_unlogged():
    # RPE 0 is not a valid 1-10 rating — treat it as "not logged".
    assert _rpe_feel({"directWorkoutRpe": 0})[0] is None


def test_feel_zero_is_very_weak_not_absent():
    # feel=0 is a real value (Very Weak -> 1), distinct from missing.
    assert _rpe_feel({"directWorkoutFeel": 0}) == (None, 1)
