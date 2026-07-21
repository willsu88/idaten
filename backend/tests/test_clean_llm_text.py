"""Defensive normalizer: a model that over-escapes a unicode char (the literal
6 chars `\\u2014`) must never reach the UI as raw escape text, AND em-dashes (an
AI tell) are stripped to a spaced hyphen in athlete-facing prose."""

from __future__ import annotations

from app.planner import clean_llm_text, strip_em_dashes


def test_decodes_stray_unicode_escape():
    # ’ (curly apostrophe) is decoded and kept; only em-dashes are stripped.
    assert clean_llm_text("you\\u2019re on track") == "you’re on track"


def test_over_escaped_em_dash_is_decoded_then_stripped():
    # — -> — -> " - " (decode first, then strip the AI tell).
    assert clean_llm_text("moderate effort \\u2014 stay relaxed") == "moderate effort - stay relaxed"


def test_em_dashes_stripped_to_spaced_hyphen():
    assert strip_em_dashes("run today—you kept it easy") == "run today - you kept it easy"
    assert strip_em_dashes("75 min — fully HR-capped") == "75 min - fully HR-capped"
    assert clean_llm_text("nailed it—strong finish") == "nailed it - strong finish"


def test_en_dash_and_hyphen_left_alone():
    # En-dash (ranges) and plain hyphens are legitimate, not an AI tell.
    assert strip_em_dashes("hold 140–150 bpm") == "hold 140–150 bpm"
    assert strip_em_dashes("HR-capped easy run") == "HR-capped easy run"


def test_handles_none_and_empty():
    assert clean_llm_text(None) is None
    assert clean_llm_text("") == ""
    assert strip_em_dashes(None) is None


def test_multiple_em_dashes():
    assert strip_em_dashes("a—b—c") == "a - b - c"
