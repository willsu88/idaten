// Types mirroring API_CONTRACT.md exactly.

export type ReadinessLevel = "green" | "yellow" | "red";

export interface Readiness {
  score: number; // 0-100
  level: ReadinessLevel;
  components: {
    hrv_delta_pct: number | null; // last night vs 7d baseline, e.g. -12.3
    sleep_hours: number | null;
    sleep_score: number | null; // 0-100 (Garmin)
    body_battery: number | null; // 0-100 morning value
    tsb: number | null; // training stress balance (ctl - atl)
  };
}

export type WorkoutType =
  | "easy_run"
  | "long_run"
  | "tempo"
  | "intervals"
  | "recovery"
  | "rest"
  | "cross_train"
  | "race";

export type StepKind = "warmup" | "work" | "recovery" | "cooldown" | "rest";

export interface WorkoutStep {
  kind: StepKind;
  duration_min: number | null; // exactly one of duration/distance normally set
  distance_km: number | null;
  target_pace: string | null; // "M:SS" min/km
  target_hr_low: number | null; // bpm band (per training mode; never both pace+HR)
  target_hr_high: number | null;
  note: string; // short cue, e.g. "controlled, not all-out"
}

export interface StepBlock {
  repeat: number; // 1 = plain step(s); >1 = repeat block (e.g. 6× ...)
  steps: WorkoutStep[]; // inside a repeat: e.g. [800m work, 400m float]
}

// Menstrual cycle phase for a given date, derived from the set-once anchor.
// Present on plan days only when the athlete has cycle tracking enabled.
export type CyclePhaseName = "menstrual" | "premenstrual" | "follicular" | "luteal";

export interface CyclePhase {
  phase: CyclePhaseName;
  day_of_cycle: number; // 1-indexed
  cycle_length_days: number;
  period_length_days: number;
  days_to_next_period: number; // 1..cycle_length
  current_start_date: string; // ISO — start of the cycle this date sits in
  next_period_date: string; // ISO date
  ease_recommended: boolean; // 2-3 days pre-start or first 1-2 days of flow
  in_drift_window: boolean; // tight band around the predicted start
  show_started_prompt?: boolean; // Today only: offer the re-anchor confirm (false once confirmed/snoozed)
}

// GET /api/cycle/calendar — per-day phase for the read-only month strip.
export interface CycleCalendarDay {
  date: string;
  phase: CyclePhaseName | null; // null = tracking off
  ease_recommended: boolean;
}

export interface PlanDay {
  date: string;
  workout_type: WorkoutType;
  title: string;
  description: string;
  duration_min: number | null;
  distance_km: number | null;
  target_pace: string | null; // "5:30" min/km
  target_hr_low: number | null; // bpm (HR-band target; pace OR band, never both)
  target_hr_high: number | null; // bpm
  rationale: string;
  status: "planned" | "completed" | "skipped";
  garmin_workout_id: string | null;
  pushed_at: string | null; // ISO datetime, null = not on watch
  steps: StepBlock[] | null; // null = simple single-block workout
  // Editor mode only: this day carries an Idaten/hand edit and can be reverted
  // to the original Garmin Coach workout. Absent/false = untouched Garmin base.
  revertible?: boolean;
  // Cycle phase for this date, attached on Today/Week when tracking is on.
  cycle?: CyclePhase | null;
  // The matched run's execution score, when a run was attributed to this day
  // (status is then "completed"). Absent/null = no matched run yet.
  execution?: { score: number; source: "garmin" | "idaten" | null; activity_id: number } | null;
}

/** GET /api/plan/week `summary` — the week's load in the plan's own currency
 * (time at intensity; plans are time-based). `run_km` is an actuals-only fact
 * from completed runs, never a target. Nulls = nothing to show. */
export interface WeekSummary {
  planned_min: number | null; // sum over non-rest plan days
  done_min: number; // all completed activities in the week (any sport)
  run_km: number | null; // completed run distance
  easy_pct: number | null; // Z1+Z2 share of zone time (the 80/20 check)
}

