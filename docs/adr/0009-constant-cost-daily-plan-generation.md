# System-initiated coach calls are curated one-shots, not agent loops

The daily pipeline is: code builds a fixed-size snapshot, one structured-output LLM call produces the artifact, code applies the result.
`generate_plan` (`planner.py`) assembles ~3-4k tokens - recent days in detail, older history pre-digested into aggregates (CTL/ATL/TSB, ACWR ramp, recent-pace profile, quality budget) - and makes one `complete_structured` call against `PLAN_SCHEMA`.
Every number the model sees was computed deterministically in code first; the LLM's job is structure and narrative judgment, never arithmetic.
The same shape serves the daily review, execution analysis, and weekly summary.
Only chat runs the tool-using agent loop (ADR 0004).

The rule behind the asymmetry: **agency when the question is unpredictable, curation when it isn't.**
Chat lets the model pick its data via tools because the athlete could ask anything; the planner and review do the same job every day, so the needed context is knowable in advance.

The daily review can still propose plan changes - but through its output schema, not a tool call.
`REVIEW_SCHEMA` carries `should_propose` + `proposal`; code inspects the result and calls `create_pending_edit`, the same function the chat tool `propose_plan_edit` dispatches to.
One enforcement point, two callers: the approval gate, pace guard, and one-pending invariant (ADR 0006) cannot be bypassed by either path.
The model never has write agency outside chat.

## Considered Options

- **Stuff full history into the prompt** - rejected: cost grows every day forever, and irrelevant context is where invented numbers come from.
- **Give the planner the chat agent's tool loop** - rejected: pays latency and tokens daily to rediscover the same known context, and multiplies the trajectory surface the evals would have to cover.
- **Let the LLM compute the metrics** - rejected: arithmetic over hundreds of days of data is the hallucination front door; computing metrics in code makes grounding assertable.
- **Curated snapshot + one structured call, deterministic guards around it** - chosen.

## Guards

- `pace_violations`: if proposed paces drift from the athlete's observed paces, code quotes the specific violations back and gives the model exactly one corrective retry; a still-violating plan ships with a logged warning rather than blocking (a plan must exist by morning - an owned tradeoff).
- `check_week`: verifies the model obeyed the prompt's rules (quality budget, ramp cap, hard-time share) and logs violations rather than silently repairing - a repair would desync the plan from its rationales.

## Consequences

- Cost is constant regardless of account age; the snapshot does not grow with history.
- Grounding is checkable: the evals can assert model claims against snapshot ground truth (the literal-30-km pattern), because ground truth exists in code.
- The stored snapshot doubles as frozen provenance on the review, which is what makes COACH_QUALITY.md's replay harness possible.
- Snapshot design is a curation bet: the model only knows what the snapshot includes, so every field is a hand-maintained decision, and a signal that ages out of the detail window is invisible to it.
- Aggregates lose specifics: the planner cannot reference one workout from weeks ago the way chat can fetch it.
