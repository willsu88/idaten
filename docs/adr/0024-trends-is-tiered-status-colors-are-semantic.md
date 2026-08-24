# Trends is tiered - verdict tiles first, one hero chart per question, deep charts behind a disclosure - and green/amber/red carry verdicts only

The Trends page grew to twelve chart cards in a single scroll, every one a raw physiology series (CTL/ATL overlays, a temperature-encoded scatter, a dual-axis sleep chart with a hidden scale).
A user opening the page to answer "am I recovering, building safely, improving?" had to assemble the answer themselves.
Benchmarking against Whoop, Oura, and Garmin Connect showed the pattern every consumer training product converged on: progressive disclosure - a glanceable verdict tier, then a trend tier, with the scientific charts present but behind an explicit tap.

The rule this ADR settles has two halves:

1. **Presentation is tiered.**
   The top of Trends is a row of verdict tiles (Recovery, Load, Progress, Sleep): a headline value, a status tone, a direction arrow, a sparkline - no axes, no legends.
   Each section then shows exactly one hero chart, chosen as the single best answer to that section's question (HRV vs baseline; Form/TSB; aerobic efficiency).
   Every other chart lives behind a per-section "More charts" disclosure, unmounted until opened.
   New charts land in the detail tier by default; promoting one to hero means demoting the current hero, not showing two.
2. **Status colors are semantic and reserved.**
   Green/amber/red (`success`/`warning`/`danger` in `ChartTheme` and the Tailwind tokens) mean good/caution/bad, everywhere, and are used only for verdicts: tile tones, threshold bands, status chips.
   Series identity keeps the decorative palette (blue/indigo/teal/accent).
   A series line is never green because it is "the good metric", and a decorative hue never signals a state.

All tile and aggregation logic is pure functions in `frontend/lib/trends.ts`, unit-tested in `lib/trends.test.ts`; components only render the derived models.
Tile thresholds reuse the ones already shipped elsewhere (readiness-card HRV bands, ramp zones, Garmin sleep-score qualifiers) so no two surfaces disagree about the same number.

## Considered options

- **Better individual charts, same flat page** - rejected: the audit showed the density problem was chart count, not any one chart's construction; twelve well-made deep-dive charts still fail the at-a-glance test.
- **Move deep charts to separate drill-in pages per metric** (the Garmin Connect model) - rejected for now: more routes and navigation surface for a single-user app, and the disclosure gets the same effect with one tap and no page loads. Revisit if the detail tier keeps growing.
- **Native `<details>/<summary>` for the disclosure** - rejected: recharts' ResponsiveContainer measures a zero-height container inside a closed `<details>` in some browsers; conditional mounting is deterministic and also skips rendering cost for closed sections.
- **Encoding status into the existing palette** (e.g. amber doubles as both a series color and a warning) - rejected: it is the current state, and it means color carries no learnable meaning; the strict split is what makes tones readable preattentively.
- **Chosen: tiered page + reserved status colors**, both enforced by the shared seams (`lib/trends.ts`, `ChartTheme`, `StatTile`).

## Consequences

- The Today readiness card and the Trends tiles share `components/stat-tile.tsx`; a change to tile anatomy changes both surfaces, deliberately.
- The Sleep page inherits the color rule and the tile/sparkline components; its own chart fixes are a follow-up ticket (`.scratch/trends-revamp/ticket.md` lists them as out of scope).
- Tile derivation depends only on the `/api/trends` and `/api/analytics` payloads; a new tile must derive from existing contract fields or go through `API_CONTRACT.md` first.
- Sparklines are direction cues, not charts: no axes, no tooltips, no thresholds. If a sparkline needs any of those, the content belongs in a chart in the detail tier instead.
- The disclosure hides charts from users who never open it; anything that must never be missed (a pending decision, an injury-risk verdict) belongs in a tile, a chip, or the coach note - not in the detail tier.
