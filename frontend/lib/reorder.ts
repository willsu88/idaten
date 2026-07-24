/**
 * Week reorder staging — pure functions, deliberately free of React and
 * dnd-kit so they stay importable by the future frontend test suite
 * (.scratch/frontend-test-infra). Spec: .scratch/week-reorder/spec.md.
 *
 * Model: the week is 7 fixed slots (Mon…Sun dates). `assignment[i]` is the
 * date whose CONTENT currently sits in slot i — the identity permutation
 * until the user drags. A drag is a SWAP of two unlocked slots (whole-day
 * cards trade dates); locked slots (past, completed/skipped, placeholder)
 * never move and never receive.
 */

import type { PlanDay, WorkoutType } from "@/lib/types";

/** Types that count as a quality day for the back-to-back warning. */
export const QUALITY_TYPES: ReadonlySet<WorkoutType> = new Set<WorkoutType>([
  "tempo",
  "intervals",
  "long_run",
  "race",
]);

export interface ReorderMove {
  date: string; // the slot that will carry the moved content
  content_from: string; // the date whose content moves there
}

/** The identity arrangement: every slot holds its own date's content. */
export function initialAssignment(slotDates: string[]): string[] {
  return [...slotDates];
}

/**
 * A slot that can neither be dragged nor receive a drop: no materialized day
 * (placeholder), a past date, or a day whose history is written
 * (completed/skipped). Today itself is movable — the run isn't done yet.
 */
export function isLockedDay(
  day: PlanDay | undefined,
  date: string,
  today: string,
): boolean {
  if (!day) return true;
  if (date < today) return true;
  return day.status !== "planned";
}

/** Swap the contents of two slots. No-op if either side is locked. */
export function swapSlots(
  assignment: string[],
  a: number,
  b: number,
  locked: boolean[],
): string[] {
  if (a === b || a < 0 || b < 0 || a >= assignment.length || b >= assignment.length) {
    return assignment;
  }
  if (locked[a] || locked[b]) return assignment;
  const next = [...assignment];
  [next[a], next[b]] = [next[b], next[a]];
  return next;
}

/** True once any card sits away from home — i.e. there is something to save. */
export function hasChanges(slotDates: string[], assignment: string[]): boolean {
  return slotDates.some((date, i) => assignment[i] !== date);
}

/** The changed slots as the API's permutation payload (empty = nothing staged). */
export function buildMoves(slotDates: string[], assignment: string[]): ReorderMove[] {
  return slotDates.flatMap((date, i) =>
    assignment[i] !== date ? [{ date, content_from: assignment[i] }] : [],
  );
}

/**
 * Slot dates that are part of a back-to-back quality pair in the STAGED
 * arrangement — the non-blocking "two hard days in a row" nudge. Purely
 * heuristic and advisory: it flags, the user always keeps final authority.
 */
export function adjacentQualityDates(
  slotDates: string[],
  assignment: string[],
  byDate: Map<string, PlanDay>,
): Set<string> {
  const quality = assignment.map((from) => {
    const day = byDate.get(from);
    return day != null && QUALITY_TYPES.has(day.workout_type);
  });
  const flagged = new Set<string>();
  for (let i = 0; i + 1 < slotDates.length; i++) {
    if (quality[i] && quality[i + 1]) {
      flagged.add(slotDates[i]);
      flagged.add(slotDates[i + 1]);
    }
  }
  return flagged;
}