export interface Activity {
  id: number;
  date: string;
  type: string;
  name: string;
  distance_km: number | null;
  duration_min: number | null;
  avg_hr: number | null;
  avg_pace: string | null;
  training_load: number | null;
  rpe: number | null; // athlete-entered in-app (1-10)
  garmin_rpe: number | null; // logged on the Garmin watch/app (1-10)
  feel: number | null; // logged on Garmin (1-5: Very Weak..Very Strong)
  body_battery_change: number | null; // Body Battery delta over the activity
  cadence: number | null; // avg steps/min (doubled), easy runs
  temperature_c: number | null; // at activity start (Garmin or Open-Meteo)
  hr_drift_pct: number | null; // aerobic decoupling %, first vs second half; <5 is good
  ef: number | null; // efficiency factor: (m/min) / avg HR
  // Execution score (0-100): how well the run matched the planned workout. Null
  // for runs not attributed to a plan (free runs). source: garmin = watch's own
  // compliance score, idaten = we computed it. analysis = LLM narrative (null
  // until the Today page lazily generates it for a recent scored run).
  execution_score: number | null;
  execution_score_source: "garmin" | "idaten" | null;
  execution_breakdown: ExecutionSegment[] | null;
  execution_analysis: string | null;
  execution_analysis_coach: string | null; // coach_style key that wrote the analysis
  // My thumb on the analysis; present where the analysis is rendered
  // (Today's completed_workout and the activity detail).
  analysis_feedback?: FeedbackState;
}

// --- coach-quality feedback (v1.23) — thumbs on coach output ---

/** The caller's own rating on one artifact; null = never rated. */
export type FeedbackState = { rating: 1 | -1 | null; tags: string[]; comment: string } | null;

export type FeedbackSurface = "coach_note" | "execution_analysis" | "edit_proposal";

/** One aggregated bucket in the admin quality view (counts, not rates). */
export interface FeedbackBucket {
  up: number;
  down: number;
  dismiss_reasons: number; // rating-null entries (proposal dismiss reasons)
}

/** GET /api/feedback/summary (admin only) */
export interface FeedbackSummary {
  days: number;
  by_surface: Array<FeedbackBucket & { surface: FeedbackSurface }>;
  by_user: Array<FeedbackBucket & { user_id: number }>;
  recent_negative: Array<{
    surface: FeedbackSurface;
    user_id: number;
    artifact_ref: string;
    tags: string[];
    comment: string;
    artifact_text: string;
    prompt_version: string | null;
    updated_at: string | null;
    has_context: boolean; // the frozen inputs travelled with the rating (eval case)
  }>;
}

export interface ExecutionSegment {
  label: string | null; // warmup / interval / recovery / cooldown / …
  axis: "hr" | "pace";
  target: [number, number]; // band (bpm, or m/s for pace)
  duration_s: number;
  avg_actual: number | null;
  score: number | null; // 0-100 for this segment
}

export interface ActivityDetail extends Activity {
  rpe_note: string | null;
  time_in_zones: { z1: number; z2: number; z3: number; z4: number; z5: number } | null; // seconds
  max_hr: number | null;
  calories: number | null;
  elevation_gain_m: number | null;
  start_time_local: string | null; // "2026-07-16 06:12:00"
  plan_day: PlanDay | null; // what was planned for that date, if anything
}

export interface ActivitySeries {
  series: {
    t_s: number[]; // elapsed seconds (x-axis)
    distance_m?: (number | null)[];
    hr?: (number | null)[];
    speed_mps?: (number | null)[]; // pace = 1000/speed (sec/km); plot pace inverted (faster = up)
    elevation_m?: (number | null)[];
    cadence_spm?: (number | null)[];
  } | null; // null = Garmin has no per-second data for this activity
  splits: Array<{
    index: number;
    distance_m: number | null;
    duration_s: number | null;
    avg_hr: number | null;
    max_hr: number | null;
    avg_speed_mps: number | null;
    avg_pace: string | null; // "5:30"
    elevation_gain_m: number | null;
    avg_cadence: number | null;
  }> | null;
  hr_zones: HrZones | null; // bpm bands for chart shading
  // [lat, lon] pairs, ordered, downsampled to <=500 points.
  // null = not known yet / non-GPS activity; [] = confirmed no GPS. Both mean: no map.
  route: Array<[number, number]> | null;
}

