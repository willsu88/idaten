# Testing

Idaten is an LLM app, but most of Idaten is not an LLM.
Snapshot builders, pace math, the pending-edit state machine, tool dispatch, the scheduler's catch-up logic - all of it is ordinary deterministic code, and it gets ordinary deterministic tests.
Yet the LLM's coaching behavior is what differentiates the product - and that contribution, the judgment in a coach note, the restraint in a weekly review, cannot be asserted with `==`.
Pretending otherwise produces either flaky tests or no coverage at all.

So the suite is split along one line: **pytest tests machinery, evals test judgment.**
Layers 1-2 below are deterministic, free, and run on every `./start.sh` (ADR 0001: a red test never reaches the live app).
Layers 3-5 call a real model, cost money, and are opt-in via `pytest -m eval`.
But cost and judgment are different boundaries: trajectory tests (layer 3) pay for a real model yet still assert hard facts - which tools were called, with what arguments - because an agent's tool choices are judgment expressed as assertable actions.
Only what survives every hard assertion is left to a judge, and a behavior always goes into the cheapest layer that can catch its failure.

The boundary between the two sides is a design decision, not a fact of nature.
Every time logic moves out of the prompt and into code - pace limits computed by `planner.py` instead of trusted to the model - a behavior migrates from the expensive judged side to the cheap asserted side.
When a judged behavior feels hard to eval, the first question is not "how do I write a better judge" but "should this be code."

## The five layers

### Layer 1 - Unit

Pure logic with no HTTP and no model: encryption round-trips (`test_crypto.py`), ramp-rate and pace math (`test_ramp.py`), text cleanup (`test_clean_llm_text.py`).
Catches: a wrong formula, a broken edge case.
Deliberately doesn't: anything about wiring or judgment.
Runs in the `start.sh` gate.

### Layer 2 - API / integration

FastAPI `TestClient` against a lifespan-free app (no scheduler threads) with a real per-test SQLite database - the `client` and `db` fixtures in `conftest.py`.
The LLM is stubbed or absent; the point is routes, auth, persistence, and state machines.
`test_tenant_isolation.py` is the load-bearing example: it proves user A can never read user B's rows (ADR 0008), which is a wiring fact, not a judgment.
Catches: broken endpoints, auth holes, state-machine violations.
Deliberately doesn't: whether the coach says anything sensible.
Runs in the `start.sh` gate.

### Layer 3 - Trajectory

A real model drives the real agent loop, but `dispatch` is monkeypatched with a recorder (the `world` fixture in `test_evals.py`), so every tool call lands in a list as `(name, args)` - a minimal trace, in the observability sense.
Assertions are trajectory evaluation in the industry sense - hard facts read from that trace: the exhausted-athlete case must end in a proposed edit and must not claim it was applied; the weekly-km answer must be grounded in tool data; the out-of-scope question must trigger no tools at all.
Catches: an agent that stops calling tools, calls the wrong one, hallucinates instead of looking, or acts without proposing.
Deliberately doesn't: prose quality - a trajectory test passes even if the wording is clumsy.
Opt-in: `pytest -m eval`.

### Layer 4 - LLM-judge

A second model grades what cannot be asserted, against one binary criterion per case.
Binary, not 1-5: industry practice is to use the lowest-precision scale that captures the distinction, and a pass/fail verdict against concrete rubric violations is checkable, while a 3.7 is not.
The tone rubrics follow the same rule - the persona specs in `test_persona_evals.py` name countable violations ("does not stack analytics", "does not cite composite scores"), not aesthetics, which is what makes a tone verdict binary at all.

Two judges with opposite doubt policies, because the cost of a wrong verdict is asymmetric in opposite directions:
`judge()` (`test_evals.py`) grades semantic claims about the reply - does the prose imply the plan was already changed, does it stay in its coaching lane - claims that are binary and factual but live in meaning rather than state, so no string assertion can reach them.
It fails when in doubt: a reply whose meaning is ambiguous to the judge is ambiguous to the athlete, and a false pass blesses a coach that misrepresented what happened.
`tone_judge` (`test_persona_evals.py`) grades voice against the persona rubrics and fails only on clear violations - borderline word choices flake, and a flaky red suite trains people to ignore red, which is worse than shipping a mildly off-voice note.
Even inside an eval test, anything checkable against known state stays a hard assertion (`assert "30" in reply` - the fixture knows the true total); the judge gets only the semantic residue.
Catches: a coach note that buries the one thing that mattered, a reply that oversells what the system did, a persona drifting off voice.
Deliberately doesn't: anything a hard assertion could have caught, and cross-conversation persona drift - notes are one-shot daily artifacts, so per-note grading matches the product.
Opt-in: `pytest -m eval`.

