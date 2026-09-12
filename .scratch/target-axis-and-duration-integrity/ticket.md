# Target-axis and duration integrity

Three defects found from a real scored workout (user 2's "Short tempo session", 30 min header vs 28 min of steps, execution score 55 with HR-scored easy segments the UI showed as pace).

## 1. Day duration must agree with the steps

`duration_min` is LLM-authored and never reconciled with the step sum.
Fix: in `apply_plan_days`, when every step in a day's blocks carries `duration_min`, overwrite the day-level `duration_min` with the repeat-expanded step sum.
Covers both the planner and accepted chat edits (one seam).
One-time in-container recompute of existing stepped rows after deploy.

## 2. Pace bands display faster-first everywhere

Storage stays "slower-faster" strings (order-agnostic downstream via `pace_band_mps`).
Add `formatPaceBand` in `frontend/lib/workout.ts` that renders faster-first with an en dash, used by `workoutTargetLabel`, `stepTargetLabel`, `compactStep`, and the plan detail Target tile - matching `execution-score.tsx`.
Fix the contradictory schema example at `planner.py` day-level `target_pace` (example was faster-first).

## 3. One target axis per step; scoring judges what was shown

- Scorer (`execution._step_segment`): non-uphill steps prefer PACE when a well-formed band exists, HR otherwise (was HR-first). Uphill keeps HR-or-unscored. Log when a step carries both.
- New deterministic guard `dual_target_violations` + corrective retry in `generate_plan` (pattern: terrain guard).
- Chat path mechanical clamp `_drop_dual_targets` (keeps pace, drops HR; runs after `_drop_uphill_pace`).
- Prompt: "one target type per day" reworded to per-step/per-field exactly-one-axis.
- ADR 0025 records the invariant and the shared precedence rule.

## Status

- [x] Backend: scorer precedence pace-first + test
- [x] Backend: dual_target_violations guard + retry + clamp + tests
- [x] Backend: duration derivation in apply_plan_days + test
- [x] Frontend: formatPaceBand + call sites + tests
- [x] Prompt example fix + wording
- [x] ADR 0025
- [x] Full suites green (backend 618 passed, frontend 71 passed, tsc clean)
- [x] ./start.sh deploy (gate green, stack up)
- [ ] One-time recompute of existing rows - 5 past rows identified; the write to the live DB needs the user to run it (permission-gated)
