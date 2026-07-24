# Idaten — API Contract (backend at http://localhost:8000)

All routes are JSON under `/api`. Dates are `YYYY-MM-DD` strings.

## Shared types

```ts
type ReadinessLevel = "green" | "yellow" | "red";

interface Readiness {
  score: number;              // 0-100
  level: ReadinessLevel;
  components: {
    hrv_delta_pct: number | null;   // last night vs 7d baseline, e.g. -12.3
    sleep_hours: number | null;
    sleep_score: number | null;     // 0-100 (Garmin)
    body_battery: number | null;    // 0-100 morning value
    tsb: number | null;             // training stress balance (ctl - atl)
  };
}

type WorkoutType =
  | "easy_run" | "long_run" | "tempo" | "intervals"
  | "recovery" | "rest" | "cross_train" | "race";

interface PlanDay {
  date: string;
  workout_type: WorkoutType;
  title: string;
  description: string;        // how to execute the workout
  duration_min: number | null;
  distance_km: number | null;
  target_pace: string | null; // "5:30" min/km
  rationale: string;          // WHY this workout / why it changed
  status: "planned" | "completed" | "skipped";
  garmin_workout_id: string | null;
  pushed_at: string | null;   // ISO datetime, null = not on watch
}

interface Activity {
  id: number;                 // Garmin activity id
  date: string;
  type: string;               // "running", ...
  name: string;
  distance_km: number | null;
  duration_min: number | null;
  avg_hr: number | null;
  avg_pace: string | null;    // min/km
  training_load: number | null;
  rpe: number | null;         // user-provided 1-10, null if not rated
}

interface DailyHealth {
  date: string;
  sleep_hours: number | null;
  sleep_score: number | null;
  hrv: number | null;
  hrv_baseline: number | null;
  resting_hr: number | null;
  body_battery: number | null;
  stress_avg: number | null;
}

interface PendingEdit {
  id: number;
  created_at: string;
  summary: string;            // one-line description of the change
  rationale: string;
  changes: PlanDay[];         // the proposed new versions of affected days
  current: PlanDay[];         // current versions of the same days (for diff)
  status: "pending" | "accepted" | "dismissed";
}
```

## Endpoints