/** The athlete's HR zone bpm bands (Garmin's, or LTHR-derived). */
export interface HrZones {
  z1: [number, number];
  z2: [number, number];
  z3: [number, number];
  z4: [number, number];
  z5: [number, number];
}

export interface ActivityTypeCount {
  type: string; // exact Garmin type key, e.g. "trail_running"
  count: number;
}

/** GET /api/activities/months — months with data (newest first), for the
 * Activities month navigator/picker. */
export interface ActivityMonthCount {
  month: string; // "YYYY-MM"
  count: number;
}

export interface DayIntent {
  date: string;
  sport: string; // "surfing", "hiking", "freediving", ...
  note: string;
  duration_min: number | null;
  effort: "easy" | "moderate" | "hard" | null;
  source: "manual" | "chat";
}

export interface DailyHealth {
  date: string;
  sleep_hours: number | null;
  sleep_score: number | null;
  hrv: number | null;
  hrv_baseline: number | null;
  resting_hr: number | null;
  body_battery: number | null;
  stress_avg: number | null;
}

export interface PendingEdit {
  id: number;
  created_at: string;
  summary: string;
  rationale: string;
  changes: PlanDay[];
  current: PlanDay[];
  status: "pending" | "accepted" | "dismissed" | "superseded";
}

export type TrainingPhase = "base" | "build" | "peak" | "taper" | "race";

export interface TrainingPlanPhase {
  phase: TrainingPhase;
  label: string;
  start_date: string;
  end_date: string;
}

export interface GarminCoachTask {
  date: string;
  week: number;
  name: string;
  description: string;
  sport: string;
  duration_min: number | null;
  training_effect: string | null;
  priority: string | null;
  rest_day: boolean;
  status: string | null;
}

/** GET /api/training-plan — Garmin Coach plan mirror, or race-derived fallback. */
export interface TrainingPlanInfo {
  source: "garmin" | "derived";
  name: string;
  start_date: string;
  end_date: string;
  total_weeks: number | null;
  current_week: number | null;
  phase: TrainingPhase | null;
  phases: TrainingPlanPhase[];
  upcoming_tasks: GarminCoachTask[];
}

export interface RacePrediction {
  source: "idaten" | "garmin"; // model behind likely_s; "garmin" only when we can't yet compute our own
  likely_s: number | null; // Idaten point estimate (center of range) — the authoritative number
  low_s: number | null; // fast end of range
  high_s: number | null; // slow end of range
  confidence: "high" | "medium" | "low" | null;
  delta_s: number | null; // likely_s - goal; negative/zero = on track
  likely_pace: string | null; // min/km at likely_s
  goal_time_s: number | null;
  goal_pace: string | null; // min/km
  garmin_time_s: number | null; // Garmin's VO2max predictor, Riegel-adjusted — REFERENCE ONLY
}

export interface Race {
  id: number;
  name: string;
  date: string; // YYYY-MM-DD
  distance_km: number;
  goal_time: string; // "3:45:00" (h:mm:ss or m:ss)
  is_primary: boolean;
  days_to_race: number; // negative if past
  prediction: RacePrediction; // Idaten's own, from demonstrated performance (+ Garmin ref)
  source: "manual" | "garmin"; // garmin = auto-imported from Garmin Connect (one-way)
  course: Array<[number, number]> | null; // [lat, lon] course polyline, athlete-imported
}

// A candidate course line parsed from a My Maps link or KML/KMZ/GPX file;
// race maps often hold several (half/10K/4K) and the athlete picks one.
export interface CourseTrack {
  name: string;
  distance_km: number;
  points: Array<[number, number]>; // [lat, lon]
}

