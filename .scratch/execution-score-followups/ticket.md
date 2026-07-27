# Ticket: execution score - remaining nice-to-haves

Filed 2026-07-27 (feature complete + deployed 2026-07-19; leftovers from ROADMAP - dissolved into tickets, see git history). Status: idea.

## Leftovers

- **Tier-2 auto-shape-match attribution**: today only tier 1 (Garmin `trainingPlanId` / Idaten-pushed day) auto-scores; a run that merely looks like the planned workout on a planned day falls to the tier-3 confirm prompt.
  Rarely matters while both live users are tier-1 editor-mode, so it waits for author-mode traffic.
- **Trends line for execution score over time** - the scores exist for every scored run; no chart reads them yet.
- **Live browser eyeball** of the Today ResultCard swap + AttributionCard - both fire only on fresh/ambiguous runs, none present in live data at build time; confirm on a real occurrence.
