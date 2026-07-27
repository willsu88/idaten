// Rendering rules for the Coach QA card (ADR 0016): denominators always
// visible, n/a excluded from rates, current week = last bucket, version
// columns newest-last.

import { describe, expect, it } from "vitest";
import {
  applicable,
  currentWeek,
  hasData,
  pctLabel,
  ratioLabel,
  versionColumns,
} from "./qa";
import type { QaItem } from "./types";

const counts = (pass: number, fail: number, na: number) => ({ pass, fail, na });

describe("n/a exclusion", () => {
  it("applicable counts pass+fail only", () => {
    expect(applicable(counts(3, 1, 5))).toBe(4);
  });

  it("ratioLabel shows the honest denominator, never a bare percentage", () => {
    expect(ratioLabel(counts(3, 1, 5))).toBe("3/4");
    expect(ratioLabel(counts(0, 0, 2))).toBe("0/0");
  });

  it("pctLabel renders a dash when nothing was applicable", () => {
    expect(pctLabel(2 / 3)).toBe("67%");
    expect(pctLabel(null)).toBe("-");
    expect(pctLabel(undefined)).toBe("-");
  });
});

const item = (over: Partial<QaItem> = {}): QaItem => ({
  key: "grounded_data",
  weeks: [
    { week_start: "2026-07-13", ...counts(5, 0, 1) },
    { week_start: "2026-07-20", ...counts(3, 1, 0) },
  ],
  versions: [
    { prompt_version: "v1", ...counts(10, 0, 2), pass_rate: 1 },
    { prompt_version: "v2", ...counts(3, 2, 0), pass_rate: 0.6 },
  ],
  regression: false,
  ...over,
});

describe("week and version selection", () => {
  it("currentWeek is the last bucket (backend sends oldest first)", () => {
    expect(currentWeek(item())).toMatchObject(counts(3, 1, 0));
    expect(currentWeek(item({ weeks: [] }))).toEqual(counts(0, 0, 0));
  });

  it("versionColumns keeps the newest versions in old-to-new order", () => {
    const many = item({
      versions: ["v1", "v2", "v3", "v4"].map((v) => ({
        prompt_version: v,
        ...counts(1, 0, 0),
        pass_rate: 1,
      })),
    });
    expect(versionColumns(many, 3).map((v) => v.prompt_version)).toEqual(["v2", "v3", "v4"]);
  });

  it("hasData is false until anything (even an n/a) was judged", () => {
    expect(hasData(item({ versions: [] }))).toBe(false);
    expect(
      hasData(item({ versions: [{ prompt_version: "v1", ...counts(0, 0, 1), pass_rate: null }] })),
    ).toBe(true);
  });
});
