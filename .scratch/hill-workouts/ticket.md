# Ticket: hill runs as a workout type

Filed 2026-07-27 (idea captured 2026-07-18, ROADMAP - dissolved into tickets, see git history).
Status: built 2026-08-08, decisions recorded in ADR 0021. Remaining work below.

## What the dig found

The premise was wrong in one important way: hill sessions already shipped.
`workout_library` has always carried a `hill_repeats` template typed `intervals`, and the planner selects from the library, so the coach could already program them.
The gap was never the workout - it was the target and the check.

It also found a live defect.
`intervals` is a quality type, quality days take a pace target in the default `hybrid` mode, so hill sessions were prescribed with a flat-ground pace band.
The watch alarmed for the whole repetition and the execution score graded a correctly-run hill session as a failure.
The template's "@ I effort" wording was overridden by the prompt's training_mode rule, and no guard caught it (a correct I-pace on a hill passes both the format and the grounding check).

## Load-bearing technical finding (from the FIT spec, 2026-07-18; verified against garminconnect 0.3.2 on 2026-08-08)

Garmin CANNOT trigger or target intervals by elevation.
Step triggers are time / distance / calories / HR / lap-button only; step targets are pace, HR, cadence, or power - grade exists only as an indoor-cycling trainer target.
Our own push path is narrower still: `_end_condition` emits distance/time/lap-button and `_target` emits pace.zone/heart.rate.zone.
So a hill workout on the watch is normal time-/distance-based intervals; the watch cannot enforce that it happened on a hill.

Also settled: step notes do NOT travel to the watch (`garmin/push.py` docstring - Garmin renders a step description as a notes screen the athlete pages past mid-interval).
The hill cue is the workout-level description plus the in-app step note, both read before the run.

## Shipped

- `terrain` on the step (`flat` / `uphill` / `downhill`), read through `metrics.step_terrain`; absent means flat, so nothing stored needed migrating.
- Uphill steps take an HR band, never pace: prompt rule, `planner.terrain_target_violations` with a corrective retry, and `push.py` `_target` refusing pace on an uphill step so days stored before the guard are covered too. `execution._step_segment` leaves a pace-only uphill step unscored rather than scoring it wrongly.
- `hill_repeats` reworked: 45-75s reps timed (not distance), uphill terrain, lap-button jog-down so the session fits any hill with no per-athlete configuration.
- `elevation_gain_m` to the coach on EVERY run (plan snapshot + execution-analysis payload), as an `Activity` property over `raw` - no migration, and years of history answer immediately.
- `athlete.running_environment` free text ("Where you run" in Settings) instead of structured hill geometry - it also covers no-track, trails, treadmill.
- `execution.hill_check`: matches laps to repetitions by climb (not `wktStepIndex`, which breaks under auto-lap), stored beside the score on `Activity.hill_check` and surfaced in the API and the activity page.

## Open follow-ups

1. `hill_check` is computed at enrichment only. A run enriched before this shipped has `hill_check` null forever; scores are never recomputed (ADR 0018), and it is not obvious whether terrain should follow that rule or be backfillable.
2. Downhill work is representable but never prescribed - no template uses it beyond the jog-down.
3. The break-test showed the model reaches for the athlete's literal hill length (`distance_km: 0.2` for a stated 200m hill) when the prompt does not insist on timing the rep. That is a sensible instinct fighting the ADR 0021 rule, and it only holds because the prompt says so. If it keeps resurfacing, revisit whether a known hill length should be allowed to make a rep distance-based.
