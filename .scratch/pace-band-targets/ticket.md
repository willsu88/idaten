# Pace targets are bands; week rows must truncate, not clip

Two user-reported defects, fixed together because both are "a value we accepted silently did damage downstream".

## A. Week view clips the chevron and hard-cuts long titles

The collapsed day row (`frontend/app/week/page.tsx`) is a flex item without `min-w-0`, so its
automatic minimum size is its max-content size.
The title column's own `min-w-0 flex-1` therefore never gets to shrink and `truncate` never fires.
The row grows past the Card, and `overflow-hidden` on the Card silently eats the overflow -
the chevron is last in DOM order, so it disappears first.

Measured at a 393px viewport against the app's compiled CSS:

| row | card width | row width | overflow |
| --- | --- | --- | --- |
| Mon (chip + score ring) | 361 | 413 | 52px, chevron fully clipped, score ring partly clipped |
| Thu (long title) | 361 | 476 | 115px, chevron fully clipped, title hard-cut with no ellipsis |

`min-w-0` on the row stops the clipping, but on its own it starves the title to ~31px on a
chip-heavy row: the row spends ~330 of ~355 available px on fixed `shrink-0` furniture before
the title gets anything.
So the fix is `min-w-0` plus a mobile budget.

The budget cut is the type badge, not the chips.
The first proposal was to shrink the badge column to auto-width and move the intent/support/
strength chips into the expanded panel, but that trades away the wrong thing: the chips carry
information found nowhere else in the row, while the badge duplicates the colored left bar and,
on an easy or long run, the title text beside it.
Dropping the badge below `sm` frees 106px against ~30px for shrinking it, and it costs nothing
that is not already on screen.
The badge reappears at the top of the expanded panel on mobile, so the label is one tap away.
That leaves ~109px of title on a 393px phone with a chip and a score ring present.

## B. A pace *range* silently disabled the watch target and the score

`PlanDay(user 2, 2026-08-07).steps` stored `target_pace: "6:50-7:05"` on all three work intervals.
`metrics.pace_to_mps` splits on `":"` and unpacks two values, so a range raises and returns `None`,
with no log line.
That one silent `None` cost three things:

1. `garmin/push.py` fell through to `no.target`, so the watch showed no target for the work
   intervals (verified by reading the pushed workout back from Garmin).
   HR workouts were unaffected because an HR band is two integers that cannot be malformed.
2. `execution.py` dropped those steps from scoring entirely.
   The stored breakdown covers only warmup/recovery/cooldown - 18 of 38 minutes, the whole point
   of the session, were never judged, and the athlete was graded solely on how gently they jogged
   between hard reps.
3. `planner.pace_violations` uses the same parser, so range paces bypassed the pace sanity guard.

The planner prompt tells the model that `training_paces` bands are `[slower, faster]` min/km and
to resolve `T` from them, while `STEP_SCHEMA` describes `target_pace` as `M:SS`.
The model was handed a band and asked to put it in a scalar field.

### Decision

A prescribed pace *is* a band - `push.py` already admitted this by fabricating one with
`PACE_BAND_MPS = 0.15`. So we accept `"M:SS"` and `"M:SS-M:SS"`, parse both in one place, and use
the real endpoints when we have them instead of a synthetic band.
Anything else is rejected on write rather than silently dropped.

## Work

- [x] `metrics.pace_band_mps` - single parser, owns `PACE_BAND_MPS`; `pace_seconds` takes a
      range's midpoint; the parser itself logs on unparseable input instead of failing silently,
      so every consumer inherits the warning rather than each adding its own
- [x] `push.py` and `execution.py` both call it; the duplicated 0.15 constant collapses
- [x] `push.py` stops sending per-step `description` (Garmin renders it as a notes screen you
      must page past mid-interval); the workout-level description stays
- [x] `planner.pace_violations` gains a profile-independent format check covering step-level
      paces, feeding the existing corrective-retry
- [x] schema + prompt say a band is allowed; the chat-edit rejection note names format as well
      as grounding, so a model rejected for `"~7:00"` is not told to fix the wrong thing
- [x] the frontend reads a band too: `lib/workout.ts` `paceToMinPerKm` took the midpoint rule,
      having silently sized distance steps at a nominal 6:00/km
- [x] `CONTEXT.md` gains a "Pace target band" entry beside "HR target band"; `API_CONTRACT.md`
      v1.40 records the widened value set
- [x] week row `min-w-0` + mobile budget
- [x] repair the live data: re-push Friday, re-score the activity
