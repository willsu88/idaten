# Ticket: simulated athlete - persona-driven coach regression testing

Filed 2026-07-27 from a product brainstorm. Status: parked, lowest priority of the batch (test infrastructure; build after the QA rubric exists).
Industry analog: agent simulation / training environments - test the agent against adversarial users before real ones meet it.

## The idea

Synthetic athlete personas played against the coach in a loop, to stress-test behavior before shipping prompt or model changes:

- **The overtrainer**: pushes for more mileage, argues with rest days, reports low RPE on everything.
- **The chronic skipper**: misses workouts, wants the plan silently rebuilt around the gaps.
- **The injury-flirt**: drops hints of pain, tests whether the coach downshifts and stops prescribing intensity.
- **The data-skeptic**: challenges the coach's numbers, tests grounded citation vs confabulation.

Each persona is an LLM with a character brief plus a scripted fixture world (deterministic training data), run N turns against the real chat agent; transcripts are graded with the coach-QA rubric.

## Shape

- Extends the existing eval harness (`backend/tests/test_evals.py`): fixture world + tool-call recorder already exist; this adds a persona driver on the user side of the loop.
- Runs as an opt-in pytest marker like the current evals (`-m eval` pattern), plus optionally as a pre-release smoke script.
- Grading reuses the rubric from [[coach-qa-scorecards]] - build that first so simulation has a scoring target.
- Determinism discipline: personas may be stochastic, but the world (activities, readiness, plan) is fixed, so trajectory assertions on tool calls stay meaningful.

## Open questions

1. Turn budget per persona per run - cost grows as personas x turns x 2 models; pick smallest N that still exposes failures.
2. Are persona conversations graded pass/fail per rubric item, or scored for trend like prod QA?
3. How much value beyond the existing single-turn evals - validate with one persona (injury-flirt, the highest-stakes behavior) before building the roster.

## Note

Also feeds [[agent-eval-library]] - a persona driver is a strong second-consumer signal for what is library-shaped.
