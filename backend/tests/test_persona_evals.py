"""Persona-adherence evals: do Sam, Koa, and Viktoria actually sound like
themselves? Opt-in like the other model evals - real LLM calls, real key:

    ANTHROPIC_API_KEY=sk-... .venv/bin/python -m pytest tests/test_persona_evals.py -m eval -v

Two layers on top of the free persona_lint unit tests (test_persona_lint.py):

1. Per-persona voice checks: generate a real daily-review note per persona on
   the same seeded day, hard-assert persona_lint, then judge TONE only. Metric
   rules stay mechanical - see the hard-won note in test_evals.py about
   number-averse judges failing correct number-dense notes.
2. Blind identification: a judge must attribute each of the three notes to its
   coach from voice alone. This is the discriminative test - a note can pass
   its own checklist while all three personas still sound identical, which is
   exactly the failure this suite exists to catch.

Costs a few cents per run.
"""

from __future__ import annotations

import pytest
from test_evals import (
    TODAY, _d, _easy, _hard, _rest, requires_real_key, seed_editor_world,
)

pytestmark = pytest.mark.eval

# One seeded day, two moods: a red-flag morning before a planned hard session
# (rest-override note) and a healthy well-spaced week (green-light note).
SUPPRESSED_WEEK = [_hard(_d(0)), _easy(_d(1)), _rest(_d(2)), _easy(_d(3)),
                   _rest(_d(4)), _easy(_d(5)), _hard(_d(6))]
GREEN_WEEK = [_rest(_d(0)), _easy(_d(1)), _hard(_d(2)), _easy(_d(3)),
              _rest(_d(4)), _easy(_d(5)), _hard(_d(6))]

STYLES = ("default", "chill", "strict")

# Tone-only criteria; each encodes the persona spec in STYLE_PROMPTS.
PERSONA_CRITERIA = {
    "default": (
        "Reads like a calm, experienced running coach: measured and warm, candid "
        "about trade-offs, concrete about what to do today. Numbers serve a "
        "point and are interpreted for the athlete rather than recited as a "
        "dashboard. Neither gushing nor scolding."
    ),
    "chill": (
        "Reads like a relaxed friend texting a runner: warm, casual, plain "
        "everyday language. Measurement jargon is a violation (HRV, VO2max, "
        "readiness/execution scores, training zones, load numbers), as is "
        "reciting training-history statistics. Everyday runner vocabulary is "
        "fine (easy run, long run, tempo, intervals), and so is describing "
        "today's workout plainly: duration, distance, a simply-phrased "
        "heart-rate or pace target. Translating metrics into body feel "
        "('you're fresh', 'a rough night for your body') is exactly right."
    ),
    "strict": (
        "Reads like a strict, no-excuses coach: direct, declarative, says the "
        "uncomfortable part plainly, and holds the athlete accountable. Numbers "
        "appear mainly as targets and orders (minutes, bpm, pace); the note "
        "does NOT justify its calls by stacking analytics (several metrics or "
        "prediction arithmetic in one note) or by citing app-composite scores "
        "(readiness, execution). Naming the cause briefly - qualitatively or "
        "with a single physiological figure like HRV or sleep hours - is fine. "
        "On a good day this may "
        "read as businesslike command rather than warmth - that passes. It must "
        "not be cruel, insulting, or gushingly soft."
    ),
}


def tone_judge(criteria: str, note: str) -> dict:
    """Voice judge. Unlike test_evals.judge (safety bias: fail when in doubt),
    tone judging with a fail-on-doubt bias flakes on borderline word choices,
    so this judge fails only on CLEAR violations."""
    from app.llm import make_client

    return make_client().complete_structured(
        system=("You judge whether a running coach's note matches a described "
                "voice. Judge ONLY voice and tone against the criteria. Return "
                "passed=false only for a CLEAR violation of the criteria; "
                "borderline word choices pass."),
        messages=[{"role": "user",
                   "content": f"Criteria: {criteria}\n\nCoach's note:\n{note}"}],
        schema={"type": "object",
                "properties": {"passed": {"type": "boolean"},
                               "reason": {"type": "string"}},
                "required": ["passed", "reason"], "additionalProperties": False},
        name="verdict",
    )


