import { describe, expect, it } from "vitest";
import type { Analytics, TrendPoint } from "./types";
import {
  aggregateWeeklyDistance,
  deriveTrendTiles,
  easyHardWeekly,
  easySharePct,
  isoWeekOf,
  rampYMax,
  sparkSeries,
  trendDirection,
} from "./trends";

/** Full TrendPoint with every metric null except the overrides. */
function pt(date: string, overrides: Partial<TrendPoint> = {}): TrendPoint {
  return {
    date,
    hrv: null,
    hrv_baseline: null,
    resting_hr: null,
    sleep_hours: null,
    sleep_score: null,
    body_battery: null,
    ctl: null,
    atl: null,
    tsb: null,
    distance_km: null,
    training_load: null,
    acwr: null,
    vo2max: null,
    ...overrides,
  };
}

function ramp(overrides: Partial<Analytics["ramp"]> = {}): Analytics["ramp"] {
  return {
    series: [],
    caution: 1.3,
    high: 1.5,
    zone_today: null,
    chronic_trend: null,
    race: null,
    ...overrides,
  };
}

describe("isoWeekOf", () => {
  it("maps a date to its ISO week key and Monday", () => {
    // 2026-08-19 is a Wednesday in ISO week 34; its Monday is 2026-08-17.
    expect(isoWeekOf("2026-08-19")).toEqual({ key: "2026-W34", monday: "2026-08-17" });
    // A Monday maps to itself.
    expect(isoWeekOf("2026-08-17").monday).toBe("2026-08-17");
    // A Sunday belongs to the week of the preceding Monday.
    expect(isoWeekOf("2026-08-23").monday).toBe("2026-08-17");
  });

  it("assigns early January to the previous ISO year when the week's Thursday is in it", () => {
    // 2027-01-01 is a Friday; its week's Thursday is 2026-12-31 -> ISO 2026-W53.
    expect(isoWeekOf("2027-01-01").key).toBe("2026-W53");
  });
});

describe("aggregateWeeklyDistance", () => {
  it("sums per ISO week, sorted, rounded to 0.1", () => {
    const daily = [
      pt("2026-08-19", { distance_km: 10.04 }),
      pt("2026-08-17", { distance_km: 5.5 }),
      pt("2026-08-24", { distance_km: 8 }), // next week
      pt("2026-08-18"), // null distance ignored
    ];
    expect(aggregateWeeklyDistance(daily)).toEqual([
      { week: "2026-W34", monday: "2026-08-17", distance_km: 15.5 },
      { week: "2026-W35", monday: "2026-08-24", distance_km: 8 },
    ]);
  });
});

describe("easySharePct", () => {
  it("is Z1+Z2 over total, rounded", () => {
    expect(
      easySharePct([{ z1_s: 3000, z2_s: 5000, z3_s: 1000, z4_s: 500, z5_s: 500 }]),
    ).toBe(80);
  });
  it("is null with no time", () => {
    expect(easySharePct([{ z1_s: 0, z2_s: 0, z3_s: 0, z4_s: 0, z5_s: 0 }])).toBeNull();
  });
});

describe("easyHardWeekly", () => {
  it("splits each bucket into easy/hard hours and easy share, sorted by start", () => {
    const rows = easyHardWeekly([
      { start: "2026-08-17", z1_s: 3600, z2_s: 7200, z3_s: 1800, z4_s: 900, z5_s: 900 },
      { start: "2026-08-10", z1_s: 0, z2_s: 3600, z3_s: 3600, z4_s: 0, z5_s: 0 },
    ]);
    expect(rows).toEqual([
      { start: "2026-08-10", easy_h: 1, hard_h: 1, easyPct: 50 },
      { start: "2026-08-17", easy_h: 3, hard_h: 1, easyPct: 75 },
    ]);
  });
  it("carries a null share for an empty bucket", () => {
    const rows = easyHardWeekly([
      { start: "2026-08-17", z1_s: 0, z2_s: 0, z3_s: 0, z4_s: 0, z5_s: 0 },
    ]);
    expect(rows[0]).toEqual({ start: "2026-08-17", easy_h: 0, hard_h: 0, easyPct: null });
  });
});

describe("sparkSeries", () => {
  it("takes the last n non-null values of a metric, in date order", () => {
    const daily = [
      pt("2026-08-01", { hrv: 60 }),
      pt("2026-08-02"),
      pt("2026-08-03", { hrv: 62 }),
      pt("2026-08-04", { hrv: 64 }),
    ];
    expect(sparkSeries(daily, "hrv", 2)).toEqual([62, 64]);
    expect(sparkSeries(daily, "hrv")).toEqual([60, 62, 64]);
    expect(sparkSeries(daily, "vo2max")).toEqual([]);
  });
});

