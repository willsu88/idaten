import type {
  Activity,
  ActivityDetail,
  ActivityMonthCount,
  ActivitySeries,
  ActivityTypeCount,
  Analytics,
  ChatEvent,
  ChatMessage,
  ChatSession,
  CourseTrack,
  CycleCalendarDay,
  DailyReview,
  DashboardReview,
  DashboardToday,
  DayIntent,
  FeedbackState,
  FeedbackSummary,
  FeedbackSurface,
  GearItem,
  GearSuggestion,
  HrZones,
  InviteLink,
  InviteStatus,
  Member,
  Niggle,
  PendingEdit,
  PlanDay,
  Race,
  Settings,
  StrengthSession,
  SyncStatus,
  TrainingPlanInfo,
  TrendPoint,
  UsageSummary,
  UserInfo,
  WeekSummary,
} from "./types";

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

/**
 * On any 401 (session missing/expired) send the user to /login.
 * Skipped for auth endpoints where 401 has a domain meaning
 * (bad credentials, wrong current password).
 */
function redirectToLogin() {
  if (typeof window !== "undefined" && window.location.pathname !== "/login") {
    window.location.href = "/login";
  }
}

/** Pull a human-readable message out of an error response body, if any. */
async function errorMessage(res: Response): Promise<string> {
  try {
    const body = (await res.json()) as { detail?: unknown; message?: unknown; error?: unknown };
    const msg = body.detail ?? body.message ?? body.error;
    if (typeof msg === "string" && msg) return msg;
  } catch {
    // non-JSON body
  }
  return `API ${res.status}`;
}

async function request<T>(
  path: string,
  init?: RequestInit,
  opts?: { skip401Redirect?: boolean },
): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
    cache: "no-store",
  });
  if (!res.ok) {
    if (res.status === 401 && !opts?.skip401Redirect) {
      redirectToLogin();
    }
    throw new ApiError(res.status, await errorMessage(res));
  }
  return (await res.json()) as T;
}

/** Like request(), but resolves to null instead of throwing (for page loads). */
export async function safe<T>(p: Promise<T>): Promise<T | null> {
  try {
    return await p;
  } catch {
    return null;
  }
}