- `GET /api/dashboard/today` → `{ date, readiness: Readiness | null, workout: PlanDay | null, health: DailyHealth | null, pending_edit: PendingEdit | null, race: RaceGoal | null, days_to_race: number | null, unrated_activity: Activity | null }`
- `GET /api/plan/week?start=YYYY-MM-DD` → `{ days: PlanDay[] }` (7 days; `start` defaults to today)
- `POST /api/plan/push` body `{ date }` → `{ ok: true, garmin_workout_id }` (push that day's workout to the Garmin calendar/watch)
- `GET /api/trends?days=90` → `{ daily: Array<{ date, hrv, hrv_baseline, resting_hr, sleep_hours, sleep_score, body_battery, ctl, atl, tsb, distance_km, training_load }> }` (nulls where no data)
- `GET /api/activities?limit=20` → `Activity[]` (newest first)
- `POST /api/activities/{id}/rpe` body `{ rating: number (1-10), note?: string }` → `{ ok: true }`
- `GET /api/settings` / `PUT /api/settings` →
  ```ts
  interface Settings {
    race: { name: string; date: string; distance_km: number; goal_time: string } | null; // goal_time "3:45:00"
    athlete: { age: number | null; weekly_km: number | null; notes: string };
    llm_provider: "anthropic" | "openai";
    auto_push_workouts: boolean;
    plan_hour: number; // local hour the daily job runs
  }
  ```
- `POST /api/sync` → `{ ok, synced_through, plan_updated }` — runs Garmin sync + replan now (long: up to ~60s)
- `GET /api/sync/status` → `{ last_run: string | null, last_status: "ok" | "error" | null, last_detail: string | null, running: boolean }`
- `GET /api/edits/pending` → `PendingEdit | null`
- `POST /api/edits/{id}/accept` → `{ ok: true }` (applies to plan, pushes to Garmin if auto-push)
- `POST /api/edits/{id}/dismiss` → `{ ok: true }`

## Chat

- `GET /api/chat/sessions` → `Array<{ id: string, created_at: string, title: string }>`
- `GET /api/chat/history?session_id=` → `Array<{ role: "user" | "assistant", content: string, created_at: string }>`
- `POST /api/chat` body `{ session_id?: string, message: string, context_date?: string }` — **SSE stream** (`Content-Type: text/event-stream`). Events are lines `data: <json>\n\n` with:
  - `{ "type": "session", "session_id": "..." }` (first event)
  - `{ "type": "text", "delta": "..." }` (assistant text tokens)
  - `{ "type": "tool", "name": "get_training_data", "status": "running" | "done" }`
  - `{ "type": "edit_proposed", "edit": PendingEdit }` (render diff card with Accept/Dismiss wired to /api/edits)
  - `{ "type": "done" }` / `{ "type": "error", "message": "..." }`

Chat supports slash shortcuts client-side by just sending the expanded text (e.g. `/week` → "Give me a summary of my week and how my plan is going").

---

# v1.1 additions

## Type changes

```ts
// Activity gains:
interface Activity {
  // ...existing fields...
  cadence: number | null;         // avg steps/min (doubled), easy runs
  temperature_c: number | null;   // at activity start (Garmin or Open-Meteo)
  hr_drift_pct: number | null;    // aerobic decoupling %, first vs second half; <5 is good
  ef: number | null;              // efficiency factor: (m/min) / avg HR
}

// PlanDay: "stale on watch" is derivable — garmin_workout_id != null && pushed_at == null
// means an outdated version is still on the Garmin calendar; show "Changed — resend".

interface DayIntent {
  date: string;
  sport: string;                  // "surfing", "hiking", "freediving", ...
  note: string;
  duration_min: number | null;
  effort: "easy" | "moderate" | "hard" | null;
  source: "manual" | "chat";
}

// Trends daily rows gain: acwr (number|null), vo2max (number|null)
```

## Day intents (other-sport / no-run days)

- `GET /api/intents?start=&end=` → `DayIntent[]`
- `PUT /api/intents/{date}` body `{ sport, note?, duration_min?, effort? }` → `DayIntent` (upsert; the daily replan and chat plan around these — a run is never scheduled on an intent day)
- `DELETE /api/intents/{date}` → `{ ok: true }`

UI: a quick "Other sport" action on Today/Week day cards (small dialog: sport free-text or presets [hiking, surfing, freediving, cycling, climbing], optional duration + effort) and an intent chip on the day card (shown alongside/instead of the run workout, with a remove button). Chat gains a `/sport` slash shortcut expanding to: "I'm doing [sport] on [date] for about [duration]. Set that day accordingly and rebalance my week around it."

## Watch push (manual by default)

`auto_push_workouts` now defaults to **false**. New endpoints:

- `POST /api/plan/push_week` body `{ start?: string }` → `{ ok, pushed: number }` (pushes all pushable, unpushed/stale days in that week)
- `POST /api/plan/unpush` body `{ date }` → `{ ok: true }` (deletes the workout from the Garmin calendar)
- `POST /api/plan/unpush_week` body `{ start?: string }` → `{ ok, removed: number }`

UI: week view header gets "Send week to watch" and "Clear week from watch" buttons; each day card keeps its own push button plus a remove ("×") when pushed; "On watch" badge shows the pushed time (e.g. "On watch · 14:53"); stale days show an amber "Changed — resend" badge.

## Backfill

- `POST /api/backfill` body `{ days: number }` → `{ ok: true, started: true }` (long-running background job)
- `GET /api/sync/status` response gains `backfill: { running: boolean, done_days: number, total_days: number } | null`

UI: on Settings (or near Sync now), a "Backfill history" action with a small progress indicator driven by sync status polling.

## Analytics

- `GET /api/analytics?days=180` →
  ```ts
  {
    ef_series: Array<{            // easy/recovery/long runs only
      date: string; activity_id: number; name: string;
      ef: number; avg_pace: string | null; avg_hr: number | null;
      temperature_c: number | null; hr_drift_pct: number | null;
      cadence: number | null; distance_km: number | null;
    }>;
    zones_weekly: Array<{ week_start: string; z1_s: number; z2_s: number; z3_s: number; z4_s: number; z5_s: number }>;
    vo2max_series: Array<{ date: string; vo2max: number }>;
    race_prediction: { date: string; time_5k_s: number | null; time_10k_s: number | null; time_half_s: number | null; time_marathon_s: number | null } | null;
    goal: { distance_km: number; goal_time_s: number; predicted_time_s: number | null } | null;
  }
  ```

UI — Trends page gains (respecting the existing 30/90/180d range tabs where sensible):
1. **Aerobic efficiency**: EF scatter (one point per easy run) colored by temperature (cool blue → hot red), with a rolling-average trendline. Tooltip: run name, pace, HR, temp, drift.
2. **HR drift**: line/scatter of `hr_drift_pct` per run with a 5% reference line.
3. **Resting HR**: line chart (data already in trends daily rows).
4. **ACWR**: line on/near the load chart with the 0.8–1.3 shaded safe band.
5. **VO2max**: line chart; if `goal` present, a "Race outlook" card comparing predicted vs goal time (e.g. "Predicted 3:52 vs goal 3:45 — 7 min to close").
6. **Time in zones**: weekly stacked bars (z1..z5) with an 80/20 hint (share of z1+z2).

---

# v1.2 additions — multiple races

The single `Settings.race` is replaced by a races list with one primary (existing settings race is auto-migrated into it server-side). `Settings` no longer has a `race` field.

```ts
interface Race {
  id: number;
  name: string;
  date: string;              // YYYY-MM-DD
  distance_km: number;
  goal_time: string;         // "3:45:00" (h:mm:ss or m:ss)
  is_primary: boolean;
  days_to_race: number;      // negative if past
  prediction: {              // from Garmin's race predictor, Riegel-adjusted to this distance
    predicted_time_s: number | null;
    goal_time_s: number | null;
    delta_s: number | null;          // predicted - goal; negative/zero = on track
    predicted_pace: string | null;   // min/km
    goal_pace: string | null;        // min/km
  };
}
```

- `GET /api/races` → `Race[]` (upcoming only, soonest first; `?include_past=true` for all)
- `POST /api/races` body `{ name, date, distance_km, goal_time, is_primary? }` → `Race` (first race ever created becomes primary automatically)
- `PUT /api/races/{id}` body: same fields, all optional → `Race`
- `DELETE /api/races/{id}` → `{ ok: true }` (deleting the primary promotes the next upcoming race)
- `POST /api/races/{id}/primary` → `{ ok: true }` (exactly one primary at a time)

`GET /api/dashboard/today`: the `race` field is now the primary `Race` object (or null); `days_to_race` unchanged. `GET /api/analytics`: `goal` is now derived from the primary race (Riegel-adjusted prediction for its exact distance).

## UI

- **Settings**: replace the single race form with a "Races" manager card: list of upcoming races sorted by date, each row showing name, date (+ countdown), distance, goal time, a **prediction chip** ("Predicted 3:52:10 · +7:10 vs goal" — green when delta ≤ 0, amber/red when behind; em-dash when no prediction yet), a star toggle to set primary (filled star = primary), edit (dialog), and delete. "Add race" button opens the same dialog (name, date, distance presets 5k/10k/half/marathon + custom km, goal time).
- **Today page**: race countdown chip uses the primary race and gains the prediction delta ("42 days · predicted +7:10 vs goal").
- **Trends "Race outlook" card**: shows the primary race; if other upcoming races exist, list them compactly underneath with their own prediction chips.

---

# v1.3 additions — IA rework, tooltips, activities, mobile

## New/changed endpoints

- `GET /api/activities?limit=&offset=` → `Activity[]` (offset added for pagination)
- `GET /api/activities/{id}` → `ActivityDetail`:
  ```ts
  interface ActivityDetail extends Activity {
    rpe_note: string | null;
    time_in_zones: { z1: number; z2: number; z3: number; z4: number; z5: number } | null; // seconds
    max_hr: number | null;
    calories: number | null;
    elevation_gain_m: number | null;
    start_time_local: string | null;   // "2026-07-16 06:12:00"
    plan_day: PlanDay | null;          // what was planned for that date, if anything
  }
  ```
- `GET /api/dashboard/today`: `unrated_activity` is now **only the single most recent run** (within the last 2 days) **and only if it has no RPE yet** — once rated (or if a newer run exists), older unrated runs are never asked about on the home page. They can still be rated from their activity detail page.
- `POST /api/activities/{id}/rpe` unchanged (used by both home prompt and detail page; also allow re-rating).

## Metric explanations (tooltips)

Every chart/stat that shows one of these metrics gets a small ⓘ info trigger (hover popover on desktop, tap-to-open on mobile) with this exact copy — title bolded, then the body:

- **Fitness (CTL)** — "Your 42-day weighted average training load — think engine size. It rises slowly with consistent training and falls when you stop. How to use it: build gradually and let it climb over months; going into your race taper with a higher CTL is what actually makes you faster on race day."
- **Fatigue (ATL)** — "Your 7-day weighted average training load — the stress you're carrying right now. It spikes after big days and fades within a week. How to use it: high ATL is fine and normal in hard weeks, but several high-ATL weeks without recovery days is how overtraining starts."
- **Form (TSB)** — "Fitness minus Fatigue (CTL − ATL). Positive = fresh, negative = fatigued. How to use it: productive training usually happens slightly negative (−10 to −20). Below about −25, injury and illness risk climbs — back off. You want to arrive at race day slightly positive (+5 to +15), which is what the taper is for."
- **ACWR** — "Acute:chronic workload ratio — this week's load divided by your ~monthly norm. How to use it: 0.8–1.3 (the shaded band) is the safe ramp zone. Above ~1.5 you're increasing load faster than your body has adapted to — classic injury territory. Persistently below 0.8 means you're detraining."
- **Aerobic efficiency (EF)** — "Speed per heartbeat on easy runs: meters-per-minute ÷ average HR. How to use it: if EF trends up at the same easy effort over weeks, your aerobic base is genuinely improving — you run faster at the same HR. Compare fairly: heat, hills, and fatigue all depress EF, which is why points are colored by temperature."
- **HR drift** — "How much your heart rate rose in the second half of a run relative to pace (aerobic decoupling). How to use it: under 5% means the run was truly aerobic — your endurance held. Repeatedly above 8–10% on easy runs means the pace is too fast for your current base, or heat/dehydration is interfering. A shrinking drift on long runs is one of the clearest signs your base is building."
- **VO2max** — "Garmin's estimate of your maximal oxygen uptake — the broadest single fitness number. How to use it: it moves slowly, so judge the 3-month trend and ignore daily wiggles. VO2max rising together with EF is strong evidence the training is working; a sustained drop during heavy training can be an early overtraining flag."
- **Readiness** — "Your body's recovery for today, 0-100. It blends overnight HRV against your own baseline, sleep hours and quality, Body Battery, and your training-load balance (TSB) into one number. Green (70+) means go - your body can take quality work; yellow (45-69) means ease off and keep it aerobic; red (under 45) means recover. Treat it as the day's starting point, not a verdict: how you actually feel still gets a vote." (rendered next to the readiness level pill on Today)
- **Execution score** — "How closely you ran the workout that was prescribed, 0-100, measured step by step against each segment's pace or HR target. Green (80+) means you hit the targets, amber (50-79) means you drifted off them, red (under 50) means the run was well off plan. A low score is not a bad run - it often just means the day called for something else, which is useful signal for the coach. Only runs matched to a plan day get scored." (rendered next to the "Execution" label on the score badge)

The same `MetricInfo` component also carries plain-language explanations for the product's day-to-day concepts, shown at first encounter (not "metrics", but the same ⓘ popover so there is one mental model):

- **Niggles** — "A niggle is a small ache or tweak - the early twinge before it becomes a real injury. Logging one tells the coach to ease the plan around it (shorter, easier, or swapped sessions) until you mark it resolved. Severity runs from niggle (minor, keep an eye on it) to pain (moderate, training is affected) to injury (serious, protect it). Report early: the whole point is to catch it while it is still just a niggle." (Niggles card on Today + Settings)
- **RPE (perceived effort)** — "Rate of Perceived Exertion - how hard the run felt to you, from 1 (easy jog) to 10 (all-out). It is your subjective read, and it is worth logging because it catches what the watch cannot: a run that felt awful at an easy heart rate is a fatigue flag, and an easy-feeling hard session means you are fit. The coach weighs your recent RPE alongside the objective data when planning." (RPE scale + read-only Effort card)
- **Plan source** — "Who writes your training plan. 'Follow my Garmin Coach plan' keeps Garmin's plan as the base and has Idaten review it, offering tweaks as proposals you approve - it never silently overwrites Garmin. 'Let Idaten write my whole plan' hands the full 7-day plan to Idaten instead - best if you have no Garmin Coach plan, or you want Idaten fully in charge." (Settings)
- **Training mode** — "How your workout targets are expressed. Pace gives every run a min/km target. Heart rate gives HR-band targets, which self-adjust for heat, hills, and fatigue. Hybrid (recommended) uses HR bands for easy and long runs - where holding the right effort matters more than speed - and pace for quality sessions where you are chasing a specific time." (Settings)

Implement as one shared `MetricInfo` component with a copy map, so the same explanation appears wherever the metric shows up (trends charts, readiness stat tiles' TSB, etc.).

## Trends: grouped into categories

Reorganize the trends page into three sections with a sticky category pill bar (jump links or tab behavior — pick what works best on mobile):

1. **Recovery** — HRV vs baseline, Sleep, Resting HR
2. **Training load** — Load + CTL/ATL, TSB, ACWR, Weekly distance, Time in zones
3. **Progress** — Aerobic efficiency, HR drift, VO2max, Race outlook

## Races menu

Move the Races manager out of Settings into its own top-level page `/races` (nav item "Races", flag or trophy icon): the manager card (add/edit/delete/star) plus the Race outlook content (primary race featured with predicted vs goal, others below). Settings keeps only athlete/provider/plan-hour/auto-push/data sections.

## Activities menu

New top-level page `/activities`: reverse-chronological list (paginated via limit/offset with a "Load more" button), each row: date, name, distance, duration, pace, avg HR, RPE badge (or "unrated"), temperature. Rows link to `/activities/[id]`:
- Header: name, date/time, type badge.
- Stat grid: distance, duration, pace, avg/max HR, cadence, calories, elevation, temperature, training load.
- Time-in-zones horizontal stacked bar (with the zone colors used on trends).
- EF + HR drift stats with their MetricInfo tooltips.
- **Effort section**: the 1–10 RPE tap scale + optional note — shows current rating if rated, allows changing it. (Same component as the home-page prompt.)
- If `plan_day` exists: a small "Planned: <title>" card for comparison.
- "Ask about this run" button → `/chat?prefill=...` referencing the activity name and date.

## Mobile

Make the whole app phone-friendly:
- **Navigation**: on `md+` keep the current sidebar. Below `md`: a fixed bottom tab bar with the 4 primary destinations — Today, Week, Chat, Trends — plus a "More" tab opening a sheet/menu with Races, Activities, Settings (with icons). Ensure content has bottom padding so the tab bar never covers it.
- All pages single-column on mobile; stat grids wrap 2-up; charts full-width with reduced heights; tables/rows stack gracefully; dialogs become bottom sheets or full-width on small screens; tap targets ≥ 40px.
- Chat: input pinned above the bottom nav (or nav hidden on chat while keyboard open), messages scroll correctly on iOS Safari (100dvh, safe-area insets).
- Test by building and reasoning about breakpoints; use Tailwind responsive utilities throughout.

---

# v1.4 additions — auth, multi-user, onboarding, chat fixes

The backend is now multi-user with cookie-session auth.
Every `/api/*` endpoint except `/api/auth/login` returns **401** when not logged in.

## Same-origin proxy (replaces NEXT_PUBLIC_API_URL)

The frontend must call the API on its OWN origin (`/api/...`, relative URLs) so the httpOnly session cookie flows automatically.
Add to `next.config.mjs`:

```js
async rewrites() {
  return [{
    source: "/api/:path*",
    destination: `${process.env.BACKEND_URL || "http://localhost:8000"}/api/:path*`,
  }];
}
```

- Remove all `NEXT_PUBLIC_API_URL` usage from `lib/api.ts` (and the Dockerfile build arg if present); fetch with relative paths and `credentials: "same-origin"` semantics (default).
- In Docker the env `BACKEND_URL=http://backend:8000` is provided at runtime.
- SSE streaming through the rewrite works; keep the existing stream reader.

## Auth endpoints

- `POST /api/auth/login` body `{ username, password }` → `{ ok, user: UserInfo }`; sets the httpOnly cookie. 401 on bad credentials.
- `POST /api/auth/logout` → `{ ok: true }`; clears the cookie.
- `GET /api/auth/me` → `UserInfo` (401 when logged out).
- `POST /api/auth/users` body `{ username, password, display_name? }` → `UserInfo` — add a household member (must be logged in). 409 if the username is taken.
- `POST /api/auth/password` body `{ current_password, new_password }` → `{ ok }` (401 if current is wrong).

```ts
interface UserInfo {
  id: number;
  username: string;
  display_name: string;
  garmin_connected: boolean;
}
```

## Required UI

1. **Login page** at `/login`: username + password, error message on 401, redirect to `/` on success. Clean, centered card, dark/light aware.
2. **Auth guard**: on any API 401, redirect to `/login` (a small helper in `lib/api.ts` is fine). After login, `GET /api/auth/me` powers the user display.
3. **Logout + account section** in Settings (and/or the mobile More sheet): show display_name, a Log out button, a Change password form, and an "Add household member" form (username/password/display name) using `POST /api/auth/users`.
4. **Connect Garmin flow** (Settings): if `me.garmin_connected` is false, show a "Connect Garmin" card with email + password fields posting to `POST /api/garmin/connect` (below). On success show "Connected — your history is loading". Garmin credentials are only ever sent to our own backend.

## Garmin connection + two-stage onboarding

- `POST /api/garmin/connect` body `{ email, password }` → `{ ok, onboarding_started: true }`. 400 with a message when Garmin rejects the login. On success the backend runs a quick 14-day sync (first plan appears in ~1 min) then a 300-day deep backfill in the background.
- `GET /api/sync/status` now returns extra fields:
  ```ts
  {
    last_run, last_status, last_detail, running,
    backfill: { running: boolean, done_days: number, total_days: number } | null,
    garmin_connected: boolean,
  }
  ```
- **Onboarding banner** (all pages, e.g. in the layout): while `backfill.running`, show a dismissable banner: "Loading your Garmin history — {done_days}/{total_days} days synced. Charts fill in as data arrives; check back later." Poll every ~10 s while visible. When `garmin_connected` is false, the dashboard should point the user to Settings → Connect Garmin instead of showing empty states.

## Chat fixes (bugs)

1. **Markdown rendering**: assistant messages must render markdown (bold, lists, headings) in BOTH live streaming and history. Use a small md renderer already in the repo or add `react-markdown`.
2. **History shape changed** — `GET /api/chat/history?session_id=` now returns:
   ```ts
   Array<{
     role: "user" | "assistant";
     kind: "text" | "edit_proposed";
     content: string;               // for kind "text": the markdown message
     created_at: string;
     edit?: PendingEdit;            // present when kind === "edit_proposed"
   }>
   ```
   For `kind: "edit_proposed"`, render the SAME diff card component used live, driven by `edit.status`:
   - `pending` → live card with working Accept / Dismiss buttons;
   - `accepted` / `dismissed` → collapsed receipt ("Plan edit accepted/dismissed: {summary}"), never stale buttons.
3. Paragraph separation between tool rounds is now handled server-side (text deltas include `\n\n`) — no client change needed beyond rendering markdown.

## Removal

- The old `Settings.race` field note and any leftover single "race goal" settings UI should not reappear; races are managed solely on /races (unchanged).

## Changed in v1.4 (late addition)

- `POST /api/sync` is now fire-and-forget: returns `{ ok: true, started: true }` (or `{ ok: true, already_running: true }`) immediately; watch `GET /api/sync/status` for completion. A sync takes longer than the same-origin proxy allows for a single request.
- `UserInfo` gains `garmin_email: string | null`. The Connect Garmin card is now always shown in Settings: connected users see "Connected as {garmin_email}" with an "Update credentials" form; `POST /api/garmin/connect` only starts onboarding (`onboarding_started: true`) for accounts with no synced data — updating credentials on an established account just re-verifies.

---

# v1.5 additions (Phase 2 — training features)

Charting: use the same lightweight chart approach already in the repo (recharts). All new endpoints require auth like everything else.

## 1. Athlete card: auto profile from Garmin

`GET /api/settings` gains a READ-ONLY `athlete_auto` block (ignored by PUT) and a writable `training_mode`:

```ts
interface Settings {
  athlete: { age: number | null; weekly_km: number | null; notes: string }; // only `notes` is edited now
  athlete_auto: {
    age: number | null;              // from Garmin birth date
    gender: string | null;           // "male" | "female"
    weight_kg: number | null;
    height_cm: number | null;
    lthr: number | null;             // lactate threshold HR (bpm)
    vo2max_running: number | null;
    weekly_km_4wk: number | null;    // computed 4-week average from real activities
    updated: string | null;          // date the profile was last synced
  };
  llm_provider: "anthropic" | "openai";
  auto_push_workouts: boolean;
  plan_hour: number;
  training_mode: "pace" | "hr" | "hybrid";   // NEW, default "hybrid"
}
```

**Athlete card rework (Settings):** replace the manual Age and "Typical weekly volume" inputs with read-only rows from `athlete_auto` (age, gender, weight, height, LTHR, VO2max running, weekly volume 4-wk avg) with a subtle "from Garmin" hint; hide null fields. Keep "Notes for the coach" as the ONLY editable athlete field (still saved via `athlete.notes`). If everything in `athlete_auto` is null (profile not synced yet), show a hint that it fills in after the next sync, and keep the manual age field as fallback.

## 2. Training mode

**Settings → Coach behavior**: add a "Training mode" select next to LLM provider — options: Pace (pace targets), Heart rate (HR-band targets), Hybrid (recommended; HR for easy/long runs, pace for quality). Save via the normal settings PUT. One-line helper text under it.

`PlanDay` gains HR band targets (both null unless training mode produces them):

```ts
interface PlanDay {
  // ... existing fields ...
  target_hr_low: number | null;    // bpm
  target_hr_high: number | null;   // bpm
}
```

**Display:** wherever `target_pace` is shown on a plan day (Today card, week list, edit-diff cards), show the HR band when pace is null and the band exists: "HR 140–155" (with a heart icon if one is already in use). A day has pace OR an HR band, never both.

## 3. Activity detail charts + splits

New endpoint `GET /api/activities/{id}/series` (fetches from Garmin and caches on first call — can take a couple of seconds; show chart skeletons; 502 if Garmin is unreachable and nothing is cached):

```ts
interface ActivitySeries {
  series: {
    t_s: number[];                       // elapsed seconds (x-axis)
    distance_m?: (number | null)[];
    hr?: (number | null)[];
    speed_mps?: (number | null)[];       // pace = 1000/speed (sec/km); plot pace inverted (faster = up)
    elevation_m?: (number | null)[];
    cadence_spm?: (number | null)[];
  } | null;                              // null = Garmin has no per-second data for this activity
  splits: Array<{
    index: number;
    distance_m: number | null;
    duration_s: number | null;
    avg_hr: number | null;
    max_hr: number | null;
    avg_speed_mps: number | null;
    avg_pace: string | null;             // "5:30"
    elevation_gain_m: number | null;
    avg_cadence: number | null;
  }> | null;
  hr_zones: { z1: [number, number]; z2: [number, number]; z3: [number, number]; z4: [number, number]; z5: [number, number] } | null; // bpm bands for chart shading
}
```

**Activity detail page additions** (below the existing stat grid):
- Pace-over-time chart (invert y so faster is up; hide when speed series missing).
- HR-over-time chart with soft horizontal zone bands from `hr_zones` (skip bands when null).
- Elevation profile and cadence charts (small, collapsible or secondary).
- Splits table: km | pace | HR | elev gain (per lap; most users autolap at 1 km). Render compactly on mobile.
Charts only make sense for runs; for other activity types render whatever series exist, or nothing.

## 4. Activities list: type filter

- `GET /api/activities` accepts `&type=running` (exact Garmin type key).
- `GET /api/activities/types` → `Array<{ type: string; count: number }>` sorted by count desc.
- **UI:** horizontal filter chips above the activities list ("All" + one chip per type, prettified label e.g. "trail_running" → "Trail running", with count). Selecting a chip refetches with `?type=`.

## 5. Races: one-way Garmin import

Backend now auto-imports races the user created in Garmin Connect during the daily sync. `Race` gains `source`:

```ts
interface Race {
  // ... existing fields ...
  source: "manual" | "garmin";
}
```

- **/races page:** show a small "from Garmin" badge on `source === "garmin"` races, and this note somewhere sensible on the page: "Races you create in Garmin Connect appear here automatically; races created here are not sent back to Garmin."
- Deleting an imported race is allowed (it won't come back); editing one keeps your edits (the import never overwrites).
- No other UI change; primary-race behavior is unchanged from the frontend's perspective.

---

# v1.6 additions (Phase 3 — membership, floating chat, mobile polish)

## 1. Membership: admin + invite links (replaces the add-member form)

`UserInfo` gains `is_admin: boolean`. **`POST /api/auth/users` is REMOVED** — delete the "Add household member" form and its api helper. Accounts are now created only through one-time invite links.

New endpoints:

- `GET /api/auth/members` (any logged-in user) → `Array<UserInfo & { is_me: boolean; created_at: string }>`.
- `POST /api/auth/invites` (admin only, 403 otherwise) → `{ path: "/invite/<token>", expires_at: string }`. Compose the full URL client-side: `window.location.origin + path`. Links are one-time and expire in 7 days.
- `POST /api/auth/users/{id}/reset_link` (admin only) → same shape — a one-time password-reset link for that member.
- `DELETE /api/auth/users/{id}` (admin only; 400 when targeting yourself) → `{ ok: true }`. Deletes the member AND all their data.
- `GET /api/auth/invites/{token}` (PUBLIC, no auth) → `{ valid: false }` or `{ valid: true, kind: "invite" }` or `{ valid: true, kind: "password_reset", username: string }`.
- `POST /api/auth/invites/{token}/accept` (PUBLIC) — for `kind "invite"`: body `{ username, password, display_name? }` (username lowercase `[a-z0-9_.-]{2,32}`, password min 6; 409 = username taken); for `kind "password_reset"`: body `{ password }`. Both → `{ ok, user: UserInfo }` and set the session cookie (user is logged in). 410 = link used/expired.

**Members card (Settings, replaces the add-member section of the account card):**
- List every member: display name, @username, "You" chip, "Admin" chip, small Garmin-connected dot.
- Admin-only actions: an "Invite member" button that calls POST /invites and reveals the full link with a copy button + "One-time link, expires in 7 days — send it over any messenger"; per-member (not self): "Reset password" (same link-reveal pattern) and "Remove…" (confirmation dialog that states ALL their data will be deleted).
- Non-admins see the list only, plus a hint that the admin manages membership.

**Invite page `/invite/[token]` (PUBLIC — must render without a session; ensure the 401-redirect helper isn't triggered here):**
- On load call GET /api/auth/invites/{token}. Invalid → friendly "This link has expired or was already used" card.
- `kind "invite"` → welcome card ("You've been invited to join the household") with username / display name / password fields → accept → redirect to `/` (they land logged in; the dashboard will point them to Connect Garmin).
- `kind "password_reset"` → "Set a new password for @{username}" with one password field → accept → redirect to `/`.
- Same centered-card visual language as /login.

## 2. Floating chat bubble/panel (locked decision #8)

- Floating bubble bottom-right on every authed page. Desktop: opens a docked panel (~400px wide, ~min(640px, 80vh) tall, above the bubble). Mobile: full-screen sheet; the bubble sits above the bottom tab bar.
- Chat LEAVES the tab bar → 4 tabs: Today, Week, Trends, More. Keep the `/chat` route working (full-page chat + session history/deep links); the panel and page share the same session.
- Stream and session state MUST survive closing/reopening the panel and navigating between pages: lift chat state into a provider/store mounted once in the app shell (closing hides the panel; it does not unmount mid-stream state). If a reply finishes while the panel is closed, show a small unread dot on the bubble.
- The pending-edit diff card, markdown rendering, and SSE handling are the same components as /chat — reuse, don't fork.

## 3. Mobile polish wave (locked decision #9 + known bugs)

- **Races card**: stacked layout on small screens (name/date block above prediction stats, full-width; no horizontal cramming).
- **Activity detail stat grid**: audit for dangling last tiles — grid should keep even columns (e.g. 2-col on mobile, 3/4 on wider) without a lone tile stretching oddly.
- **Bottom tab bar refresh**: translucent blur background (`backdrop-blur` + semi-transparent bg), filled icon variant for the active tab (outline for inactive), and hide-on-scroll-down / reveal-on-scroll-up behavior. Respect safe-area insets. The floating chat bubble must stay clear of it.

---

# v1.7 additions (Phase 4 — tutorial, chat limits, coach style)

## 1. Settings: coach style + tutorial flag

`Settings` gains two writable fields (normal GET/PUT):

```ts
interface Settings {
  // ... existing fields ...
  coach_style: "default" | "chill" | "strict";  // default "default"
  tutorial_done: boolean;                        // default false
}
```

**Coach style select (Settings → Coach behavior, next to Training mode):** options — "Default" (balanced, cites your numbers), "Chill" (plain language, no jargon, encouraging), "Strict" (blunt, holds you accountable). One-line helper: "Changes the coach's tone in chat and plan rationales — never its safety judgment."

## 2. Chat rate limits (backend-enforced)

`POST /api/chat` can now return BEFORE the SSE stream starts:
- `400` — message over 2000 characters.
- `429` — non-admin quota hit (5 messages / 5 min, 15 / day) or a previous reply is still streaming. The `detail` field is a friendly, user-ready sentence.

**UI:** when the chat POST fails with 400/429, render `detail` as an inline assistant-style notice bubble in the thread (muted style, no retry spinner) and re-enable the composer. Do NOT treat it as a hard error toast. Admins are exempt from the counts; no UI needed for that distinction beyond the error simply not happening.

## 3. First-run tutorial (frontend-only, modal carousel)

A centered modal carousel, 5 steps, one icon + heading + 2 short sentences each. NOT a spotlight/anchor tour. Steps:
1. **Welcome** — "Your coach syncs Garmin nightly and keeps a rolling 7-day plan pointed at your race."
2. **Connect Garmin** — button "Take me there" → `/settings` (this step auto-skips its CTA if `me.garmin_connected`; still show the card explaining sync).
3. **Today** — readiness score + today's workout and the why behind it. CTA → `/`.
4. **Your week** — the 7-day plan; push any run to your watch. CTA → week view.
5. **Chat with your coach** — the bubble, bottom right; plan changes always wait for your approval. Final button: "Done".

Behavior:
- Auto-open once when `settings.tutorial_done === false` after login (fetch settings in the shell or on the dashboard; only for authed pages).
- Any dismissal (X, backdrop, Done) sets `tutorial_done: true` via the settings PUT — it never auto-opens again.
- Replay: a "Show tutorial" item in Settings (near the account card) AND in the mobile More sheet reopens the same carousel (replay does not re-write the flag; it's already true).
- "Take me there" navigates and CLOSES the modal but does not end the tutorial permanently mid-flow unless dismissed; simplest compliant behavior: navigating counts as dismissal (flag set) — acceptable.
- Dots/step indicator + back/next; swipe on mobile if trivial to add, otherwise buttons only.

---

# v1.8 additions (Phase 5 — setup wizard, coach personas, getting-started checklist)

Replaces the v1.7 modal-carousel tutorial entirely (delete that component). The tutorial is now a real setup wizard where the user DOES the setup, not a slideshow about it.

## 1. New endpoint: update own profile

```
POST /api/auth/profile   body: { display_name: string }   → the standard user object (same shape as /auth/me)
```
- 1-40 chars after trim; 422 otherwise. Only affects the current session's user.

## 2. Coach personas (frontend naming layer over coach_style)

The three `coach_style` values get names, portraits, and taglines. The API is unchanged — `coach_style` still stores `"default" | "chill" | "strict"`; personas are a presentation concept:

| Persona | style value | Tagline | Flavor disclosure line |
|---|---|---|---|
| **Coach Sam** | `default` | "Balanced and data-driven." | "A balanced mix of workouts, always grounded in your numbers." |
| **Coach Koa** | `chill` | "Zero jargon, all good vibes." | "Expect fartleks, relaxed progressions, and plain-language advice." |
| **Coach Viktoria** | `strict` | "No excuses — but never past your limits." | "Expect track intervals and tempo blocks. Recovery rules still always win." |

- **Portraits** (v1.8.1, supersedes the SVG spec): Will-provided illustration PNGs, source art in `/images`, cropped variants committed to `frontend/public/coaches/` — `{sam,koa,viktoria}-full.png` (full pose, 16:17, shown in the wizard) and `{sam,koa,viktoria}-head.png` (square head crop, round avatar in Settings). Served locally from /public — still no external assets. One shared `PersonaCard` component (portrait, name, tagline, flavor line, selected ring) with `variant: "full" | "head"`; selected-ring palettes match the art (Sam sky, Koa orange, Viktoria purple).
- Used in TWO places: wizard step 3, and Settings (replace the v1.7 coach-style `<select>` with the three cards in a row / stacked on mobile). Keep the safety helper line: "Personas change tone and workout flavor — never safety judgment."

## 3. Setup wizard — full-screen `/welcome` route (authed)

A full-screen multi-step flow (progress dots, Back, and per-step Skip where noted). Steps embed the REAL forms — completing a step performs the real API call immediately:

1. **Welcome + name** — greeting, one input prefilled with current `display_name`, saved via `POST /api/auth/profile` on Next. Copy: this app syncs your Garmin nightly and keeps a rolling 7-day plan pointed at your race.
2. **Connect Garmin** — the actual connect form (email + password → `POST /api/garmin/connect`), live verify states (connecting / success / error with message), and after success show onboarding progress from `GET /api/sync/status` (the same quick-sync-then-backfill banner logic Settings uses — reuse the component). If `me.garmin_connected` already: show a "✓ Connected as {garmin_email}" state instead of the form. Skippable ("I'll do this later").
3. **Choose your coach** — the three `PersonaCard`s; picking one PUTs `{coach_style}` immediately. Preselect current value.
4. **Your race (optional)** — minimal add-race form (name, date, distance km, optional goal time) → `POST /api/races`; note underneath: "Races on your Garmin calendar import automatically on sync." If upcoming races already exist, list them instead of the form. Skippable.
5. **Find your way around** — interactive mini-map instead of prose: a stylized app-frame graphic with the 4 tabs + chat bubble; tapping/hovering each highlights it and shows a one-liner (Today = readiness + today's run and why · Week = 7-day plan, push to watch · Trends = fitness over time · More = races, activities, settings · Chat bubble = your coach; plan changes always wait for your approval). Final button: **"Go to Today"** → sets `tutorial_done: true` via settings PUT, navigates to `/`.

Behavior:
- After login or invite-accept, if `settings.tutorial_done === false` → redirect to `/welcome` (authed pages only; don't loop if already there).
- Leaving mid-wizard is allowed (it's a normal route); steps already completed have already saved. The redirect keeps bringing them back until step 5 sets the flag — but only on fresh navigations to `/`, not as a trap (no blocking of other routes).
- **Replay mode**: "Show tutorial" (mobile More sheet + Settings) navigates to `/welcome?replay=1` — identical wizard, prefilled with current values, all steps skippable, does NOT re-write `tutorial_done`, and the final button just goes home. Non-destructive: replaying never clears anything.

## 4. Dashboard "Getting started" checklist card

On the Today dashboard, above the readiness card, show a compact checklist card until complete:
- ✓/○ **Connect Garmin** (`me.garmin_connected`) → deep-link `/welcome` step 2 (or `/settings`)
- ✓/○ **Meet your coach** (done when `tutorial_done` is true — finishing the wizard counts) → `/welcome?replay=1`
- ✓/○ **Add a race** (any upcoming race exists — races come with the dashboard/races fetch) → `/races`

Card disappears entirely when all three are ✓. Small, dismissible is NOT needed (completion is the dismissal).

---

# v1.9 additions (Phase 6 — structured multi-step workouts)

## 1. PlanDay gains `steps`

Every plan-day payload (`/dashboard/today`, `/plan/week`, pending-edit `changes`/`current`, chat plan tools) now includes:

```ts
type StepKind = "warmup" | "work" | "recovery" | "cooldown" | "rest";

interface WorkoutStep {
  kind: StepKind;
  duration_min: number | null;   // exactly one of duration/distance normally set
  distance_km: number | null;
  target_pace: string | null;    // "M:SS" min/km
  target_hr_low: number | null;  // bpm band (per training mode; never both pace+HR)
  target_hr_high: number | null;
  note: string;                  // short cue, e.g. "controlled, not all-out"
}

interface StepBlock {
  repeat: number;                // 1 = plain step(s); >1 = repeat block (e.g. 6× ...)
  steps: WorkoutStep[];          // inside a repeat: e.g. [800m work, 400m float]
}

interface PlanDay {
  // ... existing fields ...
  steps: StepBlock[] | null;     // null = simple single-block workout (render as today)
}
```

## 2. Rendering

- **Today card (expanded)**: when `steps` is set, render the structure as a vertical step list: each block a row; repeat blocks prefixed "6×" with their inner steps indented/grouped visually. Per-step chips for the target (pace `4:45/km` or HR `148–158 bpm`) and the end condition (`800 m` / `12 min`). Keep the day-level description above it as the coach's execution notes.
- **Week view**: one-line compact summary per structured day, built client-side, e.g. `WU 15' · 6×(800m @ 4:45 + 400m float) · CD 10'` (warmup→WU, cooldown→CD, minutes→'). Truncate gracefully on mobile. Simple days (steps null) unchanged.
- **Pending-edit diff cards**: if a changed day's `steps` differ, show the compact one-line summary form (old vs new); no need for a full step-by-step diff.
- Shared helper for the compact summary string — write once, use in week view + diff cards.

## 3. Watch push (informational)

Structured days push to Garmin as real multi-step workouts (repeat groups included) — no UI change beyond what exists; the same push/stale/unpush buttons apply.

---

# v1.10 additions (UX batch — honest sync, coach presence, fixes)

## 1. API changes

- **`PUT /api/settings` now returns the same shape as GET** (settings + `athlete_auto`). The settings page may safely replace its whole state with the PUT response (this fixes the "Cannot read properties of undefined (reading 'age')" crash on save).
- **`POST /api/sync` is now DATA-ONLY**: Garmin pull + enrichment, no plan regeneration, no LLM call. Response shape unchanged. Sync-button copy should say "Sync" / success toast "Data synced" — never imply the plan updates.

## 2. Sync button placement + resilience

- **Today**: keeps the sync button.
- **Week**: REMOVE the sync button — replaced by the coach-review shortcut (below).
- **Activities** and Settings: unchanged.
- **Resume from server state**: on mount, the sync button checks `GET /api/sync/status`; if `running` is true it shows its spinning/"Syncing…" state and resumes polling until done. (Currently the spinner is component-local, so navigating away and back loses a running sync.)

## 3. "Ask your coach" chat shortcut

- Where Week's sync button was: a button labeled **"Ask {coach first name}"** (e.g. "Ask Koa") with the coach's head avatar (small, round).
- Clicking opens the floating chat panel with the composer PREFILLED (not auto-sent): `"I just synced new data — review my week and update the plan if needed."` The user presses send themselves; normal chat flow (rate limits, tools, approval-gated edits) applies.
- Implement via the ChatProvider: an `openWithDraft(text)` action that opens the panel and sets the composer draft (do not overwrite a non-empty draft the user already typed — append instead is fine, simplest: only prefill when composer is empty).
- Today: a smaller text-link version of the same shortcut inside the coach note (below).

## 4. Coach presence (uses PERSONAS + settings.coach_style)

- **Floating chat bubble**: replace the generic icon with the selected coach's head avatar (`headSrc`), full-bleed round crop; keep the unread dot. Coach switch in Settings updates it on next settings fetch (same-session immediacy is a bonus, not required).
- **Chat panel + /chat page header**: coach avatar + "Coach {Name}" as the title (falls back to "Coach" if settings not loaded).
- **Assistant messages** (panel AND full-page chat): small round coach avatar beside each assistant message group. User messages unchanged.
- **Today page coach note**: the expanded workout card's rationale becomes a "coach note" — coach head avatar + "Coach {Name}" label above the rationale text, plus the "Ask {Name}" text-link (see §3) that opens chat prefilled with `"Question about today's workout: "`. Visual: keep it subtle (muted card/quote styling), not a hero banner.

## 5. Persona picker: optimistic selection

- In BOTH the wizard step 3 and Settings: selecting a persona highlights it INSTANTLY (local state), the settings PUT fires in the background, and on failure the selection reverts with an inline error. Never disable/gray the cards while saving (the current disabled-while-saving flash reads as a glitch on slow connections).

## 6. Default light theme

- `ThemeProvider defaultTheme="light"` (was "system"). Keep `enableSystem` off OR retain the user's explicit choice if a theme toggle exists; if no toggle exists, simply default to light.

---

# v1.11 additions (Idaten rename + honest chat + settings reorg + coach pointers)

## 1. Branding — the app is now "Idaten"

- Replace "Garmin Bot" in ALL user-visible copy: layout metadata title, sidebar wordmark, login card title, wizard welcome title ("Welcome to Idaten"). Also rename `package.json` name to `idaten-frontend`.
- The word **"household" must not appear anywhere user-visible**:
  - Login subtitle: "Sign in to your household account" → "Sign in to Idaten".
  - Invite page: "You've been invited to join the household" → "You've been invited to Idaten"; "Ask your household admin for a fresh one" → "Ask the person who invited you for a fresh one".
  - Members card: "Everyone in the household — …" → "Everyone on Idaten — each with their own login, Garmin connection, and plan"; "Membership is managed by the household admin — …" → "Membership is managed by the admin — ask them for invites or password resets."

## 2. Scrub "backfill" from user-facing copy

Internal identifiers and API fields stay; only visible words change (Settings data card):

- Button "Backfill history" → "Load older history".
- Toast "Backfill started" → "Loading older history…"; "Backfill failed to start — is the backend running?" → "Couldn't start loading history — is the backend running?".
- Status "Backfilling… X/Y days" → "Loading older history — X/Y days"; "Last backfill: X/Y days" → "History loaded: X/Y days".

## 3. Chat — honest slash shortcuts (API change)

- `POST /api/chat` now expands shortcuts **server-side**. The client MUST send the raw text the user typed — delete the client-side `SLASH_SHORTCUTS` prompt expansion in chat-provider.
- Persisted user messages get `kind: "shortcut"` when the message matched a command; `content` is the raw typed text. `GET /api/chat/history` returns this. Render user messages with kind `"shortcut"` as a command chip (compact monospace pill) instead of a normal bubble, in BOTH live thread and history.
- Server-side commands (all accept optional trailing detail text, e.g. `/sport surfing saturday ~90min`): `/week`, `/replan`, `/race-plan`, `/sport`.
- Slash menu: keep commands + hints only (no prompt bodies). Selecting a command inserts the command itself plus a trailing space (user may add details); hints should encourage that for `/sport` ("add what/when, e.g. /sport surfing saturday").
- The `context_date` prefix also moved server-side — keep sending `context_date`, but the message body stays exactly what the user typed.

## 4. Chat — `/help` (client-side only)

- Intercept `/help` (case-insensitive) before sending: render a local non-persisted "help" thread item (no API call, no rate-limit spend). Content: the shortcut list with one-line descriptions, a short "what your coach can do" paragraph (grounded answers from your Garmin data, plan edits you approve before they apply, day intents for other sports), and a note that a streaming reply can be stopped with the stop button.
- `/help` appears in the slash menu.

## 5. Chat — stop button (new endpoint + new SSE event)

- New endpoint: `POST /api/chat/stop` → `{ok: true, stopping: boolean}` — asks the server to stop the current stream (`stopping: false` means nothing was streaming).
- New terminal SSE event: `{"type": "stopped"}` (alongside `done`/`error`). On receipt: end the streaming state and append a subtle muted "— stopped" marker under the partial assistant text.
- UI: while a reply streams, the send button becomes a stop button (square icon). Clicking it calls `POST /api/chat/stop` and **keeps reading the stream** until `stopped`/`done`/`error` arrives (do NOT abort the fetch — the server persists the partial reply and confirms with the event).
- History reload: stopped partials come back as normal text messages — no special rendering required.

## 6. Chat — placeholders replace prefilled drafts

- Remove `openWithDraft` prefills entirely; nothing may pre-type a message into the composer. Add `openWithPlaceholder(text)` on ChatProvider: opens the panel and sets a transient composer placeholder (cleared back to the default when the panel closes or a message is sent). Never touches the input value.
- Week "Ask {coach}" button → placeholder: `Ask {Coach first name} to review your week, or request plan changes…`.
- Today coach-note "Ask {name}" link → placeholder: `Ask about today's workout…` (keep passing `context_date`).
- Workout-card footer "Ask about this workout" link: drop the `prefill` query param (raw message must be user-typed); keep the date/context param and apply the same placeholder on the /chat page.
- Default composer placeholder: `Ask {Coach first name} anything — your plan, a workout, a change… (/ for shortcuts)`, falling back to "your coach" when settings aren't loaded.

## 7. Settings — LLM provider is admin-only (API change)

- `GET`/`PUT /api/settings` now **omit `llm_provider` for non-admin users**, and PUT silently ignores it from non-admins. Type change: `Settings.llm_provider` becomes optional (`llm_provider?: string`).
- Render the provider select only when `me.is_admin` (and the key is present).

## 8. Settings page reorg

New card order (top → bottom):

1. **"Your coach"** — persona picker + training mode select + "Notes for the coach" textarea (moved out of the Athlete card). Anchor id `coach` so other surfaces can deep-link (`/settings#coach`).
2. **Athlete** — the read-only from-Garmin block (unchanged fields, minus the notes textarea).
3. **Garmin connection** (existing ConnectGarminCard).
4. **Data** — the load-older-history card (§2 copy).
5. **Members** (unchanged behavior).
6. **Account & advanced** — display name, change password, "Show tutorial" replay, theme toggle if present, plan hour, auto-push toggle, **LLM provider (admin-only, §7)**, logout.

Also: in the mobile **More sheet**, the Settings entry that relates to the coach should show the selected coach's head avatar + "Coach {Name}" and deep-link to `/settings#coach` (adds coach presence for zero new nav).

## 9. First-run coach pointers (`page_hints_seen`)

- Settings shape gains `page_hints_seen: string[]` (GET and PUT; page ids whose pointer was dismissed).
- New `CoachHint` component: an inline callout at the top of the page content — coach head avatar + coach name + ONE persona-voiced sentence + a "Got it" dismiss button. Visual: same subtle muted styling as the Today coach note; NOT a modal, NOT an anchored overlay.
- Pages + ids: `week`, `trends`, `races`, `activities`. Show only when settings are loaded AND `tutorial_done === true` AND the id is not in `page_hints_seen`. (Today gets no hint — the getting-started checklist covers it.)
- Dismiss = refetch-before-write merge: GET settings, PUT with the union of current `page_hints_seen` + the id (same anti-clobber pattern as `tutorial_done`).
- Copy: write 3 personas × 4 pages, one sentence each (≤ ~120 chars), in-voice: Sam balanced/data-driven, Koa chill plain-language, Viktoria strict but caring. Each sentence should tell the user what the page is for / one way to use it.

---

# v1.12 additions (QoL batch — activity icons, day-range filter, About page)

## 1. `GET /api/activities` accepts `&days=`

- Optional `days: int` query param: only return activities dated within the last N days (`date >= today - days`).
Omitted or 0 = full history (unchanged behavior).
Combines with the existing `type` and `limit`/`offset` params.
- Frontend `api.activities(limit, offset, type?, days?)` gains the fourth param.

## 2. Activities page — day-range tabs + type icons

- PageHeader actions: a `Tabs` range picker `30d / 90d / 180d / All` (same pattern as Trends), default **All**.
Changing range resets pagination; "Load more" keeps the selected range.
- Each activity row gets a leading round icon chip identifying its type (new `components/activity-icon.tsx`: exact Garmin typeKey map + substring fallbacks — running→Footprints, trail→MountainSnow, treadmill/indoor→Gauge, walking/yoga→PersonStanding, hiking→Mountain, cycling→Bike, swim/surf→Waves, strength/fitness→Dumbbell, indoor_cardio→HeartPulse, hiit→Flame, snow/ski→Snowflake, else Activity).
- The activity detail header reuses the same icon chip and now shows the prettified type ("Treadmill running", not `treadmill_running`); `prettyType` moved to `lib/utils`.
- Empty-state copy when a type or range filter matches nothing: "No activities match this filter."

## 3. `/about` page

- New static page: what Idaten is (personal AI running coach on Garmin data, approval-gated plan edits) and why the name (韋駄天, the swift guardian deity; 韋駄天走り = "running like the wind").
- Nav: desktop sidebar gains an "About" entry (Info icon, below Settings); mobile More sheet gains "About Idaten" (Info icon).

## 4. Mobile compatibility pass (UI only, no API changes)

- `Input`/`Textarea`/`Select` base font is now `text-base sm:text-sm` — fonts under 16px make iOS Safari zoom the page when an input is focused.
Overrides that force a smaller size on mobile are forbidden for the same reason (the invite-link input is `text-base sm:text-xs`).
- Toasts render above the mobile tab bar (`bottom-[calc(4.5rem+env(safe-area-inset-bottom))]`, right-aligned, `max-w-full`) and keep the desktop corner position from `md:` up.
- Touch targets: `Button size="icon"` is 44px on phones (`h-11 w-11 md:h-9 md:w-9`); the chat-panel header buttons and the RPE scale buttons follow the same phone-first sizing; the workout chip's "remove from watch" X gained padding (`p-2 -my-1.5`) without inflating the chip.

## 5. Chat stream lock — zombie-proofing (bug fix)

Field incident: a member's SSE reply broke mid-stream over the Cloudflare tunnel; the backend turn froze on the dead connection and the in-memory one-stream-per-user lock was held indefinitely — every later send got the "coach is still answering" 429 until a process restart.

- `rate_limit` stream slots are now generation-tokens with a TTL (`STREAM_TTL_S = 300`): `acquire_stream` returns a `gen`, and a holder older than the TTL — or one whose stop was already requested — is cancelled and its slot taken immediately. Cancellation is generation-scoped so a stale stop can never kill a newer stream.
- `POST /api/chat` releases the slot if anything fails between acquire and stream start.
- Frontend: the one-stream-conflict 429 notice bubble now carries `canStop` and renders an inline "Stop that reply now" action wired to `POST /api/chat/stop` (the composer's stop button is invisible when the stuck stream belongs to a dropped connection or another tab). After a successful stop the notice flips to "Stopped — send your message again."

## 6. Mobile More sheet — Settings entry restored

The v1.11 "coach presence" decision replaced the Settings label with the coach's name, leaving mobile with no visible "Settings" at all.
The coach entry ("{Coach name}" + head avatar → `/settings#coach`) is now its own item at the top of the sheet, and Settings renders as a normal gear-icon entry again.

# v1.13 additions — grounded plans, proposal supersession, streaming fix, training phases

## 1. Pace grounding (planner + chat)

Field incident: a new member's first generated week prescribed 5:20-6:00/km paces against actual easy runs of 7:15-8:30/km — the model admitted it was guessing.
Every prescribed pace is now anchored to observed data.

- New `metrics.pace_profile(db, user_id, today)`: whole-run average paces from the last 90 days of runs (>= 2 km, type contains "running").
Returns `{runs_last_90d, typical_pace (median), fastest_avg_pace, slowest_avg_pace, typical_pace_s, fastest_avg_pace_s}`, or null under 3 qualifying runs.
- The planner snapshot gains `recent_pace_profile`, and each snapshot race now carries `goal_pace`, `predicted_time_s`, `predicted_pace` (Riegel from Garmin's race predictor) so plans are grounded in BOTH recent data and the race goal.
- The chat system prompt gains the same profile plus explicit grounding rules.
- Deterministic pace guard (`planner.pace_violations`): easy/recovery/long day targets may not be >7% faster than `typical_pace`; any day target may not be >10% faster than `fastest_avg_pace`.
  - Daily generation: one corrective retry with the violations quoted; still-violating plans are logged.
  - `propose_plan_edit`: violating proposals are REJECTED before creation — the tool returns the violations and the profile so the model re-proposes grounded paces.

## 2. Pending-proposal supersession

- A new proposal now marks older pending edits `superseded` (previously `dismissed`), a fourth `PendingEdit.status` value.
- `POST /api/edits/{id}/accept|dismiss` on a non-pending edit returns **409** with a human sentence saying what happened ("superseded by a newer one", "already accepted", ...) instead of 404.
- Frontend: when an `edit_proposed` SSE event arrives, older pending proposal cards in the live thread flip to superseded (history reloads already hydrate current status); the card renders "Superseded by a newer proposal" and, on a 409, adopts the server's verdict instead of showing a generic error.

## 3. Chat streaming actually streams (bug fix)

The backend always streamed token-by-token, but Next.js's built-in gzip compressed `text/event-stream` responses whenever the client advertised `Accept-Encoding: gzip` (cloudflared always does) — deltas sat in the gzip buffer until the turn ended, so phones saw the whole reply flush at once.
`compress: false` in `next.config.mjs`; Cloudflare still compresses static assets at the edge.
Verified through the tunnel: 9 incremental chunks vs 1 before.

## 4. Week page — "Ask {coach} to adjust this week"

The Week page chat button is now labeled "Ask {coach} to adjust this week" and pre-types `/replan ` into the composer via the new `useChat().openWithDraft(text)` (the user still reviews and presses send — no auto-submit).

## 5. Training phases + Garmin Coach plan mirror

- New table `training_plans` (one row per user): the user's ACTIVE Garmin Run Coach adaptive plan, mirrored read-only during every sync (`garmin/training_plan.py`).
Stores the phase timeline (BASE/BUILD/PEAK/TAPER/TARGET_EVENT_DAY → base/build/peak/taper/race), duration, and a ±14-day window of scheduled Garmin workouts (`weekId` is 0-indexed Monday-aligned; payloads expose 1-indexed weeks).
Row is deleted when Garmin no longer has an active plan.
- New `GET /api/training-plan` → `{source: "garmin"|"derived", name, start_date, end_date, total_weeks, current_week, phase, phases[], upcoming_tasks[]}`, or null.
Garmin plan when mirrored (its week numbering is ground truth — an athlete 8 weeks in is never shown week 1); otherwise a timeline derived from the primary race with the `phase_for` boundaries; null with neither.
- Planner: `training_phase` comes from the Garmin plan when present (race day maps to taper for the library); snapshot gains `garmin_coach_plan` `{name, current_week, total_weeks, phase, race_date, scheduled_workouts}` with a prompt rule to align with — not fight — Garmin's progression.
The chat system prompt gets the same context.
- Frontend: Races page gains a "Training phases" card (proportional phase bar, today marker, week X of Y, per-phase date legend, "from Garmin Coach" / "estimated from race date" badge); the Week page title gains a phase chip ("Base · Week 8 of 25").
New `components/training-phases-card.tsx` (`TrainingPhasesCard`, `PhaseChip`, `usePlanInfo`), `api.trainingPlan()`, `TrainingPlanInfo` types.
- Open product decision (deliberately NOT built): when a Garmin Coach plan is active, Idaten still generates its own week — mirroring Garmin's plan as the base plan (and suppressing our generation/auto-push) is a follow-up decision.

# v1.14 additions — daily review (editor above the DSW)

Idaten becomes an EDITOR of an active Garmin Coach plan rather than a competing author. See ROADMAP "DECIDED — Idaten as editor above the DSW".

## New type

```ts
interface DailyReview {
  date: string;
  state: "pending_data" | "done_full" | "done_structural";
  mode: "editor" | "author" | null;
  coach_note: string;         // persona-voiced daily message; "" until reviewed
  coach: string | null;       // coach_style key that WROTE the note (see coach-attribution entry below); null on pre-feature rows
  proposal_id: number | null; // the PendingEdit this review raised, if any
}
```

## New endpoints

- `GET /api/dashboard/review` → `{ review: DailyReview | null, data_ready: boolean }`.
Cheap, no-LLM. `data_ready` is whether today's sleep/HRV row has synced. The Today page paints the base plan, then polls this.
- `POST /api/dashboard/evaluate` `{ allow_structural?: boolean }` → `DailyReview`.
The lazy first-login trigger for the ONE daily LLM review. Idempotent per day via `DailyReview.state`: a completed review returns cached with NO new call. With no data yet and `allow_structural` false, records `pending_data` and spends nothing; the degraded "Review with recent training instead" button sends `allow_structural: true` for a structural-only review.

## Behavior / model

- New table `daily_reviews` (PK `(user_id, date)`): the review artifact — state machine, `coach_note`, and `proposal_id` → `pending_edits`.
- New setting `plan_authoring: "auto" | "author"` (default `auto`): auto = editor when a Garmin plan is active, else author; `author` forces full authoring even with a Garmin plan.
- Scheduled job no longer calls the LLM: it syncs data and, for editor users, materializes the Garmin coach `taskList` into `plan_days` as the base (override-safe — never overwrites a user-accepted edit). The daily review (`evaluate_today`) is lazy, triggered by the Today page.
- Editor review: coach_note (always) + optional superseding `PendingEdit` when the data warrants (readiness red-flag on a hard day, hard-day clustering via structural signals). Author review: writes the week via the planner + a coach_note.

## UI

- Shared `components/coach-note.tsx` (`CoachNote`): the coach's avatar + name + message, embedded. Replaces the Week page's lightbulb-next-to-rationale; used by the Today workout card, the Week day rows (collapsible), and the daily review note.
- `components/daily-coach-note.tsx` (`DailyCoachNote`) on Today: progressive render — base plan shows instantly, the coach note fills in after the lazy review; three states (waiting-for-data with an honest line + degraded button, evaluating shimmer, done). A surfaced proposal refetches the dashboard so the existing `EditProposalCard` shows.
- In editor mode most Week days carry no rationale (Garmin authored them, Idaten didn't touch them), so the week is clean by construction.

# v1.15 additions — Garmin RPE/feel/body-battery import, coach-mode label, revert-to-Garmin

## Feature 1 — imported effort data

`Activity` (and `ActivityDetail`) gain three fields, populated from Garmin per activity:

```ts
garmin_rpe: number | null;          // RPE logged on the watch/app (1-10). Garmin stores it x10.
feel: number | null;                // "How did you feel?" (1-5: Very Weak/Weak/Normal/Strong/Very Strong)
body_battery_change: number | null; // Body Battery delta over the activity (e.g. -5)
```

- `body_battery_change` comes from the activity summary (no extra Garmin call); `garmin_rpe`/`feel` come from the per-activity detail (`get_activity().summaryDTO`). All three are `null` when the athlete didn't log them.
- `garmin_rpe`/`feel` are SEPARATE from the in-app `rpe`/`rpe_note` (provenance: watch vs in-app). In-app `rpe` still wins when both exist.
- `GET /api/dashboard/today`: `unrated_activity` is now null when the latest run has EITHER an in-app `rpe` OR a `garmin_rpe` — the home RPE prompt no longer appears when Garmin already logged effort. Re-rating from the detail page is unchanged.
- The activity detail "Effort" card reflects the Garmin-logged RPE/feel ("Logged on your watch: RPE 3/10, felt Normal. Tap to override."); Body Battery change shows as a stat tile.
- Backfill: `enrich.backfill_rpe_feel_bb(db, user_id, garmin, days=30)` — one-shot, last 30 days only (no 300-day backfill).

## Feature 2 — coach-mode label

- `GET /api/dashboard/today` and `GET /api/plan/week` now include `mode: "editor" | "author"`.
- `editor` = following a Garmin Coach plan (Idaten reviews + tweaks); `author` = Idaten writes the whole plan.
- UI: `components/coach-mode-badge.tsx` (`CoachModeBadge`) — a pill next to the phase chip on Today + Week. Editor → "Following Garmin Coach"; author → "Following {persona.name}" (Coach Sam/Koa/Viktoria). Hover/tap shows a tooltip explaining the difference with a link to Settings → Plan source.

## Feature 3 — revert an Idaten edit to the original Garmin Coach workout

- `PlanDay` gains `revertible?: boolean` on the `/dashboard/today` (`workout`) and `/plan/week` (`days[]`) payloads: true only in editor mode on a planned day carrying an Idaten/hand override. Absent/false = untouched Garmin base or author mode.
- `POST /api/dashboard/revert-to-garmin` body `{ scope: "day" | "week", date?: "YYYY-MM-DD", start?: "YYYY-MM-DD" }` → `{ reverted: string[] }` (the dates restored).
  - `scope: "day"` requires `date`; `scope: "week"` reverts every edited day in the 7-day window (`start` defaults to today).
  - Restores the mirrored Garmin coach workout, drops the Idaten rationale, and CLEARS Idaten's pushed watch workout (the native Garmin Coach workout stands — no re-push). Committed other-sport (intent) days are preserved; completed/skipped days are left untouched. Returns 400 in author mode (no Garmin base).
- UI: `components/revert-button.tsx` (`RevertButton`) per revertible day on Today + Week; a top-level "Replace with Garmin Coach plan" button on the Week header (editor mode, when edits exist) reverts the whole week behind a confirm dialog.

# v1.16 additions — per-workout plan-source chip, all-activity effort import, effort-card refinements

- **Per-workout source chip (editor mode)**: `components/plan-source-chip.tsx` (`PlanSourceChip`) on the Today card + each Week row. Untouched Garmin base day → `⌚ Garmin Coach`; a coach-adjusted day (`revertible` override) → `Coach {persona}`; a self-made committed other-sport day (a `DayIntent`) → no chip. Author mode renders nothing (the header `CoachModeBadge` already covers it). `TodayWorkoutCard`/`DayRow` now take a `mode` prop.
- **Effort import extended to ALL activity types**: `enrich_activity` fetches `garmin_rpe`/`feel` (and captures `body_battery_change`) for every activity, not just runs; the run-only metrics (zones, HR drift, chart series, splits, weather) stay gated to `RUN_TYPES` via `_enrich_run_metrics`. `enrich_pending` and `backfill_rpe_feel_bb` no longer filter by run type. Non-run activities are `null` for rpe/feel unless the athlete actually logged them.
- **Activities list**: the RPE badge now reads `rpe ?? garmin_rpe`; a watch-logged value shows `⌚ RPE N` (secondary badge) instead of "unrated". Only genuinely unlogged activities show "unrated".
- **Activity detail "Effort" card**: when effort was logged on the watch and NOT overridden in-app (`rpe == null && garmin_rpe != null`), the card is read-only (`⌚ RPE N/10` + `Felt <label>` badges) — the tap-to-rate input is hidden (no need to re-enter). In-app-rated or unrated activities keep the interactive `RpeScale`.

# v1.17 additions — menstrual cycle tracking as a coach signal

Opt-in, set-once anchor + deterministic forward projection. No new tables — stored as a `cycle` settings key; no Garmin import (spike 2026-07-18 found both accounts hold zero cycle data).

**Settings.** `GET/PUT /api/settings` gain a `cycle` object and a read-only `cycle_status`:

```ts
cycle: {
  enabled: boolean;                 // opt-in feature gate (NOT a gender flag); default false
  last_start_date: string | null;   // ISO date of the most recent period start (the anchor)
  cycle_length_days: number;        // default 28; accepted range 15-60 (out-of-range → 28)
  period_length_days: number;       // default 5; accepted range 1-14
};
cycle_status: CyclePhase | null;    // today's derived phase; null when disabled or no anchor
```

- PUT normalizes `cycle`: a malformed `last_start_date` drops to `null`, out-of-range lengths fall back to defaults, `enabled` must be a real bool. PUT returns the same shape as GET (with a recomputed `cycle_status`).

**CyclePhase** (derived, never stored) — attached per-day and as `cycle_status`:

```ts
interface CyclePhase {
  phase: "menstrual" | "premenstrual" | "follicular" | "luteal";
  day_of_cycle: number;             // 1-indexed
  cycle_length_days: number;
  period_length_days: number;
  days_to_next_period: number;      // 1..cycle_length
  next_period_date: string;         // ISO date
  ease_recommended: boolean;        // 2-3 days pre-start (premenstrual) or first 1-2 days of flow
  in_drift_window: boolean;         // tight band around the predicted start — Today offers a re-anchor confirm
}
```

- **Per-day phase**: `PlanDay` gains `cycle?: CyclePhase | null` on `/dashboard/today` (`workout`) and `/plan/week` (`days[]`). Present only when tracking is enabled with a valid anchor.
- **Top-level Today phase**: `GET /api/dashboard/today` gains `cycle: CyclePhase | null` (today's phase, independent of whether a workout exists) — drives the Today cycle card.
- **Drift prompt (Today)**: the Today `cycle` object also carries `show_started_prompt: boolean` — whether to render the one-tap "did your period start today?" confirm. It's true only inside `in_drift_window` AND when this cycle's start hasn't been confirmed and wasn't snoozed today, so the prompt does NOT re-nag after a Yes / Not-yet or a browser refresh. `current_start_date` (ISO, start of the cycle the date sits in) supports this. Confirmed/snooze state is server-owned (internal settings keys), not part of the writable `cycle` blob.
- **`POST /api/cycle/started`** body `{ date?: string }` (ISO; defaults to today, rejects future dates with 422) → re-anchors the cycle to an observed period start, gently nudges `cycle_length_days` toward the observed gap (2:1 blend), marks the start confirmed, and clears any snooze. Returns the full settings payload (recomputed `cycle_status`).
- **`POST /api/cycle/snooze`** → `{ ok: true }`. "Not yet" — hides the drift prompt for the rest of today only (a new day shows it again unless the start is confirmed).
- **`GET /api/cycle/calendar?months=N`** (N 1-12, default 3) → `{ start, end, days: [{ date, phase, ease_recommended }] }` from the 1st of the current month; `phase` is null per-day when tracking is off. Feeds the read-only month strip.
- **Daily review signal**: the review snapshot carries `menstrual_cycle` (the same dict). `REVIEW_SYSTEM_PROMPT` instructs the coach to gently ease intensity when `ease_recommended` is true (soften a hard session; consider rest on a very low-readiness early-flow day), and — conversely — to GREEN-LIGHT a plan's quality session in the `follicular` phase when readiness is good (remove hesitation, never invent hard work). Mentioned warmly in the `coach_note`, never churning a sound plan. It is a bias fed to the model, not a deterministic gate.
- **UI**: `components/cycle-phase-chip.tsx` (`CyclePhaseChip`) — rose "Menstrual · day N" / amber "Premenstrual" / emerald "Follicular · strong" tag next to the workout badge on Today + Week; luteal stays unmarked. `components/cycle-tracking-card.tsx` (`CycleTrackingCard`) — an off-by-default toggle card in Settings with the prediction summary + a "Manage cycle →" link. `components/cycle-today-card.tsx` (`CycleTodayCard`) — a Today card shown during the period / premenstrual lead-up / drift window, with a one-tap "did your period start today?" confirm (calls `/cycle/started`) in the drift window. `/settings/cycle` page: enable toggle + anchor inputs + today's-phase preview + `components/cycle-month-strip.tsx` (`CycleMonthStrip`), a read-only 3-month projection shaded from `/cycle/calendar`. No tap-to-log period calendar.
- **Nav**: when `settings.cycle.enabled`, a "Cycle" item (droplet) appears in the sidebar and mobile "More" sheet linking to `/settings/cycle` — surfaced via `useCycleEnabled()` on `CoachProvider` (refetches on leaving `/settings*`). The `/settings` nav item no longer highlights on `/settings/cycle`.

# v1.17 additions — morning sync reliability (timezone fix + self-healing review)

**Root cause fixed**: the container ran in UTC while the household is CST (UTC+8), so `PLAN_HOUR=6` fired the daily job at 06:00 UTC = 2pm local. Every morning had no auto-sync, so the daily review sat waiting on data until the user manually hit "Sync now".

- **Timezone**: backend container now runs in `TZ=Asia/Taipei` (Dockerfile installs tzdata; `docker-compose.yml` sets `TZ`; `config.timezone` reads the `TZ` env). The APScheduler cron and `catch_up` are explicitly timezone-aware (`BackgroundScheduler(timezone=...)`, local-hour gate, `SyncLog.ran_at` normalized to local before date comparison). The daily job now fires at **06:05 local**.
- **Self-healing review** (`GET /api/dashboard/review`): now returns `syncing?: boolean` and, when today's data hasn't landed, kicks a **background sync** (`scheduler.ensure_fresh_today` — deduped per user by a 3-min cooldown + the global run lock, non-blocking) so the review never depends on a perfectly-timed cron or a laptop that slept through it. The Today page's existing poll picks up the data when it arrives.
- **`data_ready` is now content-based**: it requires real recovery content (sleep or HRV present), not merely a `DailyHealth` row. This prevents a sync that runs *before* Garmin has processed last night (a bare/empty row) from prematurely satisfying the gate and running the review on null data. `evaluate_today` uses the same `metrics.has_recovery_data()` gate — an empty row now yields `pending_data`, not `done_full`.

# v1.18 — coach text: stray `—` escape fix

- **Symptom**: a freediving day's rationale/description rendered a literal `—` (and a stray trailing quote) instead of an em-dash.
- **Root cause**: stale E2E seed data (`PlanVersion.source="phase6_e2e"`) that wrote the literal 6-char escape into plain-Text columns. NOT a live bug — the LLM structured/chat paths `json.loads` tool args and structured output, so real coach text already stores proper unicode (verified: `daily_reviews.coach_note` render correct `—`/`’`).
- **Fix**: (1) cleaned the affected rows in place; (2) added `planner.clean_llm_text()` — decodes stray `\uXXXX` escapes — applied defensively at the LLM free-text sinks (`apply_plan_days` title/description/rationale, `evaluate_today` coach_note, `create_pending_edit` summary/rationale) so an over-escaping model can never surface raw escapes again. No API shape change.

# v1.19 additions — plan preview / detail page (`/plan/[date]`)

Every Plan card on Today and Week is selectable and opens a dedicated page previewing what that run looks like. See ROADMAP "DECIDED — Plan preview / detail page" for the full story, incl. the load-bearing finding that **Garmin's API exposes no step breakdown for adaptive coach workouts** (only a compact `workoutDescription` string; the app renders stages client-side). Consequence for this contract: for the live data (whole-run HR targets), the page is built around the target + zone + purpose; the structured step UI renders ONLY when a day genuinely carries `steps` (Idaten-authored/pushed days). No `PlanDay` shape change.

## New endpoint

- `GET /api/plan/day?date=YYYY-MM-DD` → `{ mode: "editor" | "author" | null, day: PlanDay | null, intent: DayIntent | null, hr_zones: HrZones | null }`.
  - `day` is the SAME `PlanDay` shape returned in `GET /api/plan/week`'s `days[]` (incl. `steps`, `cycle`, `revertible`, `target_pace`/`target_hr_low/high`, `status`, `pushed_at`, `garmin_workout_id`). `null` when nothing is materialized for that date (unplanned / outside the plan window).
  - `mode` mirrors `week`/`today` (`editor` following a Garmin Coach plan, `author` when Idaten writes the whole plan) — drives `PlanSourceChip`.
  - `intent` is that date's `DayIntent` (committed other-sport) if any, else `null` — drives the `IntentChip` + `OtherSportButton`.
  - `hr_zones` = `{ z1:[lo,hi], …, z5:[lo,hi] }` (bpm bands, from `settings_store.hr_zones` — Garmin's own zones, else LTHR-derived; `null` until zones/LTHR sync). Same `HrZones` shape already used by `ActivitySeries`. Powers the zone bar that locates an HR-targeted run on the Z1–Z5 scale.
  - `date` missing/malformed → 422. A rest day returns its `PlanDay` (`workout_type: "rest"`) so the page renders a graceful rest state, not an error.

## Frontend (as shipped — reframed from the original steps-first draft)

- **New route** `app/plan/[date]/page.tsx` (App Router dynamic segment, keyed by ISO date — `PlanDay` has no numeric id; `(user_id, date)` is its PK). Fetches `api.planDay(date)`.
- **Stat tiles** — Duration / Distance / Target (pace `M:SS /km`, or HR band `bpm`) / Effort (`WORKOUT_EFFORT_LABEL`). Client-derived from the whole-run fields; works for every run.
- **Purpose line** — `WORKOUT_PURPOSE[workout_type]` (in `lib/workout.ts`): a sentence on what that kind of run is for.
- **HR zone bar** — `components/hr-zone-bar.tsx` (`HrZoneBar`): five proportional zone bands with the target HR range highlighted and its primary zone named (`ZONE_LABELS`, `primaryZoneForHr`). Renders when `hr_zones` + `target_hr_low/high` are present. Colors from `ZONE_COLORS` in `lib/workout.ts` (dependency-free copy of the analytics palette, so the page doesn't pull recharts).
- **Structured section — only when `day.steps` is present** (Idaten-authored/pushed days; Garmin adaptive days have no steps). Order: **Steps** → **Effort profile** → **Target zone (HR bar)**.
  - `WorkoutSteps` (redesigned): each step a row with a color-accent bar + duration/target pills + cue; repeat sets grouped in a card with an `N×` badge and computed set total. This redesign also applies on the Today card.
  - `WorkoutTimeline` (`components/workout-timeline.tsx`): proportional kind-colored bar + work/recovery/warmup/cooldown time totals. `workoutBreakdown(steps, workoutPace)` in `lib/workout.ts` → `{ totalMin, workMin, recoveryMin, warmupMin, cooldownMin, segments:[{kind,min,approximate}] }`. Per-step time: `duration_min` if set; else `distance_km`×pace (step pace, else workout pace); else distance-only at a nominal pace (flagged approximate); else equal weight. Repeats expanded before summing.
  - Time-in-zone (Z1–Z5 minutes) intentionally NOT computed client-side (needs server zone boundaries); the WU/work/recovery/CD breakdown ships instead.
- **Source labelling**: `PlanSourceChip` only (⌚ Garmin Coach vs Coach {persona}). The account-level `CoachModeBadge` is NOT shown on this single-day page (it read as contradictory next to a per-day "Coach {persona}" chip; it stays on the Week/Today headers).
- Actions: `PushButton`, `RevertButton` (when `revertible`), `OtherSportButton`, "Ask about this workout" → `/chat?date=…`. States: loading skeleton, backend-down error, unplanned/`null` → "Nothing planned", rest → minimal rest card.
- **Card wiring**: Today card title/meta links to `/plan/[date]`. Week rows are FULLY clickable via a stretched-link overlay (`<Link className="absolute inset-0 z-10">`); the bottom action bar, coach-note "More" toggle, and intent chip are raised to `z-20` so they stay interactive while the rest of the card navigates. Rest days are not linked. Week header actions moved to a dedicated left-aligned toolbar; per-card actions are a bottom action bar (order: Send to watch → Replace with Garmin Coach → Other sport).
- `api.planDay(date)` added to `lib/api.ts`; `HrZones` promoted to a named export in `lib/types.ts` (reused by `ActivitySeries`).

---

# v1.20 additions — Idaten race prediction (own model + Garmin reference)

**Why.** The `prediction` on a `Race` was *Garmin's VO2-max race predictor, Riegel-adjusted* (v1.2 — `races.py:riegel_predict` on `DailyHealth.race_predictions`). Garmin's model is a physiological ceiling that runs optimistic for many recreational runners. Live case: Julianne's self-set goal is 2:28; Garmin predicts 2:12. This version makes the prediction **Idaten's own — Garmin's number corrected by a per-user factor learned from the athlete's actual race results** — and keeps Garmin's raw number as a labelled reference so it can be reconciled against the watch.

**A dead end we ruled out (documented so it isn't retried).** The first cut derived a *demonstrated* VDOT from recent training runs (Daniels VDOT from each run's whole-run-average pace, high-percentile over the window). It was built and unit-tested, then **E2E validation on the two live accounts killed it**: whole-run-average pace of easy/tempo runs badly *understates* race fitness (warmup/recovery drag the average down below race intensity), so it predicted a **2:38 half for William** (LTHR 186, goal 1:52, Garmin 2:01) and 2:55 for Julianne. HR-gating to "hard" efforts didn't save it — even William's hardest whole-run *average* HR is 164 (< 0.88×186), so no run cleared the gate. Doing it correctly (regress pace-vs-HR, extrapolate to threshold) is exactly re-implementing Garmin's Firstbeat economy model — the thing we agreed not to compete with. **Conclusion: training runs are not trustworthy race-fitness signals; only actual races/time-trials are.** The `vdot_from_performance` / `race_time_for_vdot` / `demonstrated_anchor` helpers remain in `metrics.py` (tested) for a future *real-race/TT* anchor, but are NOT on the prediction path.

**Shape of the work: a BACKEND change with a small frontend tail.** Computed server-side (`races.py` / `metrics.py`); the frontend only renders the wider `prediction`. Three paths emitted Garmin's number and all three now emit the calibrated one: `races.py:race_dict`, `api.py` dashboard/analytics `goal`, `planner.py` snapshot.

## Backend build (as shipped)

### 1. Calibrated-Garmin prediction — `metrics.race_prediction(garmin_time_s, k, n_samples)`
- `likely_s = round(garmin_time_s × k)`, where `garmin_time_s = riegel_predict(garmin race_predictions, distance)` (the v1.2 number, unchanged).
- `k` corrects that athlete's systematic bias vs Garmin's predictor. **`source`** is `"garmin"` while `n_samples == 0` (we're just showing Garmin's number, honestly labelled — no reconciliation line) and `"idaten"` once ≥ 1 real race has tuned `k`.
- We do **not** model physiology from training runs (see dead end above). Garmin owns the physiology; we own the per-user correction.

### 2. Per-user calibration factor `k` — `settings_store`
- **Default `1.0`** (trust Garmin until a real race says otherwise). Learned from actual results: on each completed race `observed = actual_time_s / garmin_predicted_time_s`, then EWMA `k ← (1-α)·k + α·observed`, **α = 0.35**. **Clamp `k ∈ [0.85, 1.25]`** (both directions — a runner may beat or miss Garmin; one blow-up/downhill-PR can't distort it). Julianne racing 2:28 against a Garmin 2:12 prediction pushes `k → ~1.13`, so her future 2:12 → ~2:28.

### 3. Range + confidence — `metrics.py`
Confidence is **how many real races have tuned `k`** (`prediction_confidence(n_samples)`): `0 → "low"`, `1-2 → "medium"`, `3+ → "high"`. Symmetric half-width `hw = base[confidence]`, `base = {high: 0.04, medium: 0.06, low: 0.08}`; `low_s/high_s = round5(likely_s·(1∓hw))`. More real races → tighter range and higher confidence.

### 4. Call-site swaps (all three use the calibrated number)
- `races.py:race_dict()` → full `prediction` block; `garmin_time_s` carries Garmin's raw number as the reference. `delta_s = likely_s − goal_s`.
- `api.py` dashboard/analytics `goal` → `predicted_time_s = likely_s`.
- `planner.py` snapshot per-race `predicted_time_s`/`predicted_pace` = `likely_s`/`likely_pace` (plan grounded on our number); `garmin_time_s` travels as context.

### 5. Calibration-update hook — `races.maybe_record_race_result`, wired into `garmin/enrich.py`
On each enriched run, if it matches a scheduled `Race` (date ±1 day, distance within 5%), fold `actual_time_s` vs **Garmin's predicted time for that race** into `k` (§2). Idempotent per race (deduped by `race_id` in `samples`). Backend-internal; no endpoint.

### 6. Storage
- `settings_store` internal key `race_pred_calibration = { k: float, samples: [{race_id, predicted_s, actual_s, at}] }` — JSON, additive, no migration, invisible to the client (outside `DEFAULTS`).
- `garmin_time_s` computed on the fly from `DailyHealth.race_predictions` — no new column.

## Type change — supersedes the v1.2 `Race.prediction` block

```ts
prediction: {
  source: "idaten" | "garmin";     // model behind likely_s; "garmin" only when we can't yet compute our own
  likely_s: number | null;         // Idaten point estimate (center of range) — the authoritative number
  low_s: number | null;            // fast end of range
  high_s: number | null;           // slow end of range
  confidence: "high" | "medium" | "low" | null;
  delta_s: number | null;          // likely_s - goal; negative/zero = on track (same semantics as before, now vs likely_s)
  likely_pace: string | null;      // min/km at likely_s
  goal_time_s: number | null;
  goal_pace: string | null;        // min/km
  garmin_time_s: number | null;    // Garmin's VO2max predictor, Riegel-adjusted to this distance — REFERENCE ONLY, never drives plan/paces
}
```

- Renames vs v1.2: `predicted_time_s` → `likely_s`, `predicted_pace` → `likely_pace`. New: `source`, `low_s`, `high_s`, `confidence`, `garmin_time_s`. `delta_s`/`goal_time_s`/`goal_pace` unchanged.
- Everything that already reads `prediction` inherits the authoritative number for free: `GET /api/dashboard/today` (`race`), `GET /api/analytics` (`goal` — now derived from `likely_s`, not Garmin's), and the planner snapshot (the per-race `predicted_time_s`/`predicted_pace` from v1.13 now carry Idaten's `likely_s`/`likely_pace`; `garmin_time_s` may travel alongside as context but the plan is grounded on ours). No endpoint routes change.

## Reconciliation copy (single source of truth)

When `garmin_time_s` is present, `source === "idaten"`, and `|garmin_time_s - likely_s| ≥ 60s`, detail surfaces render one explanatory line beneath the headline:

> Garmin predicts **{garmin_time_s}** — ours corrects that for how you've actually raced.

Suppress the line when `source === "garmin"` (nothing to reconcile) or the two agree within 60s.

## Frontend (the small tail — render-only, strictly downstream)

The frontend computes nothing; it renders the wider `prediction` object. Idaten leads, Garmin rides along as reference — do **not** show the two predictions at equal weight.

- **`PredictionChip` (`components/race-chip.tsx`) — small surfaces (Today countdown chip, Trends "Race outlook").** Idaten only. Show the **range + goal delta**, no Garmin number, no reconciliation line (no room):
  - `high`/`medium` confidence → `"Likely 2:20–2:29 · on track for 2:28"` (green when `delta_s ≤ 0`, amber/red when behind).
  - `low` confidence → soften to a single tilde estimate `"~2:24 · goal 2:28"` with a muted/secondary style so it doesn't overclaim.
  - No prediction yet → existing em-dash `"Prediction —"` state.
  - Supersedes the v1.2 Today-chip copy `"42 days · predicted +7:10 vs goal"` → `"42 days · likely 2:20–2:29 vs goal 2:28"`.
- **Races manager card (`components/races-card.tsx`) + race detail — full surfaces.** Idaten range is the headline; Garmin appears as a smaller reference with the reconciliation line above. Layout stacks on small screens (keep the v1.2 mobile rule). Confidence shown as a small label/dot (`high`/`medium`/`low`) next to the range.
- **Confidence nudge:** when `confidence === "low"`, the card shows a subtle affordance — "Add a recent race or time-trial to sharpen this" — linking to the existing "Add race" dialog (which already doubles as logging a recent result). No new input flow; this is the only place we ask her for efforts, and only when the data is thin.

## Compatibility / migration

- Additive on the wire but **renaming** `predicted_time_s`/`predicted_pace` → `likely_s`/`likely_pace` — the frontend `RacePrediction` type (`lib/types.ts`), `PredictionChip`, `races-card.tsx`, and Today/Trends readers all moved in the same change. (Done.)
- Every race always has a `prediction`: calibrated Garmin when a Garmin number exists (`source` `garmin` uncalibrated / `idaten` once tuned), or all-null when Garmin has none for the distance.
- Per-user calibration (`settings_store` key `race_pred_calibration`) is backend-internal; not exposed on this contract.

## Status — SHIPPED, but UI GATED OFF (feature flag)

All backend + frontend landed; 278 backend tests pass, `tsc` clean. Live validation on both accounts (uncalibrated, `n_samples=0`): William 2:01:31 (range 1:52–2:11, his 1:52 goal at the fast end), Julianne 2:12:30 (range 2:02–2:23) — both `source:"garmin"`, low confidence, matching Garmin exactly until a real race tunes `k`.

**The prediction UI is hidden behind a flag** (`frontend/lib/flags.ts` → `SHOW_RACE_PREDICTION`, default **off**; enable with `NEXT_PUBLIC_SHOW_RACE_PREDICTION=true`). Rationale: until an athlete has actually raced, Idaten's number is just Garmin's number relabelled, so showing it as a second "prediction" alongside the one in the Garmin app only confuses. Flag off → the races card, Today chip, and Trends "Race outlook" card show no prediction (just the goal); Garmin's number stays in the Garmin app. **The backend keeps computing and calibrating silently** (`k` learns from every real race even while hidden), so flipping the flag on later — once the prediction earns its place (real-race/TT anchor, or distance-aware `k`) — needs no backfill. The `prediction` object still ships on the wire and still grounds the planner; only its display is gated.

**Open follow-up (not blocking):** the calibration only starts working once each athlete finishes a race that matches a scheduled `Race` row; until then everyone sees Garmin's number (honestly labelled). A future enhancement is a genuine *real-race/TT anchor* (using the retained `metrics` VDOT helpers) so a recent hard race can drive the number directly, not just calibrate `k`.

# v1.21 additions — execution score + analysis, Garmin-zone unification, Trends filter

Retrospective per-run grading: how well a completed run matched the workout it was attempting. Deterministic SCORES for every attributed run (old and new); a persona-voiced LLM NARRATIVE only for recent runs, generated lazily.

## `Activity` / `ActivityDetail` — new fields

```ts
execution_score: number | null;        // 0-100; null for runs not attributed to a plan (free runs)
execution_score_source: "garmin" | "idaten" | null;  // watch's own compliance score vs Idaten-computed
execution_breakdown: ExecutionSegment[] | null;      // per-prescribed-step receipts
execution_analysis: string | null;     // LLM narrative; null until lazily generated (today-onward only)

interface ExecutionSegment {
  label: string | null;      // warmup / interval / recovery / cooldown / …
  axis: "hr" | "pace";
  target: [number, number];  // band — bpm for hr, m/s for pace (higher speed = faster)
  duration_s: number;
  avg_actual: number | null; // athlete's average on that axis over the segment
  score: number | null;      // 0-100 for this segment
}
```

Present everywhere `_activity_dict` is returned (Today `completed_workout`, `/activities`, `/activities/{id}`).

## Scoring model (backend, informational)

- **Attribution** (device-agnostic, never checks watch model): a run is scored only if it was an attempt at a planned workout — tier-1 = a Garmin coach run (`metadataDTO.trainingPlanId`) or an Idaten-pushed/authored day; tier-3 = the ambiguous middle (see prompt below); free/rest runs are unscored.
- **Score source**: `summaryDTO.directWorkoutComplianceScore` present ? PULL (source `garmin`) : COMPUTE (source `idaten`). Presence is per-activity, so it self-corrects for any watch.
- **Precedence**: an Idaten-owned day (accepted edit / author mode) scores against Idaten's prescription even when `trainingPlanId` is present — always the FINAL plan the athlete followed, never Garmin's original.
- Computed scores = time-integrated closeness of actual HR/pace to each prescribed segment's band (over/under-shoot both penalised); coach targets Garmin hides are derived from lap `intensityType` + the day's training-effect label + the athlete's Garmin HR zones.

## Today payload — new fields

```ts
// GET /api/dashboard/today
completed_workout: Activity | null;   // today's plan-attributed scored run; when set, the UI
                                      // swaps the plan card for a result card (score + analysis)
attribution_prompt: { activity_id: number; workout_label: string } | null;
                                      // ambiguous run on a planned-workout day: "Was this your {X}?"
```

## New endpoints

```
POST /api/activities/{id}/attribution   { attempted: boolean }
    -> { ok: true, execution_score: number | null }
    Resolve an ambiguous run. attempted=true attributes + scores it (source idaten);
    false marks it "just a run" (never scored, never re-asked). Folded into the Today RPE moment.

POST /api/activities/{id}/analysis      (no body)
    -> { analysis: string }
    Generate (once) + return the LLM execution narrative. Idempotent — cached text returns with
    no LLM call. 400 if the run has no execution score, or if it is older than 2 days
    (ANALYSIS_MAX_AGE_DAYS): old history NEVER spends a call. The Today page load is the only
    trigger; the activity-detail page displays cached text but never generates.
```

Cost profile: ~2 lazy LLM calls on an active running day (the morning review + the post-run analysis), zero on an unopened / no-run day.

## Zone basis unification (behind the wire)

The athlete's HR zones now come from Garmin's own per-athlete boundaries (`zoneLowBoundary`, observed from the HR-in-zones payload we already fetch) whenever available, else LTHR-derived. This is the SINGLE source for both planner HR targets and execution scoring, so prescribed bands match what the watch scores against. `ActivitySeries.hr_zones` and `/plan/day.hr_zones` reflect this; no shape change. `splits` in `/activities/{id}/series` gain `intensity` + `step_index` (structured-workout linkage; null on free runs).

## Trends filter

- Range options now `[7, 30, 90, 180]` (added **7d**).
- The selected range persists in `localStorage` (`trends_range_days`) and is restored on return; first-ever visit defaults to **7d** (was a hard 90d).

## v1.21.1 — forward-looking + coach-attributed execution analysis

- `Activity`/`ActivityDetail` gain `execution_analysis_coach: string | null` — the `coach_style` key (default/chill/strict) of the persona that WROTE the analysis, stamped at generation time so a later coach switch never re-labels it. The UI renders the analysis via `CoachNote` (avatar + name) resolved from this key, NOT the current coach.
- `POST /api/activities/{id}/analysis` response is now `{ analysis: string, coach: string | null }`.
- The analysis is now FORWARD-LOOKING and honest: it relates the run to the primary race's goal-vs-prediction trajectory (`vs_goal_s`) and recent execution trend, and explicitly declines to claim "on track" when there's no goal or confidence is low. The SCORE keeps its own `execution_score_source` provenance ("scored by your watch" vs "by Idaten"); the ANALYSIS is attributed separately to the coach persona.

## v1.21.2 — house style, Trends daily view, About hidden

**No em-dashes in any LLM-generated text.** All athlete-facing model prose (daily coach note, execution analysis, plan titles/descriptions/rationales, edit summaries, chat) is stripped of em-dashes (— ― and long bars → spaced hyphen; en-dashes in ranges kept). Enforced two ways: a house-style line appended to every system prompt via `style_prompt`, and a deterministic `strip_em_dashes()` in `clean_llm_text` (structured outputs) + per-delta in the chat stream (live + persisted). No wire-shape change; prose just reads human.

**Trends: the 7-day view renders the two "weekly" charts BY DAY.**
- `GET /api/analytics` gains `zones_daily: ZonesDay[]` alongside `zones_weekly` — same shape but keyed by `date` instead of `week_start`:
  ```ts
  interface ZonesBucket { z1_s: number; z2_s: number; z3_s: number; z4_s: number; z5_s: number; }
  interface ZonesWeek extends ZonesBucket { week_start: string; }
  interface ZonesDay  extends ZonesBucket { date: string; }
  ```
- When the Trends range is **7d**, "Weekly distance" becomes "Daily distance" (per-day bars from `TrendPoint.distance_km`) and "Time in zones" uses `zones_daily`. 30/90/180 stay weekly. The chart component takes a generic bucket carrying a `start` ISO date (week_start or date).

**About page hidden from nav.** `/about` route + page code are KEPT; the nav links (desktop sidebar + mobile More) are removed. Reachable by direct URL; re-add the two `{ href: "/about" }` entries in `sidebar.tsx` to restore.

## v1.21.3 — completed-day marking + Week completion indicator

- When a run is attributed + scored to a plan day (auto at enrich, or via `POST /activities/{id}/attribution` Yes), that `PlanDay.status` flips `planned → completed`. This LOCKS the day: `apply_plan_days` (Ask-Koa edits), `materialize_coach_plan` (daily re-materialize), and `revert_to_garmin` (Replace-with-Garmin) all already skip non-planned days, so a finished session is never overwritten. Only `planned → completed`; skipped/override history is untouched.
- `GET /api/plan/week` days[] gain `execution: { score, source: "garmin"|"idaten"|null, activity_id } | null` — the matched run's score for that day (null when no run matched). `status` was already present.
- Week UI: a `completed` day shows a green "✓ Done" badge + an "Execution {score}" chip linking to the activity; its Revert and Other-sport buttons are hidden (it's locked).

## v1.22 — injury / niggle tracking

The athlete can report pain ("a niggle") and it persists until resolved; the coach's daily review eases the plan around it.
Reporting is athlete-initiated: primary door is chat ("my knee hurts" → the coach logs it), with a UI fallback.
The only prompt we ever show is a gentle check-in after a quiet window (7 days for severity 1, 14 for severity 2-3); "still sore" re-arms the window.

### Niggle type

```ts
type Niggle = {
  id: number
  body_part: string            // "left knee"
  severity: 1 | 2 | 3          // 1 = niggle (minor), 2 = pain, 3 = injury
  severity_label: "niggle" | "pain" | "injury"
  onset_date: string           // ISO date
  days_open: number
  note: string
  show_checkin: boolean        // show the "still bothered?" check-in variant
}
```

### Endpoints

- `GET /api/dashboard/today` gains top-level `niggles: Niggle[] | null` (null when nothing open — render nothing).
- `GET /api/niggles` → `{ niggles: Niggle[] }` (open only).
- `POST /api/niggles` `{ body_part, severity, note?, onset_date? }` → `{ niggle }`. 422 on empty body_part, severity outside 1-3, bad/future onset_date. Logging an already-open body part updates that entry (no duplicates).
- `POST /api/niggles/{id}/resolve` → `{ ok: true }`. 404 if not the user's.
- `POST /api/niggles/{id}/checkin` → `{ ok: true }` — "still sore", keeps it open and re-arms the check-in window.

### UI

- **`NiggleCard`** (new, `components/niggle-card.tsx`) on Today, rendered directly below `CycleTodayCard`, ONLY when `today.niggles` is non-empty — never a permanent widget. One row per niggle:
  - Normal row: body part (capitalized) + severity label chip + "day N". Severity tone: 1 amber, 2-3 rose (same palette family as `CyclePhaseChip`). A quiet "Resolved" ghost button per row (`POST resolve`, optimistic-hide, toast "Glad it's better").
  - Check-in variant when `show_checkin`: the row becomes a gentle question — "Still bothered by your left knee?" with two small buttons: "Better now" (`resolve`) and "Still sore" (`checkin`, optimistic, row returns to normal). Mirrors the cycle drift-prompt interaction.
  - A small "Log a niggle" ghost link at the card's foot opening the log dialog.
- **`NiggleLogDialog`** (new): body part text input, severity select (Niggle - minor / Pain - protect it / Injury - can't train normally), optional note, optional start date (defaults today, no future). Submits `POST /api/niggles`; refreshes the Today payload on success.
- **Settings**: a compact "Niggles & injuries" card (below Cycle tracking) with a one-line explainer ("Tell your coach when something hurts — in chat or here — and the plan eases around it until it clears"), the open list from `GET /api/niggles` (with the same Resolved button), and a "Log a niggle" button opening the same dialog. This is the standing entry point when the Today card is hidden.
- House style: no em-dashes in any copy; plain dash only.

## v1.23 — coach-quality feedback (thumbs)

See COACH_QUALITY.md for the full operating model (four stages, flight-recorder-not-autopilot).
Frontend scope: thumbs on the two coach-note surfaces, dismiss-reason chips on proposals, and an admin quality panel.

### Types

```ts
type FeedbackState = { rating: 1 | -1 | null; tags: string[]; comment: string } | null
// Thumbs-down chips: "wrong" | "off_tone" | "too_long" | "not_useful"
// Dismiss-reason chips: "didnt_want_change" | "reasoning_wrong"
```

### Endpoints

- `POST /api/feedback` `{ surface, ref, rating, tags?, comment? }` → `{ feedback: FeedbackState }`.
  - `surface`: `"coach_note"` (ref = the review's date ISO) | `"execution_analysis"` (ref = activity id as string) | `"edit_proposal"` (ref = edit id as string).
  - `rating`: `1` | `-1` | `null` (null = dismiss-reason-only, edit_proposal surface).
  - Upserts: re-rating the same artifact updates in place (ratings are changeable). 404 when the artifact doesn't exist / isn't the caller's; 422 on bad surface/rating.
- `GET /api/feedback/summary?days=90` (ADMIN-only, like `/usage`) → `{ days, by_surface: [{surface, up, down, dismiss_reasons}], by_user: [{user_id, ...same}], recent_negative: [{surface, user_id, artifact_ref, tags, comment, artifact_text, prompt_version, updated_at, has_context}] }`.
- `GET /api/dashboard/review` review object gains `my_feedback: FeedbackState` (also on the `POST /dashboard/evaluate` response).
- `GET /api/dashboard/today` `completed_workout` gains `analysis_feedback: FeedbackState`; `GET /api/activities/{id}` gains the same.

### UI

- **Thumbs in `CoachNote`** (shared component - one change covers both surfaces): two small ghost 👍/👎 icons, bottom-right of the note, visible on hover/always-subtle on mobile. Enabled via a new optional `feedback` prop `{ surface, ref, state }`; when absent the component renders exactly as today (week rationales etc. stay unrated). Tap 👍 → immediate `POST /api/feedback` rating 1 (optimistic fill). Tap 👎 → a small popover: the four chips (Wrong or ungrounded / Off tone / Too long / Not useful, multi-select), an optional one-line "anything else?" input, and a Send button; posts rating -1 with tags+comment. Re-tapping either thumb changes the rating. Current state comes from `my_feedback` / `analysis_feedback`.
- **Wire it** in `DailyCoachNote` (surface `coach_note`, ref = review date) and on the execution-analysis render in `ResultCard` + activity detail (surface `execution_analysis`, ref = activity id).
- **`EditProposalCard` dismiss**: after a successful dismiss, the card's confirmation state offers two optional one-tap chips - "Didn't want the change" / "The reasoning was wrong" (posts `{ surface: "edit_proposal", ref, rating: null, tags: [chip] }`), plus a quiet skip (just leaving it is fine). No extra step before the dismiss itself - the reason is optional and after the fact.
- **`AdminQualityCard`** on `/admin` below `AdminLlmCard`: per-surface thumb-rate tiles (👍 percentage + counts), per-member table, and a recent 👎 list (surface, tags, comment, first ~2 lines of the artifact text). Data from `GET /api/feedback/summary`.
- House style: no em-dashes in copy; plain dash only.

# v1.24 additions — UX batch (week summary, Today week strip, optimistic settings, list score chips)

From UX_IMPROVEMENTS.md (2026-07-21 review). One API change; the rest is render-only.

## 1. `GET /api/plan/week` gains `summary`

```ts
interface WeekSummary {
  planned_min: number | null; // sum of duration_min over non-rest plan days
  done_min: number;           // all completed activities in the week window (any sport)
  run_km: number | null;      // completed RUN distance only - an actuals fact, never a target
  easy_pct: number | null;    // Z1+Z2 share of the week's zone time (the 80/20 check)
}
```

Framing is deliberate: plans here are time-based (Garmin DSW style), so the summary's primary currency is time at intensity.
Distance is a secondary actuals-only footnote.
No unit setting - the frame is derived from the plan data itself.

## 2. Week page - summary line

The navigator's "X / Y done" line extends to "X / Y done · 3 h 05 of 4 h 10 · 78% easy · 8 km run" (null parts dropped).

## 3. Today - week-at-a-glance strip

The Week page's Mon-Sun strip is extracted to `components/week-strip.tsx` and reused on Today in a compact "This week" card (under Readiness), with the summary line in the card header.
Tapping a day deep-links to `/week?day=YYYY-MM-DD` - NEW query param: Week opens + scrolls to that day's card once loaded (one-shot).

## 4. Activities list - execution score chips

Each row now leads with a colored execution-score chip (same 80/50 tone thresholds as the Week strip; `scoreChipTone` exported from `components/execution-score.tsx`).
Unscored activities show nothing.
No API change - the list payload already carried `execution_score`.

## 5. Settings - optimistic everywhere (Save button removed)

Every control persists the moment it changes: selects/toggles PUT their single key immediately (the API merges per-key), athlete free-text/number fields save on an 800 ms debounce after typing stops.
Failures revert the control with an error toast.
The bottom-of-page "Save settings" button is gone - the split save model (some instant, some deferred) was a silent-data-loss trap on mobile.

## 6. Mobile polish batch (UI only)

Dropdown menus clamp to the viewport (max-w + position clamp); splits table gets a right-edge fade scroll cue; dialogs autofocus their first input; app shell uses `min-h-dvh`; chat bubbles widen to 92% on phones.

## v1.24.1 — summary-line refinements (user feedback)

- Activities score chip is worded "Score 84" (capitalized like a label; RPE stays all-caps as an acronym).
- The easy share reads "78% easy (Z1+Z2)" (matches the Trends footer wording) and carries a `MetricInfo` popover.
  New `MetricId` `easy_pct` - canonical copy (part of the product, do not paraphrase):
  - title: "Easy share (80/20)"
  - body: "The share of this week's training time spent in heart-rate zones 1–2 — the easy zones. Endurance training works best polarized: roughly 80% easy, 20% hard. Early in the week one easy run reads 100%; judge the number by Sunday. Persistently under ~70% usually means your easy runs are creeping too hard, which blunts both recovery and the quality sessions."
- `weekSummaryLine` (string helper) is now the `WeekSummaryLine` component in `components/week-strip.tsx`; on Today it renders below the strip (wrapping, never truncated) instead of in the card header.

# v1.25 additions — eager morning review + calm "no sleep data yet" state

From the 2026-07-21 proactive-delivery discussion (ROADMAP Idea C: push rejected, eager generation built instead).

## 1. Eager review generation (backend behavior, no endpoint change)

The daily job (`scheduler.py`, plan_hour cron) now runs `evaluate_today` right after each user's sync, gated on `metrics.has_recovery_data` — the coach's daily call exists by ~plan_hour+5 on normal days, before the athlete opens the app.
When the night hasn't landed yet, `catch_up` (every 30 min) re-syncs and evaluates once recovery data appears; no cutoff, so a night slept off in the afternoon still gets its review.
While data stays absent each retry costs one Garmin data sync and zero LLM calls.

`evaluate_today` is now idempotent internally (per-user lock + done-state re-check): the scheduler's eager pass and the Today page's lazy trigger can race without double-spending.
The lazy Today-page path is unchanged and remains the fallback (server down at cron time, review failure, pre-plan_hour visits).

## 2. `GET /api/dashboard/review` gains `data_overdue`

```ts
interface DashboardReview {
  review: DailyReview | null;
  data_ready: boolean;
  syncing?: boolean;
  data_overdue?: boolean; // NEW: still no recovery data at >= plan_hour + 2h (household zone)
}
```

`data_overdue` means the missing data reads as "no sleep recorded" (a rough night, or a night that ends mid-day), not a slow sync.

## 3. Today — calm waiting state (frontend)

While `data_overdue` is false the waiting UI is unchanged (pulsing "Getting last night's sleep & recovery from Garmin…", text-link "Review with recent training instead" after 25 s).
Once `data_overdue` is true, `DailyCoachNote` switches to a calm card: no pulse animation, copy "No sleep data from Garmin yet - I'll pick it up when it lands.", and the structural-review action promoted to a real (secondary) button.
The poll slows from 5 s to 60 s in this state; if data lands later (an afternoon sleep), the same poll picks it up and the normal review flow resumes.

## v1.24.2 — Activities row decluttered (user feedback)

- RPE badges removed from the Activities LIST entirely (RPE still lives on the activity detail page).
- Execution score renders as the same `ScoreRing` medallion as the Week page rows (right edge, before the chevron), not a worded chip. Unscored rows show nothing.
- `MetricInfo` popover gained `whitespace-normal` so its body wraps even when the trigger sits inside a nowrap line (fixes the week-summary tooltip overflowing its box).

## v1.24.3 — Activities list simplification (user feedback)

- Temperature dropped from list-row stats (still on the detail page).
- Day-range tabs (30d/90d/180d/All, v1.12 §2) REMOVED - the list is newest-first with load-more, so a truncating range filter had no job; it sat on All permanently.
  Temporal orientation now comes from month divider headers ("July 2026") inserted where the month changes while scrolling.
  `GET /api/activities?days=` stays supported backend-side; the list page no longer sends it. Type chips unchanged.

## v1.25 — training-load ramp guardrail on Trends (Idea E)

The multi-week "too much, too soon" signal (7-day vs 28-day training load) now feeds the daily review AND gets an athlete-facing chart.
Backend-computed; thresholds calibrated on live history.

### `GET /api/analytics` gains `ramp`

```ts
type RampPoint = { date: string; acute: number; chronic: number; ratio: number | null }
// ratio is null where the athlete's base is too small to be meaningful - gap the line, don't draw 0.

ramp: {
  series: RampPoint[]          // daily, over the requested window
  caution: number              // 1.3 - band edge
  high: number                 // 1.5 - band edge
  zone_today: "safe" | "caution" | "high" | null
  chronic_trend: "building" | "flat" | "detraining" | null
  race: { name: string; date: string } | null   // primary race, for the marker
}
```

### UI - one new chart in the Trends "Load" group

- **"Load ramp"** chart (new `components/ramp-chart.tsx`), placed with the existing ACWR/load charts: the `ratio` line over shaded horizontal bands - green up to `caution`, amber `caution`-`high`, rose above `high`. Y domain ~[0.5, 2.0] clamped. Null ratios gap the line.
- Subtitle/footer copy (plain language, no acronyms): "How fast your training load is growing vs what your body is used to. Staying under 1.3 is a sustainable build; above 1.5 is injury territory."
- A small status chip in the chart header from `zone_today` + `chronic_trend`: e.g. "Safe - building" (emerald), "Caution" (amber), "High" (rose), "Detraining" (slate). Hide when null.
- If the primary race's date falls inside the visible window, draw a subtle vertical marker with the race name (most windows won't include it - that's fine).
- Follows the existing Trends range filter (7/30/90/180d) like every other chart; on 7d the chart still works (daily points).
- Metric tooltip (`MetricInfo`) coaching copy: "Compares your last 7 days of training load to your last 28. A ratio over ~1.3 held for several days means you're ramping faster than your body can adapt to - the classic overuse-injury setup. One easy week never trips it; your baseline absorbs it."
- House style: no em-dashes; plain dash only.

## v1.26 — activity route map

Runs recorded outdoors now expose their GPS route, and the activity detail page renders it on a map.

### `GET /api/activities/{id}/series` gains `route`

```ts
route: Array<[number, number]> | null;   // [lat, lon] pairs, ordered, downsampled to <=500 points
// null = not known yet / non-GPS activity; [] = confirmed no GPS (treadmill/indoor).
// Frontend treats null and [] identically: no map.
```

Same lazy-fetch semantics as `series`: the first view of an older activity fetches from Garmin and caches, so the request can take a couple of seconds - the existing skeleton already covers this.

### UI - route map on the activity detail page

- New `components/activity-map.tsx`, rendered as the FIRST card of the series section (above the Pace chart), only when `route` has >= 2 points.
- **MapLibre GL JS** (`npm install maplibre-gl`) with Carto vector basemaps, matched to the app theme via `useTheme().resolvedTheme` (next-themes):
  - light: `https://basemaps.cartocdn.com/gl/positron-gl-style/style.json`
  - dark: `https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json`
  - on theme change call `map.setStyle(...)` and re-add the route source/layers on the `style.load` event.
- Route rendering (note: GeoJSON wants **[lon, lat]** - swap from the API's [lat, lon]):
  - GeoJSON LineString with two line layers for a crisp modern look: a wider casing underneath (dark translucent in light mode / black in dark mode) + the main line on top in the app accent color, `line-cap: round`, `line-join: round`, width ~3.5 (casing ~6).
  - Small start marker (white-ringed green dot) and finish marker (white-ringed dark/red dot).
  - `map.fitBounds` over the route with ~40px padding, `animate: false` on load.
- Card styling: use the existing `Card` with `CardContent` at `p-0` so the map bleeds edge-to-edge inside the rounded card; map container `h-64 sm:h-96 w-full`, `overflow-hidden rounded-2xl` (match Card radius). No card header - the map IS the content.
- Interaction: `cooperativeGestures: true` (ctrl/cmd+scroll to zoom, two-finger on mobile) so the page never hijacks scroll; keep the default nav feel otherwise, hide the maplibre logo control, keep a compact `AttributionControl` ("© OpenStreetMap contributors © CARTO" - legally required, bottom-right, compact mode).
- Import `maplibre-gl/dist/maplibre-gl.css` in the component. Create the map inside `useEffect` (client-only; the detail page is already a client component) and `map.remove()` on cleanup.
- Non-GPS activities: render nothing (no empty-state card).

## v1.27 — race course maps (My Maps link / KML / KMZ / GPX)

Each race can carry an athlete-imported course polyline, rendered with the same map component as activity routes.

### `Race` gains `course`

```ts
course: Array<[number, number]> | null;  // [lat, lon] pairs, <=500 points; null = no course imported
```

### New endpoints

`POST /api/races/course/preview` — stateless parse of a course source into candidate tracks (race maps often hold several courses, e.g. half/10K/4K):

```ts
// body: exactly one of
{ url: string }          // shared Google My Maps link; backend extracts mid= and fetches Google's KML export itself
{ content_b64: string }  // an uploaded .kml/.kmz/.gpx file, base64 (10 MB max)

// 200 response
{ tracks: Array<{ name: string; distance_km: number; points: Array<[number, number]> }> }
// 400 with a human-readable `detail` on bad links/files or marker-only maps; surface it verbatim.
```

`PUT /api/races/{id}/course` body `{ course: Array<[number, number]> }` (2-2000 points) — saves the picked track, returns the updated Race.
`DELETE /api/races/{id}/course` — clears it, returns the updated Race.

### UI

- `RaceRow` gains a map icon action (accent-tinted when a course exists) opening `components/course-dialog.tsx`: URL field + "Load", "or" divider, file upload button (.kml/.kmz/.gpx read client-side, base64'd), then a track picker (radio rows: name + distance, pre-selected to the track closest to the race's `distance_km`) with a live `RouteMap` preview, Save / Remove-current-map actions.
- Races with a course render the map inline under the row (`RouteMap`, ~h-44/h-56).
- `RouteMap` is the bare map extracted from `ActivityMap` (same Carto basemaps/theming/markers); `ActivityMap` stays the card-wrapped activity variant.

## v1.28 — onboarding comprehension: metric + concept tooltips (UX_IMPROVEMENTS Phase 1-2)

No wire-shape change - render-only. Extends the shared `MetricInfo` popover (see "Metric explanations") to the concepts a new user meets but that were previously undefined in-product:

- **Phase 1 (hero metrics on the landing page):** the **Readiness** ring gained a ⓘ next to its level pill (`ReadinessCard`), and the **Execution** score badge gained one next to its "Execution" label (`ScoreBadge` in `components/execution-score.tsx`). Copy is in the metric list above.
- **Phase 2 (jargon + trust):** first-encounter ⓘ tooltips for **Niggles** (`NiggleCard` + `NigglesSettingsCard`), **RPE** (`RpeScale` + the read-only Effort card on activity detail), **Plan source** and **Training mode** (Settings; `Field` gained an optional `info` slot). `EditProposalCard` now shows a quiet "Nothing changes until you accept - this is only a proposal." line while the proposal is pending, reinforcing the approval model at the decision point (the welcome wizard's mini-map already states it once during onboarding).

Rationale: the app already had solid *activation* onboarding (the `/welcome` wizard, `GettingStartedCard`, `CoachHint`), but no *comprehension* layer - the Today dashboard led with undefined numbers. This reuses the one teaching pattern already proven on Trends rather than adding a tutorial or FAQ page.

## v1.29 - gear (shoes): mileage, per-activity editing, one-tap suggestions

Backend mirrors Garmin's gear-service at sync time (list + per-shoe lifetime totals + which shoe each activity wore, bulk-labeled with one call per shoe).
Editing writes through to Garmin (the same link/unlink endpoints the Connect web app uses), then updates the mirror.
Shoe photos are instance-local uploads under the data dir; the repo ships no imagery - shoes without a photo render a generated card.

### New type

```ts
interface GearItem {
  uuid: string;              // Garmin gear UUID (stable id)
  name: string;              // e.g. "New Balance 1080v14" (customMakeModel)
  make: string;
  model: string;
  gear_type: string;         // "Shoes" | "Bike" | ... (UI focuses on Shoes)
  status: string;            // "active" | "retired"
  date_begin: string | null; // ISO date the shoe entered service
  distance_km: number;       // lifetime mileage from Garmin's gear stats
  limit_km: number | null;   // athlete's retire-at threshold, if set in Garmin
  total_activities: number;
  has_image: boolean;        // photo uploaded to this instance
}

interface GearSuggestion {
  activity_id: number;
  date: string;
  activity_name: string;
  bucket: string;            // "plan:tempo" | "pace:easy" | ... (why we think so)
  current: { uuid: string | null; name: string | null };
  suggested: { uuid: string; name: string };
  confidence: number;        // 0-1 share of the bucket's history agreeing
  sample_size: number;       // runs in the bucket
}
```

### `Activity` / `ActivityDetail` gain

```ts
gear_uuid: string | null;    // shoe worn; join against GET /api/gear for the name
```

### New endpoints

- `GET /api/gear` → `GearItem[]` (from the mirror; empty until the first sync or refresh)
- `POST /api/gear/refresh` → `GearItem[]` - on-demand Garmin mirror refresh (first visit / manual refresh; 502 if Garmin is unreachable)
- `GET /api/gear/suggestions` → `GearSuggestion[]` - recent runs (21 days) whose shoe disagrees with the athlete's own strong habit (≥5 samples, ≥70% agreement) for that workout bucket; dismissed ones never return
- `PUT /api/activities/{id}/gear` body `{ gear_uuid: string | null }` → `{ ok: true, gear_uuid }` - swaps the shoe on Garmin (unlink other shoes, link the new one; null = remove), then mirrors; 502 if the Garmin write fails
- `POST /api/activities/{id}/gear/dismiss` → `{ ok: true }` - reject the suggestion for this activity permanently
- `POST /api/gear/{uuid}/image` multipart `file` (JPEG/PNG/WebP, ≤5 MB) → `GearItem` - upload/replace the shoe photo
- `GET /api/gear/{uuid}/image` → the photo bytes (404 if none)
- `DELETE /api/gear/{uuid}/image` → `GearItem`

### UI

- New `/gear` page: card per shoe - uploaded photo, or a generated card (brand accent color + wordmark initial + model name) - with lifetime km (progress toward `limit_km` when set), activity count, in-service date, photo upload/remove. Suggestions render as one-tap banners (Switch to X / Dismiss) at the top.
- Activity detail gains a shoe row: current shoe with a dropdown of active shoes to reassign (writes through to Garmin), plus the suggestion banner when one exists for that activity.
- Today's completed-workout card (`ResultCard`) shows the same one-tap banner when the shown run has an open suggestion - the mistag is caught at the moment the athlete is already looking. All three surfaces read the same suggestion state; acting on it in one clears it everywhere.

## v1.30 - daily review coach attribution (frozen at write time)

`DailyReview` gains `coach: string | null` - the `coach_style` key of the persona that WROTE today's note, stamped in `evaluate_today` at generation time (same contract as `execution_analysis_coach`, v1.21.1).
A later coach switch never re-attributes an already-written note.
`GET /api/dashboard/review` and `POST /api/dashboard/evaluate` include the field; it is null on `pending_data` rows and on rows that predate the feature (UI falls back to the current coach).

UI: the Today review note renders avatar + name from this stamp, not the current selection.
On the day of a switch (stamped coach differs from the current one) a small ⓘ next to the name explains: the old coach wrote this morning's note, and starting tomorrow the daily review comes from the new coach.
The chat header keeps reflecting the CURRENT coach - attribution ("who said this") is frozen; presence ("who am I talking to") is live.
Implemented via a generic `InfoTip` extracted from `MetricInfo` (same popover, dynamic copy) and an optional `info` prop on `CoachNote`.

## v1.31 - support activities (non-run sessions surfaced)

Non-run sessions (strength, yoga, rides, hikes…) become visible on Today and Week.
Their training load already counted toward CTL/ATL/ramp; this only surfaces them.

```ts
interface SupportActivity {
  id: number;                    // activity id — links to /activities/{id}
  type: string;                  // Garmin typeKey, e.g. "strength_training"
  name: string;
  duration_min: number | null;
  training_load?: number | null; // Today only
  rpe?: number | null;           // Today only; athlete RPE, else Garmin-logged
}
```

- `GET /api/dashboard/today` gains `support_activities: SupportActivity[]` — today's non-run activities (empty when none).
- `GET /api/plan/week` `days[]` gain `support: SupportActivity[]` — that day's non-run activities (no `training_load`/`rpe`).
- "Non-run" = the activity `type` does not contain "run", so every `…running` variant stays a run.

UI: Today renders a compact `SupportSessionCard` under the workout/result card (icon, name, type · duration · RPE, links to the activity detail); Week day rows show a small `SupportChip` (icon + duration) per session.
The review system prompt now tells the coach these are real training — acknowledge them, factor them into fatigue reasoning, never treat such a day as "did nothing", and never score them.

## v1.32 - the strength lane (Idea F Phase 2: plan it)

Strength sessions become plannable: a parallel `support_sessions` lane beside the run plan, driven by a weekly-target Settings contract.
Nothing here touches plan_days, watch push, or execution scoring.

```ts
interface StrengthSession {
  id: number;
  date: string;
  kind: "strength";
  duration_min: number | null;
  focus: string;               // "hips & glutes", "full body", …
  rationale: string;           // the coach's one-line why
  status: "planned" | "completed" | "skipped";
  source: "author" | "chat_edit" | "manual";
  activity_id: number | null;  // synced activity that auto-completed it
}
```

### Settings

`Settings` gains `strength: { sessions_per_week: number /* 0-3, 0 = off */, focus: "coach" | "full" | "upper" | "lower" }`.
Server-normalized like `cycle` (bad values fall back to defaults).

### Endpoints

- `POST /api/strength` body `{ date, duration_min?, focus? }` → `StrengthSession` - manual planned session (409 if a non-planned session already holds the date; upserts over a planned coach placement).
- `POST /api/strength/{id}/complete` → `StrengthSession` - manual "did it" (watchless sessions).
- `DELETE /api/strength/{id}` → `{ ok: true }`.
- `GET /api/dashboard/today` gains `strength_session: StrengthSession | null` (planned sessions auto-complete on read when a synced strength activity shares the date).
- `GET /api/plan/week` `days[]` gain `strength: StrengthSession | null`; `summary` gains `strength: { target, done } | null` (null = not opted in). `done` counts distinct days with a completed session or any strength activity.
- `PendingEdit` gains `strength: StrengthProposalSession[] | null` (`{date, duration_min, focus, rationale}`) - a strength-placement proposal from chat; accept via the existing `POST /api/edits/{id}/accept`.

### Coach behavior

- The snapshot gains `strength` (null until opted in): `{ target_per_week, focus_preference, done_this_week, planned_upcoming, remaining_to_plan }` - computed in code; the athlete's setting decides WHETHER, the coach only WHEN and WHAT.
- Author mode: `generate_plan`'s schema gains `strength_sessions`; placements are clamped to the remaining weekly budget and written to the lane directly (the athlete's own plan, no approval step). The daily re-plan may move its own placements but never touches manual or completed rows.
- Editor mode / chat: new `propose_strength_sessions` tool rides the PendingEdit approval queue - same contract as plan edits, nothing scheduled until accepted.
- Target is guidance, not a quota; no nagging about missed sessions; an open niggle biases focus toward prevention work.

### UI

- Settings: "Strength training" card (Off/1/2/3 + focus select, optimistic save).
- Today: planned-session card with the coach's why and a "Mark done" button; disappears when a synced activity auto-completes it (the activity shows in the support list instead).
- Week: dashed chip for a planned session (solid green when manually completed); summary line gains "1 of 2 strength".
- Proposal card renders strength placements as addition rows (no before/after diff) under the header "Proposed strength sessions".

## v1.32.1 - review-initiated strength placements + Settings mode tooltip

Closes the editor-mode gap: the daily review can now propose strength placements itself, instead of only nudging toward chat.

- `REVIEW_SCHEMA`'s `proposal` gains `strength_sessions` (same item shape as the planner's); a proposal may be strength-only (`days: []`).
- `create_pending_edit` accepts the placements and validates them against the weekly target; they land on the same `PendingEdit.strength` field, so the existing proposal card renders them with zero UI changes.
- Anti-nag guard (enforced in code, not just prompt): a strength-carrying proposal dismissed this week mutes review placements until next week; chat can still propose any time. Run-only dismissals don't mute.
- Settings: the strength card's "Sessions per week" gains an InfoTip explaining the author/editor difference (auto-placed vs proposed-for-approval) and the guidance-not-quota posture.

## v1.33 - per-user daily chat message cap (admin-configurable)

The daily chat limit becomes admin-set policy: everyone (admin included) has a cap on user-sent chat messages, default 8 per calendar day, resetting at local midnight (app timezone).
It counts chat messages only - never the system-initiated coach features (review, plan, execution analysis), and never the individual LLM calls a message fans out into.
The old hardcoded 15-per-rolling-24h member limit is gone; the 5-per-5-minutes burst guard stays (non-admin, in-memory, not configurable).
Source of truth is the `chat_messages` table, so the count survives restarts and every surface reports the same number.

### Endpoints

- `GET /api/chat/sessions` shape changed: `{ sessions: Array<{ id, created_at, title }>, quota: { used: number, cap: number | null } }` (`cap` null = unlimited).
- `POST /api/chat`: 429 with a user-ready `detail` when today's cap is used up (before any LLM spend, before the stream starts).
  The SSE stream gains a final event after `done`/`stopped`: `{ "type": "quota", "used": number, "cap": number | null }` - the post-send count, so the client updates its hint without refetching.
- `PUT /api/auth/users/{id}/chat_cap` (admin) body `{ cap: number | null }` (0-1000; null = unlimited; 0 = chat disabled for that account) → `{ user_id, chat_daily_cap, msgs_today }`.
- `GET /api/auth/usage`: `by_user` now has a row for EVERY account (zero-filled without usage) and each row gains `msgs_today` (chat messages today) and `chat_daily_cap` (number | null).
  `msgs_today` counts messages, `calls` counts LLM calls - do not conflate them in UI copy.

### UI

- Admin "By member" table: two new columns - "Msgs today" (`used / cap`) and an editable "Daily cap" (click to edit; blank or `∞` = unlimited), with a caption noting the cap covers chat messages only.
- Chat composer: quiet "N coach messages left today" hint at <= 2 remaining; at the cap the composer disables itself with "Daily limit reached - the coach is back at midnight".
- The cap is stored as a server-owned settings key: `GET/PUT /api/settings` can neither read nor write it.