// An open pain report (v1.22). Persists until resolved; the coach's daily
// review eases the plan around it. severity 1 = niggle (minor), 2 = pain,
// 3 = injury.
export interface Niggle {
  id: number;
  body_part: string; // "left knee"
  severity: 1 | 2 | 3;
  severity_label: "niggle" | "pain" | "injury";
  onset_date: string; // ISO date
  days_open: number;
  note: string;
  show_checkin: boolean; // show the "still bothered?" check-in variant
}

export interface DashboardToday {
  date: string;
  mode: "editor" | "author"; // editor = following a Garmin Coach plan; author = Idaten writes it
  readiness: Readiness | null;
  cycle: CyclePhase | null; // today's menstrual phase (null when tracking off)
  workout: PlanDay | null;
  health: DailyHealth | null;
  pending_edit: PendingEdit | null;
  race: Race | null; // primary race
  days_to_race: number | null;
  unrated_activity: Activity | null;
  // Ambiguous run on a planned-workout day: ask if it was the attempt (null = don't ask).
  attribution_prompt: { activity_id: number; workout_label: string } | null;
  // Today's completed, plan-attributed run: the plan card gives way to this.
  completed_workout: Activity | null;
  niggles: Niggle[] | null; // open pain reports (null when nothing open - render nothing)
}

// The daily review (editor-above-the-DSW). One per user per day.
export interface DailyReview {
  date: string;
  state: "pending_data" | "done_full" | "done_structural";
  mode: "editor" | "author" | null;
  coach_note: string;
  proposal_id: number | null;
  my_feedback?: FeedbackState; // my thumb on today's note
}

export interface DashboardReview {
  review: DailyReview | null;
  data_ready: boolean; // today's sleep/HRV has synced (real content) — safe to run the review
  syncing?: boolean; // a background sync was kicked because data hasn't landed yet
  data_overdue?: boolean; // still no data well past plan_hour — show the calm state, promote "Review anyway"
}

export interface TrendPoint {
  date: string;
  hrv: number | null;
  hrv_baseline: number | null;
  resting_hr: number | null;
  sleep_hours: number | null;
  sleep_score: number | null;
  body_battery: number | null;
  ctl: number | null;
  atl: number | null;
  tsb: number | null;
  distance_km: number | null;
  training_load: number | null;
  acwr: number | null;
  vo2max: number | null;
}

export interface EfPoint {
  date: string;
  activity_id: number;
  name: string;
  ef: number;
  avg_pace: string | null;
  avg_hr: number | null;
  temperature_c: number | null;
  hr_drift_pct: number | null;
  cadence: number | null;
  distance_km: number | null;
}

export interface ZonesBucket {
  z1_s: number;
  z2_s: number;
  z3_s: number;
  z4_s: number;
  z5_s: number;
}

export interface ZonesWeek extends ZonesBucket {
  week_start: string;
}

export interface ZonesDay extends ZonesBucket {
  date: string;
}

// One day of the training-load ramp series (7-day acute vs 28-day chronic load).
export interface RampPoint {
  date: string;
  acute: number;
  chronic: number;
  ratio: number | null; // null where the base is too small to be meaningful - gap the line
}

export interface Analytics {
  ef_series: EfPoint[]; // easy/recovery/long runs only
  zones_weekly: ZonesWeek[];
  zones_daily: ZonesDay[]; // per-day buckets for the short (7-day) view
  vo2max_series: Array<{ date: string; vo2max: number }>;
  race_prediction: {
    date: string;
    time_5k_s: number | null;
    time_10k_s: number | null;
    time_half_s: number | null;
    time_marathon_s: number | null;
  } | null;
  // Garmin's predicted finish for the primary race's distance over time (Riegel-adjusted).
  race_prediction_series: Array<{ date: string; predicted_time_s: number }>;
  goal: { distance_km: number; goal_time_s: number; predicted_time_s: number | null } | null;
  // Training-load ramp guardrail: 7-day vs 28-day load, thresholds calibrated backend-side.
  ramp: {
    series: RampPoint[]; // daily, over the requested window
    caution: number; // band edge (~1.3)
    high: number; // band edge (~1.5)
    zone_today: "safe" | "caution" | "high" | null;
    chronic_trend: "building" | "flat" | "detraining" | null;
    race: { name: string; date: string } | null; // primary race, for the marker
  };
}

