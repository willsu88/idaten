"""persona_lint unit tests - the deterministic layer of the persona evals.

Every "flags" case below is a violation pattern observed verbatim in real
production notes before the persona rewrite; if one starts failing, the regex
regressed against known-bad output, not a hypothetical.
"""

from app.planner import persona_lint


def test_chill_flags_metric_acronyms():
    assert persona_lint("chill", "Your HRV is below baseline today.")
    assert persona_lint("chill", "That fits the low RPE, so not a bad day.")
    assert persona_lint("chill", "Your VO2max is 49, so this steady work fits.")
    assert persona_lint("chill", "Your VO2 max is trending up.")
    assert persona_lint("chill", "TSB is -6.6 right now.")


def test_chill_flags_scores_and_zones():
    assert persona_lint("chill", "Your execution is improving, with an 80 score on that run.")
    assert persona_lint("chill", "That was a score of 91.")
    assert persona_lint("chill", "Readiness is 82 this morning.")
    assert persona_lint("chill", "Keep it in z2 for the whole run.")
    assert persona_lint("chill", "Stay in zone 2 today.")


def test_chill_allows_plain_workout_targets():
    # A target that IS the workout may stay, phrased plainly.
    assert persona_lint("chill", "Nice and easy today, around 140-150 bpm.") == []
    assert persona_lint("chill", "Keep it around 6:30/km, chatty pace, and enjoy it.") == []


def test_metric_names_allowed_outside_chill():
    assert persona_lint("default", "HRV is back at baseline, so run as planned.") == []
    assert persona_lint("strict", "HRV is down and sleep was short. Rest today.") == []


def test_load_indices_banned_for_every_persona():
    for style in ("default", "chill", "strict"):
        assert persona_lint(style, "TSB is only -2.1, so quality is justified.")
        assert persona_lint(style, "Your ACWR is trending high this week.")


def test_strict_flags_dashboard_recitation():
    # Verbatim from a real production note (2026-07-22): orders backed by
    # analytics recitation - the exact failure the strict persona must not make.
    note = ("Do the prescribed 35-minute Threshold today, including 15 minutes "
            "at 182 bpm. Readiness is green at 83, HRV is 53 versus a 46 "
            "baseline, and TSB is only -2.1, so quality is justified despite "
            "6.7 hours of sleep. Your recent execution average is 62 with no "
            "low streak, so stay controlled and hit the target instead of "
            "racing it.")
    violations = persona_lint("strict", note)
    assert any("TSB" in v for v in violations)
    assert any("Readiness is green at 83" in v for v in violations)
    # Targets and qualitative causes stay legal for strict.
    assert persona_lint("strict", "35 minutes with 15 at 182 bpm. HRV is down, "
                                  "so stay controlled and hit the target.") == []


def test_stock_openers_flagged_for_every_persona():
    for style in ("default", "chill", "strict"):
        assert persona_lint(style, "Solid run today, you kept it controlled.")
        assert persona_lint(style, "Today's plan is a 35-minute threshold session.")
        assert persona_lint(style, "You look well recovered today.")
    # Only as openers - the phrase mid-note is fine.
    assert persona_lint("strict", "That was a solid run. Keep stacking them.") == []


def test_em_dash_flagged():
    assert persona_lint("default", "Rest today — you earned it.")


def test_clean_and_empty_notes_pass():
    assert persona_lint("strict", "You skipped Thursday's threshold. That's two this block.") == []
    assert persona_lint("chill", "") == []
    assert persona_lint("chill", None) == []
