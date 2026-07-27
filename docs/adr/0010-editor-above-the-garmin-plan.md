# Idaten is an editor above the Garmin plan, not a competing author

When a Garmin Coach adaptive plan is active, Garmin is the base plan and Idaten demotes itself from author to editor: it never writes a competing week, it produces diffs against Garmin's plan through the PendingEdit machinery (ADR 0006).
`plan_mode` (`planner.py`) returns `editor` whenever a Garmin plan is active on the day, `author` otherwise or when the athlete forces authoring in Settings, so one code path stays meaningful for everyone.
This resolved the root problem of two plan authors competing (Idaten's `generate_plan` vs the mirrored Garmin Coach plan): whose week is on the watch?

The division of labor is the product's positioning.
Garmin's on-watch adaptation (Daily Suggested Workouts and the adaptive coach plan) is deliberately acute and reactive: it decides today's workout from current physiology - VO2max, acute/chronic load, recovery, HRV, sleep - with some race-goal weighting, and it does that well.
It does not review multi-day structure: no mesocycle planning, no hard/easy spacing review, no weekly pattern analysis (verified against public documentation of DSW's behavior).
Idaten's value is exactly the structural layer above it: hard/easy spacing, threshold density, phase-appropriate progression.
The founding incident is field data: an athlete's watch prescribed three threshold sessions in one week - all-green on every acute readiness metric, and precisely the structural error only a multi-day review catches.

## Considered Options

- **Keep two authors** - rejected: competing weeks on the watch and in the app; churn and mistrust.
- **Mirror the live DSW as the base** - impossible, verified 2026-07-17: the same-day workout swap is computed on-device and exposed by no API.
  The base is therefore the structured coach plan taskList; Idaten consumes the same inputs Garmin uses and applies its own logic, rather than mirroring an opaque output.
- **Gate the daily review on a deterministic readiness threshold** - rejected: a gate is by construction blind to structural errors (the three-threshold week trips no acute threshold), and cost is a non-reason at this scale.
  Determinism's role is grounding and validation (ACWR, spacing signals, the pace guard), never the on/off switch for intelligence.
- **Advisory notes without diffs** - rejected for the same reason as in ADR 0006: the one-tap diff is the product.
- **Editor above the base plan** - chosen.

## Consequences

- No competing sources of truth; the product line is "the layer above the watch, not a replacement for it."
- Editor and author modes share the proposal path, so approval semantics are identical in both.
- Author mode has no live user; it is covered by seeded evals rather than live testing - an honest asymmetry.
- The base plan depends on the mirrored taskList: a Garmin API change breaks editor mode's ground truth.
- Coach-plan workouts carry HR targets, not paces, so editor-mode grounding must speak HR; the pace guard needs an HR analog - a known gap.
- Garmin's own Training Readiness proved unavailable on the live devices, so Idaten computes its own readiness signal from already-synced data (HRV vs baseline, sleep, RHR trend, stress, body battery) - no new device dependency.
