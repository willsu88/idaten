# Ticket: "structure this run for me" + plan-day page follow-ups

Filed 2026-07-27 (open follow-ups from the 2026-07-19 plan-detail build, ROADMAP - dissolved into tickets, see git history). Status: idea.

## Context (the load-bearing finding, verified live 2026-07-19)

Garmin's API exposes NO step breakdown for adaptive coach workouts (`workoutId` null, only a compact `workoutDescription` string); the pretty step view in Garmin's app is rendered client-side.
Decision: never synthesize stages onto Garmin days - fabricated structure is worse than honest whole-run targets.
Steps ARE fetchable for any workout with a real `workoutId` (saved-library + Idaten-pushed).

## The feature

An explicit opt-in "structure this run for me" action on a Garmin day: Idaten authors real steps the athlete CHOOSES - never passed off as Garmin's plan (editor-mode badging rule applies).
This also makes the day pushable with fetchable steps.

## Smaller follow-ups

- Server-computed time-in-zone (Z1-Z5) breakdown for structured days (deliberately not faked client-side; needs zone boundaries server-side).
- Intensity-height on the workout timeline bar.
