import { describe, expect, it } from "vitest";

import type { PlanDay, WorkoutType } from "@/lib/types";
import {
  adjacentQualityDates,
  buildMoves,
  hasChanges,
  initialAssignment,
  isLockedDay,
  swapSlots,
} from "@/lib/reorder";

/** Mon…Sun of one week — the 7 fixed slots the module models. */
const WEEK = [
  "2026-07-20",
  "2026-07-21",
  "2026-07-22",
  "2026-07-23",
  "2026-07-24",
  "2026-07-25",
  "2026-07-26",
];
const TODAY = "2026-07-22";

function makeDay(
  date: string,
  workout_type: WorkoutType = "easy_run",
  status: PlanDay["status"] = "planned",
): PlanDay {
  return {
    date,
    workout_type,
    title: `${workout_type} on ${date}`,
    description: "",
    duration_min: null,
    distance_km: null,
    target_pace: null,
    target_hr_low: null,
    target_hr_high: null,
    rationale: "",
    status,
    garmin_workout_id: null,
    pushed_at: null,
    steps: null,
  };
}

describe("initialAssignment", () => {
  it("returns the identity permutation as a fresh array", () => {
    const assignment = initialAssignment(WEEK);
    expect(assignment).toEqual(WEEK);
    expect(assignment).not.toBe(WEEK);
  });
});

describe("isLockedDay", () => {
  it("locks a placeholder slot (no materialized day)", () => {
    expect(isLockedDay(undefined, "2026-07-23", TODAY)).toBe(true);
  });

  it("locks any past date, even one still marked planned", () => {
    expect(isLockedDay(makeDay("2026-07-21"), "2026-07-21", TODAY)).toBe(true);
  });

  it("leaves today movable while its run is still planned", () => {
    expect(isLockedDay(makeDay(TODAY), TODAY, TODAY)).toBe(false);
  });

  it("leaves a future planned day movable", () => {
    expect(isLockedDay(makeDay("2026-07-25"), "2026-07-25", TODAY)).toBe(false);
  });

  it("locks a day whose history is written (completed or skipped)", () => {
    expect(
      isLockedDay(makeDay(TODAY, "easy_run", "completed"), TODAY, TODAY),
    ).toBe(true);
    expect(
      isLockedDay(makeDay("2026-07-25", "easy_run", "skipped"), "2026-07-25", TODAY),
    ).toBe(true);
  });
});

describe("swapSlots", () => {
  const UNLOCKED = WEEK.map(() => false);

  it("swaps the contents of two unlocked slots without mutating the input", () => {
    const before = initialAssignment(WEEK);
    const after = swapSlots(before, 1, 4, UNLOCKED);
    expect(after[1]).toBe(WEEK[4]);
    expect(after[4]).toBe(WEEK[1]);
    expect(before).toEqual(WEEK);
  });

  it("is a no-op when either side is locked", () => {
    const locked = [...UNLOCKED];
    locked[4] = true;
    const assignment = initialAssignment(WEEK);
    expect(swapSlots(assignment, 1, 4, locked)).toBe(assignment);
    expect(swapSlots(assignment, 4, 1, locked)).toBe(assignment);
  });

  it("is a no-op on a self-swap or an out-of-range index", () => {
    const assignment = initialAssignment(WEEK);
    expect(swapSlots(assignment, 3, 3, UNLOCKED)).toBe(assignment);
    expect(swapSlots(assignment, -1, 3, UNLOCKED)).toBe(assignment);
    expect(swapSlots(assignment, 3, 7, UNLOCKED)).toBe(assignment);
  });
});

describe("hasChanges / buildMoves", () => {
  const UNLOCKED = WEEK.map(() => false);

  it("reports no changes and zero moves for the identity arrangement", () => {
    const assignment = initialAssignment(WEEK);
    expect(hasChanges(WEEK, assignment)).toBe(false);
    expect(buildMoves(WEEK, assignment)).toEqual([]);
  });

  it("emits exactly the two changed slots for a single swap", () => {
    const assignment = swapSlots(initialAssignment(WEEK), 1, 4, UNLOCKED);
    expect(hasChanges(WEEK, assignment)).toBe(true);
    expect(buildMoves(WEEK, assignment)).toEqual([
      { date: WEEK[1], content_from: WEEK[4] },
      { date: WEEK[4], content_from: WEEK[1] },
    ]);
  });

  it("returns to zero moves when a swap is undone", () => {
    let assignment = swapSlots(initialAssignment(WEEK), 1, 4, UNLOCKED);
    assignment = swapSlots(assignment, 1, 4, UNLOCKED);
    expect(hasChanges(WEEK, assignment)).toBe(false);
    expect(buildMoves(WEEK, assignment)).toEqual([]);
  });
});

describe("adjacentQualityDates", () => {
  const UNLOCKED = WEEK.map(() => false);

  function weekOf(types: WorkoutType[]): Map<string, PlanDay> {
    return new Map(WEEK.map((date, i) => [date, makeDay(date, types[i])]));
  }

  it("flags nothing when quality days are separated", () => {
    const byDate = weekOf([
      "tempo",
      "easy_run",
      "intervals",
      "easy_run",
      "long_run",
      "rest",
      "easy_run",
    ]);
    const flagged = adjacentQualityDates(WEEK, initialAssignment(WEEK), byDate);
    expect(flagged.size).toBe(0);
  });

  it("flags both slot dates of a back-to-back quality pair", () => {
    const byDate = weekOf([
      "easy_run",
      "tempo",
      "intervals",
      "easy_run",
      "easy_run",
      "rest",
      "long_run",
    ]);
    const flagged = adjacentQualityDates(WEEK, initialAssignment(WEEK), byDate);
    expect(flagged).toEqual(new Set([WEEK[1], WEEK[2]]));
  });

  it("flags a whole run of three consecutive quality days", () => {
    const byDate = weekOf([
      "easy_run",
      "tempo",
      "intervals",
      "long_run",
      "easy_run",
      "rest",
      "easy_run",
    ]);
    const flagged = adjacentQualityDates(WEEK, initialAssignment(WEEK), byDate);
    expect(flagged).toEqual(new Set([WEEK[1], WEEK[2], WEEK[3]]));
  });

  it("evaluates the STAGED arrangement: a swap can create an adjacency", () => {
    // Quality on Mon and Wed only — fine as authored…
    const byDate = weekOf([
      "tempo",
      "easy_run",
      "intervals",
      "easy_run",
      "easy_run",
      "rest",
      "easy_run",
    ]);
    expect(
      adjacentQualityDates(WEEK, initialAssignment(WEEK), byDate).size,
    ).toBe(0);
    // …but dragging Wed's intervals onto Tue puts tempo + intervals back to back.
    const staged = swapSlots(initialAssignment(WEEK), 1, 2, UNLOCKED);
    expect(adjacentQualityDates(WEEK, staged, byDate)).toEqual(
      new Set([WEEK[0], WEEK[1]]),
    );
  });

  it("treats a slot with no day in the map as non-quality", () => {
    const byDate = weekOf([
      "tempo",
      "intervals",
      "easy_run",
      "easy_run",
      "easy_run",
      "rest",
      "easy_run",
    ]);
    byDate.delete(WEEK[1]); // placeholder next to a tempo day
    const flagged = adjacentQualityDates(WEEK, initialAssignment(WEEK), byDate);
    expect(flagged.size).toBe(0);
  });
});