describe("trendDirection", () => {
  it("needs at least 4 values", () => {
    expect(trendDirection([1, 2, 3])).toBeNull();
  });
  it("compares the last-3 mean to the prior mean with a deadband", () => {
    expect(trendDirection([50, 50, 50, 55, 56, 57])).toBe("up");
    expect(trendDirection([50, 50, 50, 45, 44, 43])).toBe("down");
    expect(trendDirection([50, 50, 50, 50, 50.5, 50])).toBe("flat");
  });
});

describe("rampYMax", () => {
  it("keeps the 2.0 ceiling when data fits under it", () => {
    expect(rampYMax([{ date: "2026-08-01", acute: 100, chronic: 90, ratio: 1.4 }])).toBe(2);
    expect(rampYMax([])).toBe(2);
  });
  it("extends to the data max so spikes are plotted, not clamped", () => {
    expect(
      rampYMax([
        { date: "2026-08-01", acute: 300, chronic: 100, ratio: 2.73 },
        { date: "2026-08-02", acute: 100, chronic: 100, ratio: null },
      ]),
    ).toBe(2.8);
  });
});

describe("deriveTrendTiles", () => {
  const daily = [
    pt("2026-08-20", { hrv: 60, hrv_baseline: 60, sleep_hours: 6.1, sleep_score: 55, vo2max: 51 }),
    pt("2026-08-21", { hrv: 62, hrv_baseline: 60, sleep_hours: 7.8, sleep_score: 82, vo2max: 51 }),
    pt("2026-08-22", { hrv: 66, hrv_baseline: 61, sleep_hours: 7.2, sleep_score: 74, vo2max: 52 }),
  ];

  it("derives all four tiles in order", () => {
    const tiles = deriveTrendTiles(daily, null);
    expect(tiles.map((t) => t.key)).toEqual(["recovery", "load", "progress", "sleep"]);
  });

  it("recovery: latest HRV vs its baseline with readiness-card thresholds", () => {
    const rec = deriveTrendTiles(daily, null)[0];
    // (66 - 61) / 61 = +8.2%
    expect(rec.value).toBe("+8.2%");
    expect(rec.sub).toBe("vs baseline");
    expect(rec.tone).toBe("success");
    expect(rec.spark).toEqual([60, 62, 66]);

    const dipping = [pt("2026-08-22", { hrv: 55, hrv_baseline: 61 })];
    expect(deriveTrendTiles(dipping, null)[0].tone).toBe("danger"); // -9.8%
  });

  it("load: the ramp verdict word with the latest ratio", () => {
    const analytics = {
      ramp: ramp({
        zone_today: "caution",
        chronic_trend: "building",
        series: [
          { date: "2026-08-21", acute: 120, chronic: 100, ratio: 1.2 },
          { date: "2026-08-22", acute: 138, chronic: 100, ratio: 1.38 },
        ],
      }),
    } as Analytics;
    const load = deriveTrendTiles(daily, analytics)[1];
    expect(load.value).toBe("Caution");
    expect(load.sub).toBe("ratio 1.38");
    expect(load.tone).toBe("warning");
    expect(load.spark).toEqual([1.2, 1.38]);
  });

  it("load: detraining overrides the zone", () => {
    const analytics = {
      ramp: ramp({ zone_today: "safe", chronic_trend: "detraining" }),
    } as Analytics;
    const load = deriveTrendTiles(daily, analytics)[1];
    expect(load.value).toBe("Detraining");
    expect(load.tone).toBe("warning");
  });

  it("progress: latest VO2max, tone follows direction", () => {
    const rising = [
      pt("2026-08-01", { vo2max: 50 }),
      pt("2026-08-02", { vo2max: 50 }),
      pt("2026-08-03", { vo2max: 50 }),
      pt("2026-08-04", { vo2max: 52 }),
      pt("2026-08-05", { vo2max: 52.5 }),
      pt("2026-08-06", { vo2max: 53 }),
    ];
    const prog = deriveTrendTiles(rising, null)[2];
    expect(prog.value).toBe("53.0");
    expect(prog.direction).toBe("up");
    expect(prog.tone).toBe("success");
  });

  it("sleep: last night's hours with the score's tone", () => {
    const sleep = deriveTrendTiles(daily, null)[3];
    expect(sleep.value).toBe("7.2h");
    expect(sleep.sub).toBe("score 74");
    expect(sleep.tone).toBe("warning"); // 60-79 fair
    expect(sleep.spark).toEqual([6.1, 7.8, 7.2]);
  });

  it("renders a dash and no tone when a metric has no data", () => {
    const tiles = deriveTrendTiles([pt("2026-08-22")], null);
    for (const t of tiles) {
      expect(t.value).toBe("–");
      expect(t.tone).toBeNull();
    }
  });
});
