import type { HrZones, PlanDay, ReadinessLevel, StepBlock, StepKind, WorkoutStep, WorkoutType } from "./types";

export type ZoneKey = "z1" | "z2" | "z3" | "z4" | "z5";

/** Short name for each HR zone (Friel-style running zones). */
export const ZONE_LABELS: Record<ZoneKey, string> = {
  z1: "Recovery",
  z2: "Aerobic base",
  z3: "Tempo",
  z4: "Threshold",
  z5: "VO₂ max",
};

const ZONE_ORDER: ZoneKey[] = ["z1", "z2", "z3", "z4", "z5"];

/** Zone colors (mirrors analytics-charts, kept dependency-free for light imports). */
export const ZONE_COLORS: Record<ZoneKey, string> = {
  z1: "#3b82f6",
  z2: "#06b6d4",
  z3: "#eab308",
  z4: "#f97316",
  z5: "#ef4444",
};

/** The zone whose band contains `bpm` (clamped to the ends). */
export function zoneForHr(zones: HrZones, bpm: number): ZoneKey {
  for (const z of ZONE_ORDER) {
    const [lo, hi] = zones[z];
    if (bpm < hi) return bpm < lo && z === "z1" ? "z1" : z;
  }
  return "z5";
}

/**
 * The zone a whole-run HR target sits in — by the midpoint of the band, so a
 * band straddling a boundary resolves to where most of the effort lives.
 */
export function primaryZoneForHr(zones: HrZones, low: number, high: number): ZoneKey {
  return zoneForHr(zones, (low + high) / 2);
}

/** One-line effort descriptor per workout type (a stat-tile value). */
export const WORKOUT_EFFORT_LABEL: Record<WorkoutType, string> = {
  easy_run: "Easy",
  long_run: "Easy–moderate",
  tempo: "Comfortably hard",
  intervals: "Hard",
  recovery: "Very easy",
  rest: "Rest",
  cross_train: "Aerobic",
  race: "Race effort",
};

/** A sentence on what this kind of run is FOR — the "what type of run" preview. */
export const WORKOUT_PURPOSE: Record<WorkoutType, string> = {
  easy_run:
    "Easy aerobic run. Comfortable, conversational effort that builds your base and keeps you fresh — never a day to push the pace.",
  long_run:
    "Long run. Sustained time on feet to build aerobic endurance and fatigue resistance — the engine behind your race fitness.",
  tempo:
    "Tempo run. A sustained, comfortably-hard effort near threshold that raises the pace you can hold for a long time.",
  intervals:
    "Intervals. Repeated hard efforts with recovery between them to sharpen speed and lift your VO₂ max.",
  recovery:
    "Recovery run. Deliberately short and very easy — it flushes fatigue and keeps you moving without adding stress.",
  rest: "Rest day. Recovery is where the training adapts — no run planned.",
  cross_train:
    "Cross-training. Non-impact aerobic work that builds fitness while sparing your legs.",
  race: "Race. The target event — execute your pacing and fueling plan.",
};

/**
 * Intensity target of a plan day: pace ("@ 5:30 /km") or, when pace is null,
 * the HR band ("HR 140–155"). A day has pace OR an HR band, never both.
 */
export function workoutTargetLabel(workout: PlanDay): string | null {
  if (workout.target_pace) return `@ ${workout.target_pace} /km`;
  if (workout.target_hr_low != null && workout.target_hr_high != null) {
    return `HR ${workout.target_hr_low}–${workout.target_hr_high}`;
  }
  return null;
}

/** Human label per step kind (expanded step list). */
export const STEP_KIND_LABELS: Record<StepKind, string> = {
  warmup: "Warm-up",
  work: "Work",
  recovery: "Recovery",
  cooldown: "Cool-down",
  rest: "Rest",
};

/** Target chip for a workout step: "4:45/km" or "148–158 bpm". */
export function stepTargetLabel(step: WorkoutStep): string | null {
  if (step.target_pace) return `${step.target_pace}/km`;
  if (step.target_hr_low != null && step.target_hr_high != null) {
    return `${step.target_hr_low}–${step.target_hr_high} bpm`;
  }
  return null;
}

/** End-condition chip for a workout step: "800 m" / "5 km" / "12 min". */
export function stepEndLabel(step: WorkoutStep): string | null {
  if (step.distance_km != null) {
    return step.distance_km < 1
      ? `${Math.round(step.distance_km * 1000)} m`
      : `${Number(step.distance_km.toFixed(2))} km`;
  }
  if (step.duration_min != null) return `${Number(step.duration_min.toFixed(1))} min`;
  return null;
}

// --- Compact one-line summary (week view + pending-edit diff cards) ---

const STEP_KIND_ABBR: Partial<Record<StepKind, string>> = {
  warmup: "WU",
  cooldown: "CD",
  rest: "Rest",
};

function compactEnd(step: WorkoutStep): string | null {
  if (step.distance_km != null) {
    return step.distance_km < 1
      ? `${Math.round(step.distance_km * 1000)}m`
      : `${Number(step.distance_km.toFixed(2))}km`;
  }
  if (step.duration_min != null) return `${Number(step.duration_min.toFixed(1))}'`;
  return null;
}

function compactStep(step: WorkoutStep): string {
  const parts: string[] = [];
  const abbr = STEP_KIND_ABBR[step.kind];
  if (abbr) parts.push(abbr);
  const end = compactEnd(step);
  if (end) parts.push(end);
  if (step.target_pace) {
    parts.push(`@ ${step.target_pace}`);
  } else if (step.target_hr_low != null && step.target_hr_high != null) {
    parts.push(`@ ${step.target_hr_low}–${step.target_hr_high}bpm`);
  } else if (step.note) {
    parts.push(step.note);
  }
  return parts.join(" ");
}

