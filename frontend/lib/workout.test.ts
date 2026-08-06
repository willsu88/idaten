// Step durations arrive as float minutes (a 20-second stride is 0.333), so the
// display layer picks the unit a coach would say out loud.

import { describe, expect, it } from "vitest";
import { compactStepsSummary, formatStepDuration, formatTotalDuration, stepEndLabel } from "./workout";
import type { StepBlock, WorkoutStep } from "./types";

const step = (over: Partial<WorkoutStep> = {}): WorkoutStep => ({
  kind: "work",
  duration_min: null,
  distance_km: null,
  target_pace: null,
  target_hr_low: null,
  target_hr_high: null,
  note: "",
  ...over,
});

describe("formatStepDuration", () => {
  it("renders sub-minute reps in seconds", () => {
    expect(formatStepDuration(20 / 60)).toBe("20 s");
    expect(formatStepDuration(0.25)).toBe("15 s");
  });

  it("renders seconds up to the two-minute crossover", () => {
    expect(formatStepDuration(1.25)).toBe("75 s");
    expect(formatStepDuration(90 / 60)).toBe("90 s");
    expect(formatStepDuration(2)).toBe("2 min");
  });

  it("renders whole minutes without a decimal", () => {
    expect(formatStepDuration(24)).toBe("24 min");
  });

  it("renders a fractional minute as m:ss", () => {
    expect(formatStepDuration(6.5)).toBe("6:30");
    expect(formatStepDuration(2.5)).toBe("2:30");
  });

  it("absorbs float noise", () => {
    expect(formatStepDuration(0.3333333333)).toBe("20 s");
    expect(formatStepDuration(5.000001)).toBe("5 min");
  });

  it("has a compact variant for the week view", () => {
    expect(formatStepDuration(20 / 60, true)).toBe("20s");
    expect(formatStepDuration(24, true)).toBe("24'");
    expect(formatStepDuration(6.5, true)).toBe("6:30");
  });
});

describe("formatTotalDuration", () => {
  it("rounds derived totals to whole minutes", () => {
    expect(formatTotalDuration(6.3333)).toBe("6 min");
    expect(formatTotalDuration(30.333)).toBe("30 min");
  });

  it("keeps hours legible", () => {
    expect(formatTotalDuration(95)).toBe("1 h 35 min");
  });

  it("falls back to seconds below two minutes, where rounding says nothing", () => {
    expect(formatTotalDuration(4 * (20 / 60))).toBe("80 s");
    expect(formatTotalDuration(0.3333)).toBe("20 s");
  });
});

describe("stepEndLabel", () => {
  it("formats a time-based step in the coach's unit", () => {
    expect(stepEndLabel(step({ duration_min: 20 / 60 }))).toBe("20 s");
    expect(stepEndLabel(step({ duration_min: 24 }))).toBe("24 min");
  });

  it("still prefers distance when the step is distance-based", () => {
    expect(stepEndLabel(step({ distance_km: 0.8, duration_min: 4 }))).toBe("800 m");
    expect(stepEndLabel(step({ distance_km: 5 }))).toBe("5 km");
  });

  it("is null with no end condition", () => {
    expect(stepEndLabel(step())).toBeNull();
  });
});

describe("compactStepsSummary", () => {
  it("uses seconds for short reps in the one-liner", () => {
    const blocks: StepBlock[] = [
      { repeat: 1, steps: [step({ kind: "warmup", duration_min: 24 })] },
      {
        repeat: 4,
        steps: [step({ duration_min: 20 / 60 }), step({ kind: "recovery", duration_min: 1.25 })],
      },
    ];
    expect(compactStepsSummary(blocks)).toBe("WU 24' · 4×(20s + 75s)");
  });
});