export interface Settings {
  athlete: { age: number | null; weekly_km: number | null; notes: string }; // only `notes` is edited now
  athlete_auto: {
    age: number | null; // from Garmin birth date
    gender: string | null; // "male" | "female"
    weight_kg: number | null;
    height_cm: number | null;
    lthr: number | null; // lactate threshold HR (bpm)
    vo2max_running: number | null;
    weekly_km_4wk: number | null; // computed 4-week average from real activities
    updated: string | null; // date the profile was last synced
  };
  llm_provider?: "anthropic" | "openai"; // present only for admins (v1.11)
  auto_push_workouts: boolean;
  plan_hour: number;
  training_mode: "pace" | "hr" | "hybrid";
  coach_style: "default" | "chill" | "strict"; // default "default"
  plan_authoring: "auto" | "author"; // auto = editor when a Garmin plan is present
  // Menstrual cycle tracking — opt-in, set-once anchor + forward projection.
  cycle: {
    enabled: boolean;
    last_start_date: string | null; // ISO date of the most recent period start
    cycle_length_days: number; // default 28
    period_length_days: number; // default 5
  };
  cycle_status?: CyclePhase | null; // today's derived phase (read-only, GET/PUT)

  tutorial_done: boolean; // default false
  page_hints_seen: string[]; // page ids whose first-run coach pointer was dismissed
}

export interface SyncStatus {
  last_run: string | null;
  last_status: "ok" | "error" | null;
  last_detail: string | null;
  running: boolean;
  backfill: { running: boolean; done_days: number; total_days: number } | null;
  garmin_connected: boolean;
}

export interface UserInfo {
  id: number;
  username: string;
  display_name: string;
  garmin_connected: boolean;
  garmin_email: string | null;
  is_admin: boolean;
}

/** GET /api/auth/members */
export type Member = UserInfo & { is_me: boolean; created_at: string };

/** One aggregated bucket in the admin usage view. */
export interface UsageBucket {
  calls: number;
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  cache_creation_tokens: number;
  cost_usd: number;
  cache_hit_pct: number;
}

/** GET /api/auth/usage (admin only) */
export interface UsageSummary {
  days: number;
  since: string;
  total: UsageBucket;
  by_user: Array<UsageBucket & { user_id: number; name: string }>;
  by_call_site: Array<UsageBucket & { call_site: string }>;
}

/** POST /api/auth/invites and POST /api/auth/users/{id}/reset_link */
export interface InviteLink {
  path: string; // "/invite/<token>" — compose full URL with window.location.origin
  expires_at: string;
}

/** GET /api/auth/invites/{token} (public) */
export type InviteStatus =
  | { valid: false }
  | { valid: true; kind: "invite" }
  | { valid: true; kind: "password_reset"; username: string };

export interface ChatSession {
  id: string;
  created_at: string;
  title: string;
}

export interface ChatMessage {
  role: "user" | "assistant";
  kind: "text" | "edit_proposed" | "shortcut"; // "shortcut": user message that matched a slash command
  content: string; // for kind "text": the markdown message; for "shortcut": the raw typed command
  created_at: string;
  edit?: PendingEdit; // present when kind === "edit_proposed"
}

export type ChatEvent =
  | { type: "session"; session_id: string }
  | { type: "text"; delta: string }
  | { type: "tool"; name: string; status: "running" | "done" }
  | { type: "edit_proposed"; edit: PendingEdit }
  | { type: "done" }
  | { type: "stopped" } // terminal, like "done": the server stopped the stream on request
  | { type: "error"; message: string };
