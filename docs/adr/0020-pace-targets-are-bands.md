# A prescribed pace is a band, parsed in exactly one place

`target_pace` (on a plan day or on any step inside its `steps` blocks) holds either a single pace `"M:SS"` or a band `"M:SS-M:SS"` in min/km, and nothing else.
Every consumer reads it through `metrics.pace_band_mps`, which returns the `(slow, fast)` speed bounds in m/s; the planner rejects on write anything that function cannot read.

The forces: `metrics.pace_to_mps` split on `":"` and unpacked exactly two values, so any other shape raised and returned `None` with no log line.
Three consumers then failed open on that `None`, each in a way that looked like a deliberate absence of a target rather than a parse failure.
`garmin/push.py` `_target` fell through to `no.target`, so a paced step reached the watch with nothing to chase.
`execution.py` `_step_segment` returned `None` and dropped the step from the breakdown entirely.
`planner.pace_violations` used the same parser, so a pace it could not read also skipped the grounding guard that exists to catch dangerous prescriptions.

This was not hypothetical.
The planner prompt tells the model that `training_paces` bands are `[slower, faster]` min/km and to resolve `T` from them, while the schema described `target_pace` as `M:SS` - the model was handed a band and given a scalar field to put it in.
On the first pace-based structured workout in production it wrote `"6:50-7:05"` on all three work intervals of a threshold session.
The watch showed no target for those intervals, and the execution score judged only the warmup, the two easy floats and the cooldown: 18 of 38 minutes vanished, and the athlete was graded on how gently they jogged between hard reps.
HR-target workouts were unaffected, because an HR band is two integers that cannot be malformed - which is the point.

The resolution has three parts.
A pace target is a band, because that is what it always was: `push.py` already admitted this by fabricating one with `PACE_BAND_MPS = 0.15` around the stored number, and the athlete's own `training_paces` are ranges.
When the plan gives us real bounds we use them; a bare `M:SS` still gets `PACE_BAND_MPS` either side, so nothing about existing single-pace data changes.
`pace_band_mps` is the only parser, so the band the watch is given and the band the score is judged against cannot drift apart.
And `pace_format_violations` runs at the planner and chat-edit boundary with no dependence on a pace profile, feeding the existing corrective-retry, so an unreadable pace is an error at write time instead of silent damage at read time.

## Considered Options

- **Keep `target_pace` scalar and normalize a band to its midpoint on write** - rejected: it discards information the coach actually prescribed in order to preserve a field shape that was never load-bearing, and it leaves `push.py` synthesizing a ±0.15 m/s band that may be narrower or wider than the one intended.
- **Model the band as a pair of columns** (`target_pace_low`/`target_pace_high`, the ADR 0017 shape) - rejected for now: it is the cleaner model, but it costs a schema migration across the plan schema, the chat tool, the frontend types, push and scoring, for no behavioral gain over parsing one string in one place. The string form also stays directly renderable, which is how the UI already displays it.
- **Fix only the parser and leave the guards alone** - rejected: the parser returning `None` is not the defect, failing open on `None` is. Without the write-time guard the next unreadable shape ("~7:00", "6:50 min/km", "sub 7:00") reproduces the same three silent failures.
- **Accept both forms, one parser, reject the rest on write** - chosen.

## Consequences

- ADR 0017's aside that "the pace precedent does not transfer: `target_pace` is a single field, so widening at push is the only option there" no longer holds. Both target types are now bands; they differ only in storage shape, and that difference is now a deliberate cost decision rather than a constraint.
- `PACE_BAND_MPS` moves to `metrics` and has one definition. It previously existed in `garmin/push.py` and `execution.py` with a comment asking the two to stay in sync by hand.
- `pace_seconds` reads a band as its midpoint, so the grounding guard treats a band as the pace a coach would say it was.
- The frontend's `paceToMinPerKm` accepts a band on the same midpoint rule; it silently fell back to a nominal 6:00/km before, drawing distance-based timeline segments at the wrong width.
- "Exactly one place" is true per language, not globally: the grammar is written twice, once in `metrics._pace_parts` and once in `lib/workout.ts`. That is the standing cost of the string form, and it is why the accepted set is deliberately tiny - two shapes a regex states in one line. If it ever grows, that is the signal to take the column-pair migration above.
- `pace_violations` now checks step-level paces, not only day-level ones. The grounding half is still day-level only, because interval work steps legitimately run faster than any whole-run average.
- Bad paces already in storage are not migrated. There was one such day; it is repaired by re-scoring, and the write-time guard prevents new ones.

## Amendment (2026-08-14): band width is steered by prompt, not by guard

Production plans prescribed bands too tight to run by (e.g. 5:50-6:10 on an easy day), because nothing told the model how wide a band should be.
The planner prompt and the chat-tool schema now state the widths: easy/recovery/long bands span at least 20-30 s/km, quality bands at least 10 s/km.
This is deliberately prompt guidance, not a deterministic width guard: a prescribed band is still used verbatim (this ADR's core rule), because a legitimate tight band exists (a race-pace rep) and a mechanical widener cannot tell it from a mistake.
If tight bands persist in QA, the escalation path is a `pace_band_width_violations` guard on the ADR 0017 corrective-retry pattern.