export const api = {
  // --- auth ---
  login: (username: string, password: string) =>
    request<{ ok: boolean; user: UserInfo }>(
      "/api/auth/login",
      { method: "POST", body: JSON.stringify({ username, password }) },
      { skip401Redirect: true },
    ),

  logout: () => request<{ ok: true }>("/api/auth/logout", { method: "POST" }),

  authMe: () => request<UserInfo>("/api/auth/me"),

  // 1-40 chars after trim; 422 otherwise. Only affects the current user.
  updateProfile: (display_name: string) =>
    request<UserInfo>("/api/auth/profile", {
      method: "POST",
      body: JSON.stringify({ display_name }),
    }),

  members: () => request<Member[]>("/api/auth/members"),

  usage: (days = 30) => request<UsageSummary>(`/api/auth/usage?days=${days}`),

  createInvite: () => request<InviteLink>("/api/auth/invites", { method: "POST" }),

  createResetLink: (id: number) =>
    request<InviteLink>(`/api/auth/users/${id}/reset_link`, { method: "POST" }),

  deleteUser: (id: number) => request<{ ok: true }>(`/api/auth/users/${id}`, { method: "DELETE" }),

  // Public (no session): the /invite/[token] page must never bounce to /login.
  inviteStatus: (token: string) =>
    request<InviteStatus>(
      `/api/auth/invites/${encodeURIComponent(token)}`,
      undefined,
      { skip401Redirect: true },
    ),

  // Public: invite kind takes { username, password, display_name? }; reset kind takes { password }.
  acceptInvite: (
    token: string,
    body: { username: string; password: string; display_name?: string } | { password: string },
  ) =>
    request<{ ok: boolean; user: UserInfo }>(
      `/api/auth/invites/${encodeURIComponent(token)}/accept`,
      { method: "POST", body: JSON.stringify(body) },
      { skip401Redirect: true },
    ),

  changePassword: (body: { current_password: string; new_password: string }) =>
    request<{ ok: boolean }>(
      "/api/auth/password",
      { method: "POST", body: JSON.stringify(body) },
      { skip401Redirect: true }, // 401 here means "current password is wrong"
    ),

  garminConnect: (email: string, password: string) =>
    request<{ ok: boolean; onboarding_started: boolean }>("/api/garmin/connect", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),

  dashboardToday: () => request<DashboardToday>("/api/dashboard/today"),

  // Daily review: cheap poll for state, and the lazy trigger for the one LLM call.
  dashboardReview: () => request<DashboardReview>("/api/dashboard/review"),

  dashboardEvaluate: (allowStructural = false) =>
    request<DailyReview>("/api/dashboard/evaluate", {
      method: "POST",
      body: JSON.stringify({ allow_structural: allowStructural }),
    }),

  planWeek: (start?: string) =>
    request<{ mode: "editor" | "author"; summary: WeekSummary; days: PlanDay[] }>(
      `/api/plan/week${start ? `?start=${start}` : ""}`,
    ),

  // Single plan day for the preview/detail page (/plan/[date]).
  planDay: (date: string) =>
    request<{
      mode: "editor" | "author" | null;
      day: PlanDay | null;
      intent: DayIntent | null;
      hr_zones: HrZones | null;
    }>(`/api/plan/day?date=${date}`),

  // Replace an Idaten edit with the original Garmin Coach workout (editor mode).
  revertToGarmin: (arg: { date: string } | { week: true; start?: string }) =>
    request<{ reverted: string[] }>("/api/dashboard/revert-to-garmin", {
      method: "POST",
      body: JSON.stringify(
        "date" in arg
          ? { scope: "day", date: arg.date }
          : { scope: "week", start: arg.start },
      ),
    }),

  pushWorkout: (date: string) =>
    request<{ ok: true; garmin_workout_id: string }>("/api/plan/push", {
      method: "POST",
      body: JSON.stringify({ date }),
    }),

  pushWeek: (start?: string) =>
    request<{ ok: boolean; pushed: number }>("/api/plan/push_week", {
      method: "POST",
      body: JSON.stringify(start ? { start } : {}),
    }),

  unpushWorkout: (date: string) =>
    request<{ ok: true }>("/api/plan/unpush", {
      method: "POST",
      body: JSON.stringify({ date }),
    }),

  unpushWeek: (start?: string) =>
    request<{ ok: boolean; removed: number }>("/api/plan/unpush_week", {
      method: "POST",
      body: JSON.stringify(start ? { start } : {}),
    }),

  intents: (start: string, end: string) =>
    request<DayIntent[]>(`/api/intents?start=${start}&end=${end}`),

  putIntent: (
    date: string,
    body: {
      sport: string;
      note?: string;
      duration_min?: number;
      effort?: "easy" | "moderate" | "hard";
    },
  ) =>
    request<DayIntent>(`/api/intents/${date}`, { method: "PUT", body: JSON.stringify(body) }),

  deleteIntent: (date: string) =>
    request<{ ok: true }>(`/api/intents/${date}`, { method: "DELETE" }),

  addStrength: (body: { date: string; duration_min?: number | null; focus?: string }) =>
    request<StrengthSession>("/api/strength", { method: "POST", body: JSON.stringify(body) }),

  completeStrength: (id: number) =>
    request<StrengthSession>(`/api/strength/${id}/complete`, { method: "POST" }),

  deleteStrength: (id: number) =>
    request<{ ok: true }>(`/api/strength/${id}`, { method: "DELETE" }),

  backfill: (days: number) =>
    request<{ ok: true; started: true }>("/api/backfill", {
      method: "POST",
      body: JSON.stringify({ days }),
    }),

  analytics: (days: number) => request<Analytics>(`/api/analytics?days=${days}`),

  trends: (days: number) => request<{ daily: TrendPoint[] }>(`/api/trends?days=${days}`),

  activities: (limit = 20, offset = 0, type?: string, days?: number, month?: string) =>
    request<Activity[]>(
      `/api/activities?limit=${limit}&offset=${offset}` +
        `${type ? `&type=${encodeURIComponent(type)}` : ""}${days ? `&days=${days}` : ""}` +
        `${month ? `&month=${month}` : ""}`,
    ),

  activityTypes: () => request<ActivityTypeCount[]>("/api/activities/types"),

  activityMonths: () => request<ActivityMonthCount[]>("/api/activities/months"),

  activityDetail: (id: number) => request<ActivityDetail>(`/api/activities/${id}`),

  activitySeries: (id: number) => request<ActivitySeries>(`/api/activities/${id}/series`),

  // Lazily generate (once) + fetch the execution-analysis narrative for a run.
  activityAnalysis: (id: number) =>
    request<{ analysis: string; coach: string | null }>(`/api/activities/${id}/analysis`, {
      method: "POST",
    }),

  rateActivity: (id: number, rating: number, note?: string) =>
    request<{ ok: true }>(`/api/activities/${id}/rpe`, {
      method: "POST",
      body: JSON.stringify({ rating, ...(note ? { note } : {}) }),
    }),

  attributeActivity: (id: number, attempted: boolean) =>
    request<{ ok: true; execution_score: number | null }>(
      `/api/activities/${id}/attribution`,
      { method: "POST", body: JSON.stringify({ attempted }) },
    ),

  // --- gear (shoes) ---
  gear: () => request<GearItem[]>("/api/gear"),

  // On-demand Garmin mirror refresh (first visit / manual refresh; can take a
  // few seconds — one Garmin call per shoe).
  gearRefresh: () => request<GearItem[]>("/api/gear/refresh", { method: "POST" }),

  gearSuggestions: () => request<GearSuggestion[]>("/api/gear/suggestions"),

  // Swaps the shoe on Garmin itself (null = remove the shoe from the run).
  setActivityGear: (id: number, gear_uuid: string | null) =>
    request<{ ok: true; gear_uuid: string | null }>(`/api/activities/${id}/gear`, {
      method: "PUT",
      body: JSON.stringify({ gear_uuid }),
    }),

  dismissGearSuggestion: (id: number) =>
    request<{ ok: true }>(`/api/activities/${id}/gear/dismiss`, { method: "POST" }),

  // multipart — bypasses request() so the browser sets the boundary header
  uploadGearImage: async (uuid: string, file: File): Promise<GearItem> => {
    const form = new FormData();
    form.append("file", file);
    const res = await fetch(`/api/gear/${uuid}/image`, {
      method: "POST",
      body: form,
      cache: "no-store",
    });
    if (!res.ok) {
      if (res.status === 401) redirectToLogin();
      throw new ApiError(res.status, await errorMessage(res));
    }
    return (await res.json()) as GearItem;
  },

  deleteGearImage: (uuid: string) =>
    request<GearItem>(`/api/gear/${uuid}/image`, { method: "DELETE" }),

  races: (includePast = false) =>
    request<Race[]>(`/api/races${includePast ? "?include_past=true" : ""}`),

  createRace: (body: {
    name: string;
    date: string;
    distance_km: number;
    goal_time?: string; // optional in the wizard's minimal form
    is_primary?: boolean;
  }) => request<Race>("/api/races", { method: "POST", body: JSON.stringify(body) }),

  updateRace: (
    id: number,
    body: Partial<{
      name: string;
      date: string;
      distance_km: number;
      goal_time: string;
      is_primary: boolean;
    }>,
  ) => request<Race>(`/api/races/${id}`, { method: "PUT", body: JSON.stringify(body) }),

  deleteRace: (id: number) => request<{ ok: true }>(`/api/races/${id}`, { method: "DELETE" }),

  // Course source -> candidate tracks (stateless; save the picked one below).
  coursePreview: (body: { url?: string; content_b64?: string }) =>
    request<{ tracks: CourseTrack[] }>("/api/races/course/preview", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  setRaceCourse: (id: number, course: Array<[number, number]>) =>
    request<Race>(`/api/races/${id}/course`, {
      method: "PUT",
      body: JSON.stringify({ course }),
    }),

  clearRaceCourse: (id: number) =>
    request<Race>(`/api/races/${id}/course`, { method: "DELETE" }),

  trainingPlan: () => request<TrainingPlanInfo | null>("/api/training-plan"),

  setPrimaryRace: (id: number) =>
    request<{ ok: true }>(`/api/races/${id}/primary`, { method: "POST" }),

  getSettings: () => request<Settings>("/api/settings"),

  // The API merges per-key: send only the keys you mean to change so a stale
  // full-object PUT can't clobber another surface's concurrent write.
  putSettings: (settings: Partial<Settings>) =>
    request<Settings>("/api/settings", { method: "PUT", body: JSON.stringify(settings) }),

  // Re-anchor the cycle to an observed period start (drift self-correction).
  // Returns the full settings payload (with a recomputed cycle_status).
  cycleStarted: (date?: string) =>
    request<Settings>("/api/cycle/started", {
      method: "POST",
      body: JSON.stringify({ date: date ?? null }),
    }),

  // "Not yet" — hide the drift prompt for the rest of today.
  cycleSnooze: () => request<{ ok: true }>("/api/cycle/snooze", { method: "POST" }),

  cycleCalendar: (months = 3) =>
    request<{ start: string; end: string; days: CycleCalendarDay[] }>(
      `/api/cycle/calendar?months=${months}`,
    ),

  // --- niggles (open pain reports) ---
  niggles: () => request<{ niggles: Niggle[] }>("/api/niggles"),

  // Logging an already-open body part updates that entry (no duplicates).
  createNiggle: (body: {
    body_part: string;
    severity: 1 | 2 | 3;
    note?: string;
    onset_date?: string; // defaults to today server-side; never in the future
  }) => request<{ niggle: Niggle }>("/api/niggles", { method: "POST", body: JSON.stringify(body) }),

  resolveNiggle: (id: number) =>
    request<{ ok: true }>(`/api/niggles/${id}/resolve`, { method: "POST" }),

  // "Still sore" - keeps it open and re-arms the check-in window.
  checkinNiggle: (id: number) =>
    request<{ ok: true }>(`/api/niggles/${id}/checkin`, { method: "POST" }),

  // --- coach-quality feedback (thumbs) ---
  // Upserts: re-rating the same artifact updates in place. rating null =
  // dismiss-reason-only (edit_proposal surface).
  postFeedback: (body: {
    surface: FeedbackSurface;
    ref: string;
    rating: 1 | -1 | null;
    tags?: string[];
    comment?: string;
  }) =>
    request<{ feedback: FeedbackState }>("/api/feedback", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  feedbackSummary: (days = 90) => request<FeedbackSummary>(`/api/feedback/summary?days=${days}`),

  sync: () =>
    request<{ ok: boolean; started?: boolean; already_running?: boolean }>("/api/sync", {
      method: "POST",
    }),

  syncStatus: () => request<SyncStatus>("/api/sync/status"),

  pendingEdit: () => request<PendingEdit | null>("/api/edits/pending"),

  acceptEdit: (id: number) => request<{ ok: true }>(`/api/edits/${id}/accept`, { method: "POST" }),

  dismissEdit: (id: number) =>
    request<{ ok: true }>(`/api/edits/${id}/dismiss`, { method: "POST" }),

  chatSessions: () => request<ChatSession[]>("/api/chat/sessions"),

  chatHistory: (sessionId: string) =>
    request<ChatMessage[]>(`/api/chat/history?session_id=${encodeURIComponent(sessionId)}`),
};

/**
 * Ask the server to stop the current chat stream. The client keeps reading
 * the stream until the terminal "stopped" event arrives (the server persists
 * the partial reply first) — never abort the fetch.
 */
export function stopChat(): Promise<{ ok: true; stopping: boolean }> {
  return request<{ ok: true; stopping: boolean }>("/api/chat/stop", { method: "POST" });
}

/**
 * POST /api/chat and consume the SSE stream via fetch + ReadableStream.
 * Calls onEvent for each parsed `data:` JSON payload.
 */
export async function streamChat(
  body: { session_id?: string; message: string; context_date?: string },
  onEvent: (event: ChatEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (res.status === 401) {
    redirectToLogin();
    throw new ApiError(401, "Not logged in");
  }
  if (!res.ok || !res.body) {
    // 400 (message too long) / 429 (rate limit) arrive BEFORE the SSE stream
    // starts, with a user-ready `detail` sentence — preserve it for the UI.
    throw new ApiError(res.status, await errorMessage(res));
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  const handleChunk = (chunk: string) => {
    buffer += chunk;
    // SSE events are separated by a blank line.
    let sep: number;
    while ((sep = buffer.indexOf("\n\n")) !== -1) {
      const raw = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);
      for (const line of raw.split("\n")) {
        const trimmed = line.trim();
        if (!trimmed.startsWith("data:")) continue;
        const payload = trimmed.slice(5).trim();
        if (!payload) continue;
        try {
          onEvent(JSON.parse(payload) as ChatEvent);
        } catch {
          // ignore malformed events
        }
      }
    }
  };

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    handleChunk(decoder.decode(value, { stream: true }));
  }
  handleChunk(decoder.decode());
}
