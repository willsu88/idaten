import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/**
 * The app renders in English regardless of the device's system locale. Pass
 * this to every `toLocale*`/`Intl` call - `undefined` would fall back to the
 * browser/device locale, which is why weekdays showed up in Mandarin on
 * Chinese-configured phones. One knob if we ever add real i18n.
 */
export const APP_LOCALE = "en-US";

/** Local-timezone YYYY-MM-DD for a Date (defaults to now). */
export function isoDate(d: Date = new Date()): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

/** Add `n` days to an ISO date string, returning a new ISO date string. */
export function addDays(dateStr: string, n: number): string {
  const d = new Date(`${dateStr}T00:00:00`);
  d.setDate(d.getDate() + n);
  return isoDate(d);
}

/** Monday (ISO week start) of the week containing `dateStr`. */
export function mondayOf(dateStr: string): string {
  const d = new Date(`${dateStr}T00:00:00`);
  const dow = (d.getDay() + 6) % 7; // Mon=0 … Sun=6
  return addDays(dateStr, -dow);
}

/** The 7 ISO date strings Mon…Sun for the week starting at `monday`. */
export function weekDates(monday: string): string[] {
  return Array.from({ length: 7 }, (_, i) => addDays(monday, i));
}

/** "trail_running" -> "Trail running" */
export function prettyType(type: string): string {
  const words = type.replace(/_/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export function formatDay(dateStr: string): string {
  const d = new Date(`${dateStr}T00:00:00`);
  return d.toLocaleDateString(APP_LOCALE, { weekday: "short", month: "short", day: "numeric" });
}

export function formatWeekday(dateStr: string): string {
  const d = new Date(`${dateStr}T00:00:00`);
  return d.toLocaleDateString(APP_LOCALE, { weekday: "long" });
}

/** Format a duration in seconds as h:mm:ss (or m:ss under an hour). */
export function formatSeconds(totalSeconds: number): string {
  const s = Math.round(Math.abs(totalSeconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  if (h === 0) return `${m}:${String(sec).padStart(2, "0")}`;
  return `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`;
}

export function formatDuration(min: number | null): string | null {
  if (min == null) return null;
  const h = Math.floor(min / 60);
  const m = Math.round(min % 60);
  if (h === 0) return `${m} min`;
  return m === 0 ? `${h} h` : `${h} h ${m} min`;
}
