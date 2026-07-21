# UX Improvements

Working list from the 2026-07-21 UX/UI review (senior-designer pass: IA inventory + mobile code audit + API-vs-UI data gap analysis).
Status values: SHIPPED, DECIDED (build it), DISCUSSING (design open), IDEA (captured, not committed).

## SHIPPED 2026-07-21 (contract v1.24; 317 backend tests green; tsc + next build clean)

Items 1-5 below were all built 2026-07-21 (deploy: `docker compose up -d --build`; predeploy backup `garmin_bot_backup_predeploy_uxbatch_20260721.db` already taken in-container).
Notable implementation points: `WeekStrip` + `weekSummaryLine` extracted to `components/week-strip.tsx` (Week and Today share them); `scoreChipTone` exported from `components/execution-score.tsx` (Week strip + Activities chips share it); `/plan/week` gained a `summary` object (see API_CONTRACT.md v1.24); Week supports `?day=YYYY-MM-DD` to open + scroll to a day; Settings is optimistic everywhere and the Save button is gone.

## SHIPPED 2026-07-21 (v1.26.1 - page-order batch)

Two ordering changes decided with Will 2026-07-21 (rationale: interpretation above raw data; pending decisions never below the fold):

- **Activity detail read order**: route map first (map-sized skeleton while the series call is in flight, collapses for indoor runs), then the stat grid, then execution score + coach analysis, then charts/splits/zones/efficiency/effort/plan.
  Implementation: the series fetch was lifted to `useActivitySeries` in `components/activity-series.tsx`; `ActivityRouteSection` (top of page) and `ActivitySeriesSection` (charts) share the one request.
- **Today leads with the coach**: `DailyCoachNote` then a pending `EditProposalCard` moved ABOVE the readiness card (diagnosis before prescription; readiness is the note's supporting evidence). Week strip, cycle, niggles, workout/result, RPE, attribution keep their order below.

## DECIDED - build

### 1. Execution score chips on the Activities list

`Activity.execution_score` is already in the list payload (`frontend/lib/types.ts:115`) but rows only show RPE + raw stats (`frontend/app/activities/page.tsx:66-103`).
Add a small colored score chip per row, using the same 80/50 color thresholds as the Week strip.
Render-only work; makes the history list scannable ("which runs went badly this month?").

### 2. Week-at-a-glance strip on Today

Today is the mobile landing page but shows no shape of the week.
Reuse the Mon-Sun at-a-glance strip from `frontend/app/week/page.tsx` as a compact row on Today; tapping it navigates to `/week` (tapping a day can deep-link to that day).
Render-only; data already in the dashboard/week payloads.

### 3. Mobile polish batch (from the code audit, in order)

1. Dropdown menus can overflow the viewport: `min-w-[13rem]` with no clamp (`frontend/components/ui/dropdown-menu.tsx:91`). Add `max-w-[calc(100vw-2rem)]` and clamp horizontal position. Likely repro: Week row "More" menu near the right edge on a 375px phone.
2. Splits table has no scroll affordance (`frontend/components/activity-series.tsx:142`). Add an edge fade gradient to signal horizontal scrollability.
3. Dialogs don't autofocus their first input. Add focus management to the shared Dialog so mobile forms don't cost an extra tap.
4. `min-h-screen` in `frontend/components/app-shell.tsx:20` should be `min-h-dvh` so content fills the visual viewport under the mobile dynamic address bar (login already uses `dvh`).
5. Chat bubbles are capped at `max-w-[85%]` (`frontend/components/chat/chat-conversation.tsx:317`), leaving ~287px of content on a 375px phone. Widen to ~92% on mobile so coach markdown (tables, code) breathes.

### 4. Week volume summary (time-based, not distance-based)

DECIDED (Will 2026-07-21): no settings toggle - derive the frame from the plan itself.
Context: both athletes train on time-based plans (Garmin DSW style: "18min at threshold HR"), not distance-based, so a km-first summary would impose the wrong frame and planned km often doesn't exist.

- Primary line is time + intensity, because duration is the one field every plan day has: "4h10 planned - 3h05 done - 78% easy".
  The easy/hard split doubles as the 80/20 check and reuses existing time-in-zones data.
- Distance appears only as a secondary actuals-only stat from completed activities: "31.2 km run this week". A fact, not a target, so it needs no configuration.
- If a future plan block is genuinely distance-based, the plan days would carry distance targets and the summary can notice and adapt; add a unit setting only if that day comes.

### 5. Settings save model: optimistic everywhere

DECIDED (Will 2026-07-21): option 1 - optimistic everywhere.
Every control saves the moment it changes, like persona already does; the "Save settings" button disappears; the notes textarea saves on blur / short debounce.
One mental model: touching a setting is saving it.

Background: the page previously mixed two save models (persona/toggles instant, but training mode, plan source, notes, and plan hour only via a bottom-of-page Save button), so a change could be silently lost by navigating away.
Rejected alternative: sticky "Unsaved changes" bar - safer commit step, but plan-source changes are already mediated downstream (coach proposes edits rather than instantly rewriting the week), so the deliberate-commit step buys little.

### 6. Calm "no sleep data yet" state on Today

SHIPPED 2026-07-21 (contract v1.25, together with eager review generation; 325 backend tests green; tsc + next build clean).
Implementation: `/api/dashboard/review` returns `data_overdue` (no recovery data at >= plan_hour + 2h, household zone - the server decides, the client never guesses clock math); `DailyCoachNote` then drops the pulsing "syncing…" row for a static card ("No sleep data from Garmin yet - I'll pick it up when it lands.") with the structural-review action promoted to a secondary Button, and slows its poll from 5s to 60s so an afternoon sleep still gets picked up.

DECIDED (Will 2026-07-21, from the proactive-delivery discussion - see ROADMAP.md Idea C).
On a late-sync or no-sleep morning, Today currently shows "syncing…" on every visit while `ensure_fresh_today` keeps kicking deduped background syncs for data that is not there yet, which reads as the app being stuck rather than the data being absent.
After data is still missing by mid-morning, switch to a calm state: "No sleep data from Garmin yet - I'll pick it up when it lands", with the existing "Review anyway" (structural review) button promoted.
Same machinery, better honesty; pairs with eager review generation (ROADMAP.md Idea C) but is worth doing regardless.

## IDEA - captured, not committed

These came out of the same review but Will has not prioritized them yet.

- Flip `SHOW_RACE_PREDICTION` (`frontend/lib/flags.ts`) once the calibration model is trusted; Races currently shows only Garmin's number. Option: show both, labeled "Garmin says / Idaten says".
- Overlay open-niggle periods as shaded bands on the Trends training-load chart (onset/resolved dates already exist) to answer "did that load spike cause the knee thing?".
- Move the theme toggle from every page header (`frontend/components/page-header.tsx`) into Settings or the More sheet; reclaim the header slot for page-contextual actions.
- Mobile nav: promote Chat to a 4th bottom tab (Today - Week - Chat - More), drop the floating bubble on mobile (keep on desktop), move Trends into More. Chat is the product's front door (niggle logging now flows through it).
- Richer "Ask about this" context: show context chips in the chat composer so the user sees what the coach will look at.
