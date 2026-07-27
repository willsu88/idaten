// Rendering rules for the admin Coach QA card (ADR 0016). Pure logic, kept out
// of the component so the vitest layer can pin them: counts always travel with
// their denominators, and n/a never counts in a rate.

import type { QaItem, QaVerdictCounts } from "@/lib/types";

export const RUBRIC_LABELS: Record<string, string> = {
  grounded_data: "Grounded data",
  honest_about_edits: "Honest about edits",
  concrete_when_asked: "Concrete when asked",
};

/** Verdicts that count toward a rate: pass + fail. n/a is excluded (the
 * situation never arose), matching the backend's denominators. */
export function applicable(c: QaVerdictCounts): number {
  return c.pass + c.fail;
}

/** "3/4" - the honest display at household volume. "0/0" when nothing
 * applicable (never a bare percentage, never hidden). */
export function ratioLabel(c: QaVerdictCounts): string {
  return `${c.pass}/${applicable(c)}`;
}

/** "83%" from a 0..1 rate; em-free dash when there is no rate (all n/a). */
export function pctLabel(rate: number | null | undefined): string {
  return rate == null ? "-" : `${Math.round(rate * 100)}%`;
}

/** This week's bucket: the backend sends oldest-first with the current week
 * last. */
export function currentWeek(item: QaItem): QaVerdictCounts {
  const w = item.weeks[item.weeks.length - 1];
  return w ?? { pass: 0, fail: 0, na: 0 };
}

/** The version columns the table shows: the newest `max` versions, oldest
 * first, so "previous vs current" reads left to right. */
export function versionColumns(item: QaItem, max = 3): QaItem["versions"] {
  return item.versions.slice(-max);
}

/** True when the item has ever been judged - an unjudged item renders as
 * "waiting for sessions", not as 0%. */
export function hasData(item: QaItem): boolean {
  return item.versions.some((v) => v.pass + v.fail + v.na > 0);
}
