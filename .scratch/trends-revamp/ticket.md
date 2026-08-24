# Trends revamp: glanceable tiers

## Problem

The Trends page renders 12 chart cards in one scroll, all of them deep-dive charts.
A user opening the page to answer "am I recovering / building safely / improving?" has to assemble the answer from raw physiology series.
Benchmarking against Whoop, Oura, and Garmin Connect (2024 redesign) shows the industry-standard fix: progressive disclosure - a glanceable status tier first, one hero chart per question, deep charts behind an explicit affordance.

## Scope (this ticket)

Frontend only. No API changes - everything derives from existing `/api/trends` and `/api/analytics` payloads.

1. **Tile tier** at the top of Trends: Recovery, Load, Progress, Sleep.
   Each tile: headline value, semantic tone (green/amber/red), direction arrow, 14-day sparkline.
   Derivation is pure logic in `lib/trends.ts`, TDD'd in `lib/trends.test.ts`.
2. **Hero chart per section**, remaining charts collapsed behind a per-section "More charts" disclosure:
   - Recovery hero: HRV vs baseline. Details: Sleep hours, Resting HR.
   - Training load hero: Form (TSB). Details: Fitness & fatigue (CTL/ATL), Daily load, ACWR, Load ramp, Distance, Easy vs hard, Time in zones.
   - Progress hero: Aerobic efficiency (simplified). Details: HR drift, VO2max.
3. **Chart fixes**:
   - Trends Sleep chart: drop the score line that rode a hidden right axis; hours bars only (score lives in the Sleep tile).
   - Training load: split the 3-series single-axis chart into Fitness & fatigue (CTL/ATL lines) and Daily load (bars).
   - Load ramp: un-clamp the plotted ratio (domain extends to the data max) so the line matches the tooltip; threshold labels become words ("Caution") instead of numbers.
   - EF: rolling average becomes the hero line, points muted to a single color, temperature moves to tooltip-only (gradient encoding and legend removed).
   - Zones: new "Easy vs hard" weekly chart (Z1+Z2 vs Z3-Z5 share with an 80% target line); the 5-zone stack stays as a detail chart.
4. **Semantic status colors** (`success`/`warning`/`danger`) added to `ChartTheme`; tiles and chart bands use them.
5. **Shared StatTile**: promote the tile from `readiness-card.tsx` to `components/stat-tile.tsx` (with optional sparkline) and reuse it on both pages.
6. ADR 0024 records the tier structure + semantic color decision.

## Out of scope (follow-up ticket)

Sleep page chart fixes: duration-vs-need weekly aggregation past 30d, overnight mini-chart axis units, hypnogram minimum-width exaggeration, midnight cue on the consistency axis.
Today-page tile sparklines (reuses the StatTile built here).
CONTEXT.md glossary entries for the trends vocabulary (CTL/ATL/TSB, ACWR, ramp, EF) - today those definitions live only in `metric-info.tsx` copy.
