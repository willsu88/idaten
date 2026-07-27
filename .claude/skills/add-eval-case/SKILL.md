---
name: add-eval-case
description: Add a test for coach/agent behavior in the right layer - use when protecting a new LLM behavior, adding an eval, or unsure whether something needs a judge or an assert.
---

# Add an eval case

The reasoning behind every rule here lives in `docs/TESTING.md`. Read it if a step feels arbitrary.

## Step 1: Place the behavior

Walk down; stop at the first yes.

1. Pure code can produce the failure -> ordinary unit test. Stop; this skill does not apply.
2. Needs routes/auth/DB but not a model's decision -> layer 2 on the `client`/`db` fixtures (`backend/tests/conftest.py`), LLM stubbed. Stop.
3. The failure is a wrong action or wrong prose -> continue below. The case goes in `backend/tests/test_evals.py` (behavior) or `test_persona_evals.py` (voice), file-level `pytestmark = pytest.mark.eval`.

## Step 2: Seed known ground truth

Use `seed_world` (or extend it) so every fact the test relies on is known in advance.
An eval without known ground truth cannot hard-assert anything - it can only judge, which is the weakest possible test.

## Step 3: Run one real agent turn

Use the `world` fixture: `run, calls = world`, then `reply = run("<the user message>")`.
One paid model call per scenario; stack all checks against it.

## Step 4: Assert everything assertable, cheapest first

Order matters - a red must point at one kind of defect, and later checks are meaningless if earlier ones fail:

1. Trajectory: `called(calls, "tool_name")` for presence, args, and absences. `assert not called(...)` is as load-bearing as `assert called(...)`.
2. State: query the DB for rows the tools should have created.
3. Strings: facts the seeded world makes checkable (`assert "30" in reply`).

## Step 5: Judge only the residue

Only what survives every hard assertion goes to a judge, one binary criterion per case:

- Meaning ("must not imply the edit was applied") -> `assert_judge` in `test_evals.py`. Fail-closed: ambiguity is failure.
- Voice ("reads like the strict coach") -> `tone_judge` in `test_persona_evals.py`. Fail-open: only clear violations fail.

Never delegate an assertable fact to the judge - if half a criterion could be an `assert`, split it out.
Phrase the criterion so a yes/no answer exists, and name the test after it: `test_exhausted_proposes_edit_and_never_claims_applied` is its own criterion.

## Step 6: Verify both ways

Run `pytest -m eval -k <your_test>` and confirm it passes.
Then break the behavior (or the criterion) and confirm it fails for the stated reason - a judge case that cannot go red proves nothing.

## Red-case triage (when an existing eval fails)

- Red once after a change: the change regressed the behavior. Fix the prompt/code, not the test.
- Red chronically across reasonable prompts: wrong owner - move the behavior into code and replace the eval with a cheap assertion.
- Flaky on an unchanged prompt: criterion not binary enough - fix the rubric to reduce variance, never to reduce standards.
