// Pure helpers for the /sleep page (contract v1.43).

export type StageKey = "deep" | "light" | "rem" | "awake";

// Garmin hypnogram levels → stage keys (0 deep, 1 light, 2 REM, 3 awake).
export const LEVEL_TO_STAGE: Record<number, StageKey> = {
  0: "deep",
  1: "light",
  2: "rem",
  3: "awake",
};

// Row order top→bottom in the hypnogram, standard sleep-chart convention.
export const STAGE_ROWS: StageKey[] = ["awake", "rem", "light", "deep"];

export const STAGE_LABELS: Record<StageKey, string> = {
  deep: "Deep",
  light: "Light",
  rem: "REM",
  awake: "Awake",
};

/** "7h 18m" from seconds; "0m" floor; null-safe. */
export function fmtDuration(seconds: number | null | undefined): string {
  if (seconds == null) return "–";
  const m = Math.round(seconds / 60);
  const h = Math.floor(m / 60);
  if (h === 0) return `${m % 60}m`;
  return m % 60 === 0 ? `${h}h` : `${h}h ${m % 60}m`;
}

/**
 * Decimal hour-of-day from a naive local ISO datetime ("2026-08-13T22:30:00").
 * Parsed textually — never via Date, which would re-interpret the naive
 * wall-clock value in the browser's timezone.
 */
export function clockHour(localIso: string): number {
  const [h, m] = localIso.slice(11, 16).split(":").map(Number);
  return h + m / 60;
}

/**
 * Bedtime hour on an 18→30 axis (6pm today … 6am tomorrow) so a bedtime
 * scatter is continuous across midnight: 22:30 → 22.5, 00:45 → 24.75.
 * Anything between 06:00 and 18:00 (unusual, e.g. shift work) is left as-is.
 */
export function bedtimeHour(localIso: string): number {
  const h = clockHour(localIso);
  return h < 6 ? h + 24 : h;
}

/** "10:30 PM" from a decimal hour (wraps past 24). */
export function fmtHourOfDay(hour: number, locale: string): string {
  const h = ((Math.floor(hour) % 24) + 24) % 24;
  const m = Math.round((hour % 1) * 60);
  const d = new Date(2000, 0, 1, h, m);
  return d.toLocaleTimeString(locale, { hour: "numeric", minute: "2-digit" });
}

/**
 * Stage percentages for the stage bars. Deep/light/REM are shares of time
 * asleep — Garmin's denominator, so they match the score-breakdown numbers —
 * while awake is a share of the whole night in bed.
 */
export function stageShares(stages: {
  deep_s: number | null;
  light_s: number | null;
  rem_s: number | null;
  awake_s: number | null;
}): { key: StageKey; seconds: number; pct: number }[] {
  const deep = stages.deep_s ?? 0;
  const light = stages.light_s ?? 0;
  const rem = stages.rem_s ?? 0;
  const awake = stages.awake_s ?? 0;
  const asleep = deep + light + rem;
  const inBed = asleep + awake;
  const pct = (v: number, total: number) => (total > 0 ? Math.round((v / total) * 100) : 0);
  return [
    { key: "deep", seconds: deep, pct: pct(deep, asleep) },
    { key: "light", seconds: light, pct: pct(light, asleep) },
    { key: "rem", seconds: rem, pct: pct(rem, asleep) },
    { key: "awake", seconds: awake, pct: pct(awake, inBed) },
  ];
}
