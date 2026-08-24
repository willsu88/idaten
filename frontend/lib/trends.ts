// Pure derivation logic behind the Trends page: the glanceable tile tier and
// the weekly aggregations its charts plot. Everything here is computed from the
// /api/trends and /api/analytics payloads - no fetching, no React.
import type { Analytics, RampPoint, TrendPoint, ZonesBucket } from "./types";

export type Tone = "success" | "warning" | "danger";
export type Direction = "up" | "down" | "flat";

export interface TrendTile {
  key: "recovery" | "load" | "progress" | "sleep";
  label: string;
  value: string;
  sub?: string;
  tone: Tone | null;
  direction: Direction | null;
  spark: number[];
}

/** ISO week key like "2026-W34" and its Monday date for labeling. */
export function isoWeekOf(dateStr: string): { key: string; monday: string } {
  const d = new Date(`${dateStr}T00:00:00`);
  const day = (d.getDay() + 6) % 7; // Mon = 0
  const monday = new Date(d);
  monday.setDate(d.getDate() - day);
  const thursday = new Date(monday);
  thursday.setDate(monday.getDate() + 3);
  const yearStart = new Date(thursday.getFullYear(), 0, 1);
  const week = Math.ceil(((thursday.getTime() - yearStart.getTime()) / 86400000 + 1) / 7);
  const mondayStr = `${monday.getFullYear()}-${String(monday.getMonth() + 1).padStart(2, "0")}-${String(monday.getDate()).padStart(2, "0")}`;
  return { key: `${thursday.getFullYear()}-W${String(week).padStart(2, "0")}`, monday: mondayStr };
}

export function aggregateWeeklyDistance(daily: TrendPoint[]) {
  const weeks = new Map<string, { week: string; monday: string; distance_km: number }>();
  for (const p of daily) {
    if (p.distance_km == null) continue;
    const { key, monday } = isoWeekOf(p.date);
    const entry = weeks.get(key) ?? { week: key, monday, distance_km: 0 };
    entry.distance_km += p.distance_km;
    weeks.set(key, entry);
  }
  return Array.from(weeks.values())
    .sort((a, b) => a.monday.localeCompare(b.monday))
    .map((w) => ({ ...w, distance_km: Math.round(w.distance_km * 10) / 10 }));
}

export function easySharePct(buckets: ZonesBucket[]): number | null {
  let easy = 0;
  let total = 0;
  for (const b of buckets) {
    easy += b.z1_s + b.z2_s;
    total += b.z1_s + b.z2_s + b.z3_s + b.z4_s + b.z5_s;
  }
  if (total === 0) return null;
  return Math.round((easy / total) * 100);
}

/** Easy (Z1+Z2) vs hard (Z3-Z5) hours per bucket, for the 80/20 chart. */
export function easyHardWeekly(buckets: Array<ZonesBucket & { start: string }>) {
  return [...buckets]
    .sort((a, b) => a.start.localeCompare(b.start))
    .map((b) => {
      const easy = b.z1_s + b.z2_s;
      const hard = b.z3_s + b.z4_s + b.z5_s;
      const total = easy + hard;
      return {
        start: b.start,
        easy_h: Math.round((easy / 3600) * 100) / 100,
        hard_h: Math.round((hard / 3600) * 100) / 100,
        easyPct: total === 0 ? null : Math.round((easy / total) * 100),
      };
    });
}

/** Last `n` non-null values of one metric, oldest first. */
export function sparkSeries(daily: TrendPoint[], key: keyof TrendPoint, n = 14): number[] {
  const values = daily
    .map((p) => p[key])
    .filter((v): v is number => typeof v === "number");
  return values.slice(-n);
}

/**
 * Direction of a series for a tile arrow: last-3 mean vs the mean of what came
 * before, with a relative deadband so noise reads as "flat".
 */
export function trendDirection(values: number[], deadbandPct = 3): Direction | null {
  if (values.length < 4) return null;
  const recent = values.slice(-3);
  const prior = values.slice(0, -3);
  const mean = (xs: number[]) => xs.reduce((s, x) => s + x, 0) / xs.length;
  const base = mean(prior);
  if (base === 0) return null;
  const deltaPct = ((mean(recent) - base) / Math.abs(base)) * 100;
  if (deltaPct > deadbandPct) return "up";
  if (deltaPct < -deadbandPct) return "down";
  return "flat";
}

/**
 * Ramp chart y-ceiling: the fixed 2.0 scale unless the data exceeds it, in
 * which case the axis grows so the line is never plotted below its true value.
 */
