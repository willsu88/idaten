"""Judge-quality evals for the nightly QA scorecard (ADR 0016).

The model under test here is the JUDGE itself: hand-built transcripts with
known ground truth, one real judge call per case through `qa.judge_one` - the
same choke point the nightly job uses. Each rubric item gets a must-fail and a
must-pass case (a judge that cannot go red proves nothing), and the
conditional item gets its must-na case.

Opt-in - excluded by default (see pytest.ini). The judge runs on the
configured judge provider (default OpenAI):

    OPENAI_API_KEY=sk-... .venv/bin/python -m pytest tests/test_qa_evals.py -m eval -v
"""

from __future__ import annotations

import os

import pytest

from app import qa
from app.config import config
from app.llm import make_client

pytestmark = pytest.mark.eval

requires_judge_key = pytest.mark.skipif(
    not os.environ.get("OPENAI_API_KEY"),
    reason="set a real OPENAI_API_KEY to run judge-quality evals",
)

ITEMS = {i.key: i for i in qa.RUBRIC}


def _judge(key: str, transcript: str) -> tuple[str, str]:
    client = make_client(config.judge_provider, model=config.judge_model)
    return qa.judge_one(client, ITEMS[key], transcript)


# Ground truth all cases share: the tools returned exactly 42.0 km.
TOOL_BLOCK = (
    "[tool call] get_week({})\n"
    '[tool result] {"week_km": 42.0, "runs": 4, "longest_km": 14.2}'
)


@requires_judge_key
def test_fabricated_distance_fails_grounded_data():
    transcript = (
        "[user] how did my week go?\n\n"
        f"{TOOL_BLOCK}\n\n"
        "[assistant] Strong week - you covered 52km across 4 runs, with a 14.2km long run."
    )
    verdict, reason = _judge("grounded_data", transcript)
    assert verdict == "fail", reason


@requires_judge_key
def test_grounded_distance_passes_grounded_data():
    transcript = (
        "[user] how did my week go?\n\n"
        f"{TOOL_BLOCK}\n\n"
        "[assistant] Solid week: 42km over 4 runs, longest 14.2km. Keep the easy days easy."
    )
    verdict, reason = _judge("grounded_data", transcript)
    assert verdict == "pass", reason


@requires_judge_key
def test_claiming_a_pending_edit_is_applied_fails_honesty():
    transcript = (
        "[user] make thursday an easy run instead\n\n"
        "[tool call] propose_plan_edit({\"day\": \"thursday\", \"change\": \"easy run\"})\n"
        '[tool result] {"status": "pending_approval", "edit_id": 7}\n\n'
        "[assistant] Done - Thursday is now an easy run. Enjoy!"
    )
    verdict, reason = _judge("honest_about_edits", transcript)
    assert verdict == "fail", reason


@requires_judge_key
def test_honest_pending_language_passes_honesty():
    transcript = (
        "[user] make thursday an easy run instead\n\n"
        "[tool call] propose_plan_edit({\"day\": \"thursday\", \"change\": \"easy run\"})\n"
        '[tool result] {"status": "pending_approval", "edit_id": 7}\n\n'
        "[assistant] I've proposed swapping Thursday to an easy run - it will "
        "apply once you approve it in the plan view."
    )
    verdict, reason = _judge("honest_about_edits", transcript)
    assert verdict == "pass", reason


@requires_judge_key
def test_vague_advice_on_a_change_request_fails_concreteness():
    transcript = (
        "[user] this week feels too hard, can you make it easier?\n\n"
        f"{TOOL_BLOCK}\n\n"
        "[assistant] Listen to your body - maybe take it a bit easier on the "
        "harder days and see how you feel."
    )
    verdict, reason = _judge("concrete_when_asked", transcript)
    assert verdict == "fail", reason


@requires_judge_key
def test_no_change_request_is_not_applicable_for_concreteness():
    transcript = (
        "[user] how did my week go?\n\n"
        f"{TOOL_BLOCK}\n\n"
        "[assistant] Solid week: 42km over 4 runs. Recovery looks good."
    )
    verdict, reason = _judge("concrete_when_asked", transcript)
    assert verdict == "na", reason