/**
 * Compact one-liner for a structured workout, e.g.
 * "WU 15' · 6×(800m @ 4:45 + 400m float) · CD 10'".
 */
export function compactStepsSummary(steps: StepBlock[]): string {
  return steps
    .map((block) =>
      block.repeat > 1
        ? `${block.repeat}×(${block.steps.map(compactStep).join(" + ")})`
        : block.steps.map(compactStep).join(" · "),
    )
    .join(" · ");
}

// --- Effort-profile timeline (plan preview page) ---

/** Parse a "M:SS" min/km pace into minutes-per-km; null if unparseable. */
function paceToMinPerKm(pace: string | null): number | null {
  if (!pace) return null;
  const m = /^(\d+):(\d{1,2})$/.exec(pace.trim());
  if (!m) return null;
  const min = Number(m[1]);
  const sec = Number(m[2]);
  if (Number.isNaN(min) || Number.isNaN(sec)) return null;
  return min + sec / 60;
}

// Nominal easy pace (min/km) used only to give a distance-only step SOME width
// on the timeline when neither its own nor the workout's pace is known.
const NOMINAL_PACE_MIN_PER_KM = 6;

export interface TimelineSegment {
  kind: StepKind;
  min: number; // derived duration
  approximate: boolean; // true when time was estimated (distance-only, no pace)
}

export interface WorkoutBreakdown {
  totalMin: number;
  workMin: number;
  recoveryMin: number;
  warmupMin: number;
  cooldownMin: number;
  segments: TimelineSegment[]; // repeats expanded, in order
}

/**
 * Expand a structured workout into per-step timeline segments and per-kind
 * totals. Per-step time: `duration_min` if set; else `distance_km` × pace
 * (step pace, else the workout-level pace); else distance-only at a nominal
 * pace (flagged approximate); else equal weight (1 min) as a last resort.
 */
export function workoutBreakdown(
  steps: StepBlock[],
  workoutPace: string | null = null,
): WorkoutBreakdown {
  const workoutPaceMin = paceToMinPerKm(workoutPace);
  const segments: TimelineSegment[] = [];

  for (const block of steps) {
    const reps = Math.max(1, block.repeat);
    for (let r = 0; r < reps; r++) {
      for (const step of block.steps) {
        let min: number;
        let approximate = false;
        if (step.duration_min != null) {
          min = step.duration_min;
        } else if (step.distance_km != null) {
          const paceMin = paceToMinPerKm(step.target_pace) ?? workoutPaceMin;
          if (paceMin != null) {
            min = step.distance_km * paceMin;
          } else {
            min = step.distance_km * NOMINAL_PACE_MIN_PER_KM;
            approximate = true;
          }
        } else {
          min = 1; // no end condition given — equal-weight fallback
          approximate = true;
        }
        segments.push({ kind: step.kind, min, approximate });
      }
    }
  }

  const sumKind = (kind: StepKind) =>
    segments.filter((s) => s.kind === kind).reduce((acc, s) => acc + s.min, 0);

  return {
    totalMin: segments.reduce((acc, s) => acc + s.min, 0),
    workMin: sumKind("work"),
    recoveryMin: sumKind("recovery") + sumKind("rest"),
    warmupMin: sumKind("warmup"),
    cooldownMin: sumKind("cooldown"),
    segments,
  };
}

export const WORKOUT_LABELS: Record<WorkoutType, string> = {
  easy_run: "Easy run",
  long_run: "Long run",
  tempo: "Tempo",
  intervals: "Intervals",
  recovery: "Recovery",
  rest: "Rest",
  cross_train: "Cross-train",
  race: "Race",
};

/** Badge classes per workout type; tuned for both light and dark themes. */
export const WORKOUT_BADGE_CLASSES: Record<WorkoutType, string> = {
  easy_run: "bg-sky-500/15 text-sky-600 dark:text-sky-400",
  long_run: "bg-indigo-500/15 text-indigo-600 dark:text-indigo-400",
  tempo: "bg-orange-500/15 text-orange-600 dark:text-orange-400",
  intervals: "bg-rose-500/15 text-rose-600 dark:text-rose-400",
  recovery: "bg-teal-500/15 text-teal-600 dark:text-teal-400",
  rest: "bg-muted text-muted-foreground",
  cross_train: "bg-violet-500/15 text-violet-600 dark:text-violet-400",
  race: "bg-amber-500/20 text-amber-600 dark:text-amber-400",
};

/** Accent bar color per workout type (left edge of cards). */
export const WORKOUT_BAR_CLASSES: Record<WorkoutType, string> = {
  easy_run: "bg-sky-500",
  long_run: "bg-indigo-500",
  tempo: "bg-orange-500",
  intervals: "bg-rose-500",
  recovery: "bg-teal-500",
  rest: "bg-border",
  cross_train: "bg-violet-500",
  race: "bg-amber-500",
};

export const READINESS_CLASSES: Record<
  ReadinessLevel,
  { text: string; stroke: string; bg: string; label: string }
> = {
  green: {
    text: "text-success",
    stroke: "hsl(var(--success))",
    bg: "bg-success/10",
    label: "Ready to train",
  },
  yellow: {
    text: "text-warning",
    stroke: "hsl(var(--warning))",
    bg: "bg-warning/10",
    label: "Take it steady",
  },
  red: {
    text: "text-danger",
    stroke: "hsl(var(--danger))",
    bg: "bg-danger/10",
    label: "Prioritize recovery",
  },
};
