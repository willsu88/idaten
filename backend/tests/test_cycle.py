from __future__ import annotations

import datetime as dt

from app import metrics
from app.settings_store import normalize_cycle

# Anchor: period started Mon 2026-06-01, 28-day cycle, 5-day period.
ANCHOR = {
    "enabled": True,
    "last_start_date": "2026-06-01",
    "cycle_length_days": 28,
    "period_length_days": 5,
}


def phase_on(offset_days: int, cycle=ANCHOR) -> dict | None:
    return metrics.cycle_phase(cycle, dt.date(2026, 6, 1) + dt.timedelta(days=offset_days))


def test_disabled_or_missing_anchor_returns_none():
    assert metrics.cycle_phase(None, dt.date(2026, 6, 1)) is None
    assert metrics.cycle_phase({"enabled": False, "last_start_date": "2026-06-01"},
                               dt.date(2026, 6, 1)) is None
    assert metrics.cycle_phase({"enabled": True, "last_start_date": None},
                               dt.date(2026, 6, 1)) is None
    assert metrics.cycle_phase({"enabled": True, "last_start_date": "not-a-date"},
                               dt.date(2026, 6, 1)) is None


def test_menstrual_phase_and_early_flow_ease():
    # Day 1 and day 2 of flow: ease recommended; day 5 still menstrual, no ease.
    for off in (0, 1):
        p = phase_on(off)
        assert p["phase"] == "menstrual"
        assert p["day_of_cycle"] == off + 1
        assert p["ease_recommended"] is True
    p5 = phase_on(4)  # day 5 = last period day
    assert p5["phase"] == "menstrual" and p5["ease_recommended"] is False


def test_follicular_and_luteal_are_normal():
    assert phase_on(7)["phase"] == "follicular"    # day 8
    assert phase_on(7)["ease_recommended"] is False
    assert phase_on(18)["phase"] == "luteal"       # day 19, not yet premenstrual
    assert phase_on(18)["ease_recommended"] is False


def test_premenstrual_window_eases():
    # Days 26, 27, 28 (3,2,1 days to next start) -> premenstrual + ease.
    for off in (25, 26, 27):
        p = phase_on(off)
        assert p["phase"] == "premenstrual", off
        assert p["ease_recommended"] is True
        assert p["days_to_next_period"] == 28 - off
    # Day 25 (4 days out) is still luteal.
    assert phase_on(24)["phase"] == "luteal"


def test_next_period_date_and_forward_projection():
    # Second cycle: 28 days later day 1 again.
    p = phase_on(28)
    assert p["phase"] == "menstrual" and p["day_of_cycle"] == 1
    # From day 10 of cycle 1, next period is the 28-day mark = 2026-06-29.
    assert phase_on(9)["next_period_date"] == "2026-06-29"


def test_backward_projection_before_anchor():
    # 28 days BEFORE the anchor is also day 1 of a (projected) cycle.
    p = metrics.cycle_phase(ANCHOR, dt.date(2026, 6, 1) - dt.timedelta(days=28))
    assert p["phase"] == "menstrual" and p["day_of_cycle"] == 1


def test_garbage_cycle_length_falls_back_to_default():
    bad = {**ANCHOR, "cycle_length_days": 900}
    p = metrics.cycle_phase(bad, dt.date(2026, 6, 1))
    assert p["cycle_length_days"] == 28


def test_in_drift_window_is_tight_band_around_start():
    # 2 days before start .. 1 day after: days 27, 28, 1, 2 for a 28-day cycle.
    assert phase_on(26)["in_drift_window"] is True   # day 27 (2 to go)
    assert phase_on(27)["in_drift_window"] is True   # day 28 (1 to go)
    assert phase_on(0)["in_drift_window"] is True    # day 1
    assert phase_on(1)["in_drift_window"] is True    # day 2
    # Outside the band: mid-cycle and 3 days before are quiet.
    assert phase_on(2)["in_drift_window"] is False   # day 3
    assert phase_on(14)["in_drift_window"] is False
    assert phase_on(25)["in_drift_window"] is False  # day 26 (3 to go)


def test_normalize_cycle_coerces_and_rejects():
    assert normalize_cycle(None) == {
        "enabled": False, "last_start_date": None,
        "cycle_length_days": 28, "period_length_days": 5,
    }
    # Bad anchor dropped, out-of-range lengths ignored, valid kept.
    out = normalize_cycle({
        "enabled": True, "last_start_date": "2026-06-01",
        "cycle_length_days": 999, "period_length_days": 6,
    })
    assert out["enabled"] is True
    assert out["last_start_date"] == "2026-06-01"
    assert out["cycle_length_days"] == 28   # 999 rejected -> default
    assert out["period_length_days"] == 6
    # Malformed anchor -> None, tracking still on.
    out2 = normalize_cycle({"enabled": True, "last_start_date": "13/2026"})
    assert out2["last_start_date"] is None
    # enabled must be a real bool, not truthy string.
    assert normalize_cycle({"enabled": "yes"})["enabled"] is False