### Layer 5 - Snapshot replay (designed, not yet built)

Stage 3 of `COACH_QUALITY.md`: every thumbs rating freezes the rated output with its exact inputs and prompt version (ADR 0014), so prompt editing becomes red-green - replay accumulated thumbs-down cases through a candidate prompt, hold thumbs-up cases as anti-regression anchors.
Catches: a prompt edit that re-introduces a failure a real user already flagged.
Exists today as: the capture side (ratings with frozen provenance); the replay runner is the missing piece.

## Where does a new test go?

Walk down; stop at the first yes.

1. **Can pure code produce the failure?** (a formula, a parser, a state transition)
   Layer 1. No fixtures beyond what the function needs.
2. **Does the failure need routes, auth, or the database - but not a model's decision?**
   Layer 2, on the `client`/`db` fixtures. Stub the LLM; the model's output is not what's under test.
3. **Is the failure a wrong *action* - wrong tool, wrong arguments, tool skipped, tool invented?**
   Layer 3. Record the calls, assert the trajectory. Prose stays unjudged.
4. **Is the failure only visible in what the prose *means* or how it *sounds*?**
   Layer 4. One binary criterion per case; meaning goes to `judge()` (fail-closed), voice goes to `tone_judge` (fail-open).
   Assert everything assertable first - the judge gets only the residue.
5. **Did a real user already flag it?**
   That is layer 5's job once the replay runner exists; until then, distill it into a layer 3-4 case by hand.

Two standing rules across all layers:

- **A judged behavior that keeps failing is a design smell, not an eval problem.**
  A red case has three diagnoses, and only one touches the rubric: red once after a change means the prompt regressed - fix the prompt, the eval did its job; red chronically across reasonable prompts means the behavior was assigned to the wrong owner - move the logic into code and the eval is replaced by a stronger, free assertion (pace limits went from "judge whether the paces are sensible" to `check_week` asserting the violations list is empty, ADR 0009); flaky on an unchanged prompt means the criterion is not binary enough - fix the rubric.
  A rubric may be changed to reduce variance, never to reduce standards; lowering the standard is a product decision, not a test fix.
- **Layers classify assertions, not test files.**
  Industry practice runs trajectory and final-response checks against the same run, because the canonical agent bug - a correct answer reached via a wrong trajectory - is only visible when both observe one execution.
  So a scenario stacks assertion kinds against one paid agent run, cheap first: `test_exhausted_proposes_edit_and_never_claims_applied` asserts the trajectory from the recorded trace, then judges only the prose.
  The judge's own (separate, paid) call runs last and only if the hard assertions held - not just because it is expensive, but because its question is meaningless on a broken run: "the reply doesn't claim the edit was applied" is vacuously true when no edit was proposed.
  Files organize by cost instead: a file is entirely eval-gated (`pytestmark = pytest.mark.eval`) or entirely free, never mixed.
  The one hard rule: never delegate an assertable fact to the judge - if half a criterion could be an `assert`, split it out; the judge gets the residue.

## Adding an eval case

Layers 1-2 are ordinary pytest and need no instruction.
For a layer 3-4 case, the steps are mechanical:

1. Seed the scenario into the fixture world (`seed_world` or a variant) so ground truth is known.
   An eval without known ground truth cannot hard-assert anything - it can only judge, which makes it the weakest possible test.
2. Run one real agent turn through the `world` fixture.
3. Assert the trajectory from the recorded `calls`: tool names, arguments, and absences (`assert not called(...)` is as load-bearing as `assert called(...)`).
4. Assert any state or string facts the seeded world makes checkable (`assert "30" in reply` works because the fixture knows the true total).
5. Only then, judge the residue: one criterion, phrased so a yes/no answer exists, and the test name states it - `test_exhausted_proposes_edit_and_never_claims_applied` *is* its criterion.

This procedure is also encoded as a repo skill (`.claude/skills/add-eval-case/SKILL.md`) so agents follow it without re-deriving it.

## Cross-references

- ADR 0005: the judge calls `make_client()` - evals ride the same `LLMClient` seam as production, so there is no separate test-only provider path to drift.
- ADR 0014 + `COACH_QUALITY.md`: the flight recorder's frozen thumbs ratings are the intake for layer 5.
- ADR 0001: `start.sh` is the gate where layers 1-2 run; a red test never reaches the live app.