export function rampYMax(series: RampPoint[]): number {
  let max = 0;
  for (const p of series) if (p.ratio != null && p.ratio > max) max = p.ratio;
  return Math.max(2, Math.ceil(max * 10) / 10);
}

function latest<T>(daily: TrendPoint[], pick: (p: TrendPoint) => T | null): T | null {
  for (let i = daily.length - 1; i >= 0; i--) {
    const v = pick(daily[i]);
    if (v != null) return v;
  }
  return null;
}

const EMPTY = { value: "–", tone: null, direction: null } as const;

/** The four glanceable tiles at the top of Trends. `daily` is in date order. */
export function deriveTrendTiles(daily: TrendPoint[], analytics: Analytics | null): TrendTile[] {
  // Recovery: latest night with both HRV and its baseline, same thresholds as
  // the Today readiness card so the two surfaces never disagree.
  const hrvPoint = latest(daily, (p) => (p.hrv != null && p.hrv_baseline != null ? p : null));
  const hrvSpark = sparkSeries(daily, "hrv");
  let recovery: TrendTile = { key: "recovery", label: "Recovery", spark: hrvSpark, ...EMPTY };
  if (hrvPoint && hrvPoint.hrv_baseline !== 0) {
    const deltaPct = ((hrvPoint.hrv! - hrvPoint.hrv_baseline!) / hrvPoint.hrv_baseline!) * 100;
    recovery = {
      ...recovery,
      value: `${deltaPct > 0 ? "+" : ""}${deltaPct.toFixed(1)}%`,
      sub: "vs baseline",
      tone: deltaPct < -8 ? "danger" : deltaPct < -3 ? "warning" : "success",
      direction: trendDirection(hrvSpark),
    };
  }

  // Load: the ramp verdict is already a word - surface it as the value so the
  // tile answers "am I building safely?" without a number to interpret.
  const ramp = analytics?.ramp ?? null;
  const ratios = (ramp?.series ?? [])
    .map((p) => p.ratio)
    .filter((r): r is number => r != null)
    .slice(-14);
  let load: TrendTile = { key: "load", label: "Load", spark: ratios, ...EMPTY };
  if (ramp) {
    const lastRatio = ratios.length > 0 ? ratios[ratios.length - 1] : null;
    const sub = lastRatio == null ? undefined : `ratio ${lastRatio.toFixed(2)}`;
    if (ramp.chronic_trend === "detraining") {
      load = { ...load, value: "Detraining", sub, tone: "warning" };
    } else if (ramp.zone_today === "high") {
      load = { ...load, value: "High", sub, tone: "danger" };
    } else if (ramp.zone_today === "caution") {
      load = { ...load, value: "Caution", sub, tone: "warning" };
    } else if (ramp.zone_today === "safe") {
      load = { ...load, value: "Safe", sub, tone: "success" };
    }
  }

  // Progress: latest VO2max; the arrow is the signal, so the tone follows it.
  const vo2 = latest(daily, (p) => p.vo2max);
  const vo2Spark = sparkSeries(daily, "vo2max");
  const vo2Dir = trendDirection(vo2Spark, 1); // VO2max moves slowly - tight deadband
  let progress: TrendTile = { key: "progress", label: "VO2max", spark: vo2Spark, ...EMPTY };
  if (vo2 != null) {
    progress = {
      ...progress,
      value: vo2.toFixed(1),
      direction: vo2Dir,
      tone: vo2Dir === "up" ? "success" : vo2Dir === "down" ? "warning" : null,
    };
  }

  // Sleep: last night's duration, toned by Garmin's score qualifiers
  // (>=80 good, 60-79 fair, <60 poor).
  const sleepPoint = latest(daily, (p) => (p.sleep_hours != null ? p : null));
  const sleepSpark = sparkSeries(daily, "sleep_hours");
  let sleep: TrendTile = { key: "sleep", label: "Sleep", spark: sleepSpark, ...EMPTY };
  if (sleepPoint) {
    const score = sleepPoint.sleep_score;
    sleep = {
      ...sleep,
      value: `${sleepPoint.sleep_hours!.toFixed(1)}h`,
      sub: score == null ? undefined : `score ${Math.round(score)}`,
      tone: score == null ? null : score >= 80 ? "success" : score >= 60 ? "warning" : "danger",
      direction: trendDirection(sleepSpark),
    };
  }

  return [recovery, load, progress, sleep];
}
