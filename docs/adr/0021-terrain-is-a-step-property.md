# Terrain is a step property; uphill work is prescribed by effort and verified after the fact

A workout step carries `terrain` (`"flat" | "uphill" | "downhill"`, absent meaning flat).
An uphill step always targets an HR band and never a pace band, in every training mode.
Terrain never reaches the watch as a target; it is confirmed after the run from the climb the activity recorded, and that confirmation is stored beside the execution score rather than inside it.

The forces begin with a hard external constraint.
Garmin's workout service can end a step on distance, time, heart rate, calories or the lap button, and can target pace, heart rate, cadence or power.
There is no grade trigger and no grade target for running - grade exists only as an indoor-cycling trainer target.
So a hill session reaches the watch as ordinary time-based intervals, and the watch cannot enforce, display or score the fact that a repetition happened on a hill.
Everything that makes a hill session a hill session has to live in Idaten.

That constraint met a live defect.
`workout_library` has always shipped a `hill_repeats` template, typed `intervals`, so the coach could already program hill sessions.
`intervals` is in `QUALITY_TYPES`, and the plan prompt's `training_mode` rules say quality days take a pace target in `hybrid` - the default mode.
The template hedged by writing "@ I effort" rather than "@ I pace", but the prompt rule overrode the hedge, so a hill session was prescribed with a flat-ground pace band.
The damage ran end to end: `garmin/push.py` `_target` sent it as `pace.zone`, so the watch alarmed for the whole repetition, and `execution.py` `_step_segment` scored the run against that same band, so a correctly-executed hill session was graded as a failure.
Nothing caught it: `pace_violations` checks format and grounding against the athlete's real paces, and a correct I-pace on a hill passes both.

Uphill pace is a function of the gradient, not of effort.
The same athlete at the same effort runs a 4% grade and an 8% grade at completely different paces, so no flat-ground band is reachable on a climb.
Heart rate absorbs the extra load of the climb, which makes an HR band the only honest target - the prescribe-by-effort rule the hill-workouts ticket had already reasoned its way to.

Terrain is modelled at the step, not as a workout type.
A hill session is not a fifth kind of intensity; it is intensity run on a gradient.
Terrain is orthogonal to `workout_type` - a hilly easy run, a hilly long run and hill repeats are all real, and only some of a hill session's steps are uphill anyway (the jog back down is not).
`workout_type: "hills"` would have conflated the two axes and forced a choice for every future combination.

The repetition is prescribed by time, never by distance, and the jog down is a lap-button step.
The dose of a hill repetition is the duration of the effort; the same distance is a different workout on a different gradient.
A lap-button recovery carries neither `duration_min` nor `distance_km`, so the athlete presses when they reach the bottom and the session fits whatever hill they have, with no per-athlete configuration.
This is what lets one template serve every user of an open-source project rather than only those whose local hill matches a hardcoded length.

Because the watch cannot enforce the hill, verification is post-hoc.
Garmin does give back per-lap `elevationGain`, so `execution.hill_check` asks whether the prescribed climbing actually happened and records the answer next to the score.
Laps are matched to repetitions by climb, not by `wktStepIndex`: index alignment depends on how a given watch laps a structured workout and breaks entirely under auto-lap, while "the prescribed climbs are the laps that climbed the most" holds however the run was recorded.

## Considered Options

- **A `"hills"` workout type** - rejected: it conflates terrain with intensity. Terrain is orthogonal to workout type, so this forces a combinatorial choice for every hilly variant of an existing session (hilly long run, hill tempo) and still cannot say that only *some* steps of the session are uphill. It also costs an enum change across eight backend call sites and four frontend label maps for a distinction that is not about intensity at all.
- **A prompt rule with no deterministic guard** - rejected: this is exactly the arrangement that produced the defect. The template already said "effort" and the model still wrote pace, because the `training_mode` rule actively steers the other way. A rule the model can silently disobey is not an invariant; `terrain_target_violations` plus the corrective retry is, and `push.py` refusing to send a pace target on an uphill step makes it true of stored days that predate the guard.
- **Per-athlete hill geometry settings** (`hill_length_m`, `hill_grade_pct`) - rejected: it is a narrow field only one template reads, it still fails the athlete with no hill or only a treadmill, and it makes distance-based reps look reasonable when they are the wrong prescription. The general fact is the athlete's terrain, not one hill, so this is served by free text (`athlete.running_environment`) that the coach reads as prose and that also covers "no track", "trails", "treadmill in winter".
- **Score terrain as a third axis inside `execution_score`** - rejected: the score is a continuous time-in-band measure over HR and pace, and whether the ground went up is a yes/no fact. Folding a boolean into a continuous score corrupts both - a session held perfectly at the prescribed effort on the flat is a terrain failure and an effort success, and one number cannot say that. `hill_check` sits beside the score and says it plainly.
- **Verify by matching laps to steps via `wktStepIndex`** - rejected: `stepOrder` in our pushed payload counts repeat-group containers as well as their children, Garmin's lap indexing is watch-dependent, and a run recorded under auto-lap carries no step linkage at all. Matching by climb needs no alignment assumption and degrades gracefully.
- **Terrain on the step, HR target enforced at generation and at push, verified post-hoc from per-lap climb** - chosen.

## Consequences

- `metrics.step_terrain` is the single reader, and absence is indistinguishable from `"flat"`, so no stored step needs migrating.
- An uphill step stored with only a pace target (written before the guard) reaches the watch with no target and is left out of the execution score rather than scored against an unreachable band. Both are logged; neither is silent.
- `hill_check` is null on nearly every run, which is intended - it is a fact about hill sessions, not a field every activity carries.
- The coach now sees `elevation_gain_m` on every recent activity, not only on hill days. Terrain is part of what a run cost, and the plan prompt reads a hilly easy run as more load than a flat one.
- The verification threshold (`MIN_REP_ASCENT_M`, 8m) and the majority rule are deliberately coarse. They separate "ran up a hill" from "ran on the flat"; they are not a grading of how big the hill was.
- Frontend `stepEndLabel` now names a lap-button step ("Lap press") instead of returning null, because these steps are generated on purpose rather than arising from malformed data.
- `hill_check` follows the same attribution as the score (ADR 0018), and is resolved inside `score_run` rather than at the call site. It asserts something to the athlete ("this was a hill session, but your reps show almost no climbing"), so it may only ever be said about a run that actually executed that prescription - never about a free run that happened to fall on a hill day, and never about a run whose `mismatch` shows it executed a different workout.
- `ascent_m` is the climb over all the matched repetitions, not only the qualifying ones. A failed check reporting `0` could not distinguish "ran on the flat" from "measured nothing", and that number is what makes the verdict legible to the athlete.
- The athlete's free-text setting is `running_environment`, deliberately NOT `terrain`. `terrain` is the canonical name for a step's gradient (CONTEXT.md), and one word carrying both a closed enum and free prose would break the glossary rule that a canonical term has one meaning.