def generate_note(db, user, style: str) -> str:
    """One real daily-review note in `style` for the already-seeded day.
    evaluate_today memoizes per (user, date), so the review row is dropped
    afterwards to let the next persona regenerate instead of reading this one."""
    from app.planner import evaluate_today
    from app.settings_store import put_settings

    put_settings(db, user.id, {"coach_style": style})
    review = evaluate_today(db, user.id, TODAY)
    note = review.coach_note or ""
    assert note.strip(), f"empty coach note for style {style!r}"
    db.delete(review)
    db.commit()
    return note


# --- layer 2: each persona against its own spec ----------------------------------

@requires_real_key
@pytest.mark.parametrize("style", STYLES)
def test_rest_override_note_stays_in_voice(db, user, style):
    """The voice-revealing scenario: tanked recovery before a planned hard day.
    Chill must soothe without metrics, strict must be firm about resting."""
    from app.planner import persona_lint

    seed_editor_world(db, user.id, SUPPRESSED_WEEK, suppressed=True)
    note = generate_note(db, user, style)
    assert persona_lint(style, note) == [], \
        f"lint violations {persona_lint(style, note)}\n--- note ---\n{note}"
    verdict = tone_judge(PERSONA_CRITERIA[style], note)
    assert verdict["passed"], f"{verdict['reason']}\n--- note ---\n{note}"


@requires_real_key
@pytest.mark.parametrize("style", STYLES)
def test_green_day_note_stays_in_voice(db, user, style):
    """Green-light days are where personas previously collapsed into one
    interchangeable 'you look well recovered' voice."""
    from app.planner import persona_lint

    seed_editor_world(db, user.id, GREEN_WEEK)
    note = generate_note(db, user, style)
    assert persona_lint(style, note) == [], \
        f"lint violations {persona_lint(style, note)}\n--- note ---\n{note}"
    verdict = tone_judge(PERSONA_CRITERIA[style], note)
    assert verdict["passed"], f"{verdict['reason']}\n--- note ---\n{note}"


# --- layer 3: are the voices even distinguishable? -------------------------------

@requires_real_key
def test_personas_are_blind_identifiable(db, user):
    """Same athlete, same day, one note per persona; a judge attributes each
    note to its coach from one-line descriptions. Chance is 1 in 6 - if the
    judge can't do it, the voices haven't differentiated, no matter how well
    each note passes its own checks."""
    from app.llm import make_client

    seed_editor_world(db, user.id, SUPPRESSED_WEEK, suppressed=True)
    notes = {style: generate_note(db, user, style) for style in STYLES}

    labels = {"A": "default", "B": "chill", "C": "strict"}
    coach_of = {"sam": "default", "koa": "chill", "viktoria": "strict"}
    body = "\n\n".join(f"Note {label}:\n{notes[style]}"
                       for label, style in labels.items())
    verdict = make_client().complete_structured(
        system=(
            "Three coaches with different personalities each wrote one note "
            "about the SAME athlete on the SAME day. Attribute every note to "
            "its author purely from voice and style. The coaches:\n"
            "- sam: calm, balanced, data-fluent; a few interpreted numbers\n"
            "- koa: relaxed friend texting; zero jargon, no raw metrics\n"
            "- viktoria: strict and direct; no excuses, consequences named"
        ),
        messages=[{"role": "user", "content": body}],
        schema={
            "type": "object",
            "properties": {label: {"type": "string",
                                   "enum": ["sam", "koa", "viktoria"]}
                           for label in labels},
            "required": list(labels),
            "additionalProperties": False,
        },
        name="attribution",
    )
    attributed = {label: coach_of[verdict[label]] for label in labels}
    assert attributed == labels, (
        f"judge attribution {verdict} does not match truth {labels}\n"
        + "\n\n".join(f"--- {s} ---\n{n}" for s, n in notes.items())
    )
