import { describe, expect, it } from "vitest";
import { bedtimeHour, clockHour, fmtDuration, fmtHourOfDay, stageShares } from "./sleep";

describe("fmtDuration", () => {
  it("formats hours and minutes", () => {
    expect(fmtDuration(26280)).toBe("7h 18m");
    expect(fmtDuration(5400)).toBe("1h 30m");
    expect(fmtDuration(720)).toBe("12m");
    expect(fmtDuration(7200)).toBe("2h");
    expect(fmtDuration(null)).toBe("–");
  });
});

describe("clockHour / bedtimeHour", () => {
  it("reads the wall clock textually, not via Date", () => {
    expect(clockHour("2026-08-13T22:30:00")).toBe(22.5);
    expect(clockHour("2026-08-14T06:15:00")).toBe(6.25);
  });
  it("wraps past-midnight bedtimes onto the 18→30 axis", () => {
    expect(bedtimeHour("2026-08-13T22:30:00")).toBe(22.5);
    expect(bedtimeHour("2026-08-14T00:45:00")).toBe(24.75);
    expect(bedtimeHour("2026-08-14T05:59:00")).toBeCloseTo(29.983, 2);
  });
});

describe("fmtHourOfDay", () => {
  it("formats decimal hours including wrapped ones", () => {
    expect(fmtHourOfDay(22.5, "en-US")).toBe("10:30 PM");
    expect(fmtHourOfDay(24.75, "en-US")).toBe("12:45 AM");
  });
});

describe("stageShares", () => {
  it("shares of time asleep for stages (Garmin's denominator), whole night for awake", () => {
    const shares = stageShares({ deep_s: 5400, light_s: 14400, rem_s: 4800, awake_s: 1680 });
    expect(shares.map((s) => s.key)).toEqual(["deep", "light", "rem", "awake"]);
    // asleep = 24600s: deep 22%, light 59%, rem 20%; awake over 26280s in bed = 6%
    expect(shares.find((s) => s.key === "deep")?.pct).toBe(22);
    expect(shares.find((s) => s.key === "light")?.pct).toBe(59);
    expect(shares.find((s) => s.key === "rem")?.pct).toBe(20);
    expect(shares.find((s) => s.key === "awake")?.pct).toBe(6);
  });
  it("handles an all-null night", () => {
    expect(stageShares({ deep_s: null, light_s: null, rem_s: null, awake_s: null })
      .every((s) => s.pct === 0)).toBe(true);
  });
});
