# Ticket: hill runs as a workout type

Filed 2026-07-27 (idea captured 2026-07-18, ROADMAP - dissolved into tickets, see git history). Status: idea.

## Want

Prescribe hill/elevation-interval sessions and (eventually) grade the athlete on them.

## Load-bearing technical finding (from the FIT spec, 2026-07-18)

Garmin CANNOT trigger or target intervals by elevation.
Step triggers are time / distance / calories / HR / lap-button only; step targets are pace, HR, cadence, or power - grade exists only as an indoor-cycling trainer target.
So a hill workout on the watch is normal time-/distance-based intervals plus a text instruction saying where to run them; the watch cannot enforce that it happened on a hill.
NOT yet verified against our actual `garminconnect` push path - verify the supported step trigger/target types before committing to a build.

## Leaning

- Prescribe by EFFORT (HR target) with a text cue like "on a 4-6% grade", never by pace (uphill pace is meaningless); HR naturally absorbs the climb's extra load.
- We DO get elevation gain back on the completed activity, so we can verify a hill run happened on a hill even though the watch couldn't enforce it.

## Open questions

Plan/watch rendering; how the coach decides when to program one; verify-by-elevation on completion.
