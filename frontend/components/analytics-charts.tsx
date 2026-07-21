"use client";

import * as React from "react";
import {
  Bar,
  CartesianGrid,
  Cell,
  ComposedChart,
  Legend,
  Line,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { TooltipProps } from "recharts";
import type { EfPoint, Race, TrendPoint, ZonesBucket } from "@/lib/types";
import type { ChartTheme } from "@/components/charts";
import { ChartTooltip } from "@/components/charts";
import {
  countdownLabel,
  distanceLabel,
  GarminPredictionChip,
  PredictionChip,
} from "@/components/race-chip";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { APP_LOCALE, formatDay, formatSeconds } from "@/lib/utils";
import { SHOW_RACE_PREDICTION } from "@/lib/flags";

// ---------- shared helpers ----------

function shortDate(dateStr: string): string {
  const d = new Date(`${dateStr}T00:00:00`);
  return d.toLocaleDateString(APP_LOCALE, { month: "short", day: "numeric" });
}

/** seconds-per-km -> "M:SS" pace. */
function paceStr(secPerKm: number): string {
  const s = Math.round(secPerKm);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

function EmptyNote({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
      {children}
    </div>
  );
}

const axisProps = (colors: ChartTheme) =>
  ({ stroke: colors.axis, fontSize: 11, tickLine: false, axisLine: false }) as const;

// Continuous cool-blue -> hot-red temperature scale (5°C..30°C), gray when unknown.
const TEMP_COLD: [number, number, number] = [56, 132, 244]; // blue
const TEMP_HOT: [number, number, number] = [239, 68, 68]; // red
const TEMP_UNKNOWN = "#9ca3af";

export function tempColor(temp: number | null): string {
  if (temp == null) return TEMP_UNKNOWN;
  const t = Math.min(1, Math.max(0, (temp - 5) / 25));
  const c = TEMP_COLD.map((lo, i) => Math.round(lo + (TEMP_HOT[i] - lo) * t));
  return `rgb(${c[0]}, ${c[1]}, ${c[2]})`;
}

type EfDatum = EfPoint & { label: string; roll: number | null };

function prepareEf(points: EfPoint[], window = 5): EfDatum[] {
  const sorted = [...points].sort((a, b) => a.date.localeCompare(b.date));
  return sorted.map((p, i) => {
    const slice = sorted.slice(Math.max(0, i - window + 1), i + 1);
    const roll = slice.reduce((sum, q) => sum + q.ef, 0) / slice.length;
    return { ...p, label: shortDate(p.date), roll: Math.round(roll * 1000) / 1000 };
  });
}

// ---------- Aerobic efficiency ----------

function EfTooltip({ active, payload }: TooltipProps<number, string>) {
  const p = payload?.[0]?.payload as EfDatum | undefined;
  if (!active || !p) return null;
  const rows: Array<[string, string]> = [["EF", p.ef.toFixed(3)]];
  if (p.avg_pace) rows.push(["Pace", `${p.avg_pace} /km`]);
  if (p.avg_hr != null) rows.push(["HR", `${Math.round(p.avg_hr)} bpm`]);
  rows.push(["Temp", p.temperature_c != null ? `${p.temperature_c.toFixed(1)} °C` : "–"]);
  if (p.hr_drift_pct != null) rows.push(["Drift", `${p.hr_drift_pct.toFixed(1)}%`]);
  if (p.distance_km != null) rows.push(["Distance", `${p.distance_km.toFixed(1)} km`]);
  return (
    <div className="rounded-xl border border-border bg-card px-3 py-2 text-xs shadow-lg">
      <p className="mb-1 max-w-52 truncate font-medium">{p.name}</p>
      <p className="mb-1.5 text-muted-foreground">{p.label}</p>
      {rows.map(([k, v]) => (
        <p key={k} className="flex justify-between gap-4 tabular-nums">
          <span className="text-muted-foreground">{k}</span>
          <span className="font-semibold text-foreground">{v}</span>
        </p>
      ))}
    </div>
  );
}

export function EfChart({ points, colors }: { points: EfPoint[]; colors: ChartTheme }) {
  const data = React.useMemo(() => prepareEf(points), [points]);
  if (data.length === 0) return <EmptyNote>No easy-run data yet.</EmptyNote>;
  return (
    <ResponsiveContainer>
      <ComposedChart data={data} margin={{ top: 5, right: 5, left: -20, bottom: 0 }}>
        <CartesianGrid stroke={colors.grid} strokeDasharray="3 3" vertical={false} />
        <XAxis dataKey="label" {...axisProps(colors)} minTickGap={32} />
        <YAxis {...axisProps(colors)} domain={["auto", "auto"]} tickFormatter={(v: number) => v.toFixed(2)} />
        <Tooltip content={<EfTooltip />} />
        <Line
          type="monotone"
          dataKey="roll"
          name="Rolling avg"
          stroke={colors.muted}
          strokeWidth={2}
          dot={false}
          legendType="none"
          tooltipType="none"
        />
        <Scatter dataKey="ef" name="EF">
          {data.map((p) => (
            <Cell key={p.activity_id} fill={tempColor(p.temperature_c)} />
          ))}
        </Scatter>
      </ComposedChart>
    </ResponsiveContainer>
  );
}

export function EfLegend() {
  return (
    <div className="mt-2 flex items-center gap-2 text-xs text-muted-foreground">
      <span>Cold</span>
      <span
        className="h-1.5 w-24 rounded-full"
        style={{ background: `linear-gradient(to right, ${tempColor(5)}, ${tempColor(17.5)}, ${tempColor(30)})` }}
      />
      <span>Hot</span>
      <span className="ml-3 inline-flex items-center gap-1.5">
        <span className="h-2 w-2 rounded-full" style={{ background: TEMP_UNKNOWN }} />
        No temperature
      </span>
    </div>
  );
}

// ---------- HR drift ----------

export function HrDriftChart({ points, colors }: { points: EfPoint[]; colors: ChartTheme }) {
  const data = React.useMemo(
    () =>
      [...points]
        .filter((p) => p.hr_drift_pct != null)
        .sort((a, b) => a.date.localeCompare(b.date))
        .map((p) => ({ ...p, label: shortDate(p.date) })),
    [points],
  );
  if (data.length === 0) return <EmptyNote>No HR drift data yet.</EmptyNote>;
  return (
    <ResponsiveContainer>
      <ComposedChart data={data} margin={{ top: 5, right: 5, left: -20, bottom: 0 }}>
        <CartesianGrid stroke={colors.grid} strokeDasharray="3 3" vertical={false} />
        <XAxis dataKey="label" {...axisProps(colors)} minTickGap={32} />
        <YAxis {...axisProps(colors)} unit="%" domain={["auto", "auto"]} />
        <ReferenceArea y1={0} y2={5} fill={colors.areaPos} fillOpacity={0.08} />
        <ReferenceLine
          y={5}
          stroke={colors.amber}
          strokeDasharray="6 4"
          label={{ value: "5%", position: "insideTopRight", fill: colors.axis, fontSize: 11 }}
        />
        <Tooltip content={<EfTooltip />} />
        <Line
          type="monotone"
          dataKey="hr_drift_pct"
          name="HR drift"
          stroke={colors.accent}
          strokeWidth={1.5}
          dot={{ r: 3, fill: colors.accent, strokeWidth: 0 }}
          connectNulls
        />
      </ComposedChart>
    </ResponsiveContainer>
  );
}

// ---------- Resting HR ----------

export function RestingHrChart({
  data,
  colors,
}: {
  data: Array<TrendPoint & { label: string }>;
  colors: ChartTheme;
}) {
  if (!data.some((p) => p.resting_hr != null)) return <EmptyNote>No resting HR data yet.</EmptyNote>;
  return (
    <ResponsiveContainer>
      <ComposedChart data={data} margin={{ top: 5, right: 5, left: -20, bottom: 0 }}>
        <CartesianGrid stroke={colors.grid} strokeDasharray="3 3" vertical={false} />
        <XAxis dataKey="label" {...axisProps(colors)} minTickGap={32} />
        <YAxis {...axisProps(colors)} domain={["auto", "auto"]} unit=" bpm" width={70} />
        <Tooltip content={<ChartTooltip formatter={(v) => `${Math.round(v)} bpm`} />} />
        <Line
          type="monotone"
          dataKey="resting_hr"
          name="Resting HR"
          stroke={colors.indigo}
          strokeWidth={2}
          dot={false}
          connectNulls
        />
      </ComposedChart>
    </ResponsiveContainer>
  );
}

// ---------- ACWR ----------

export function AcwrChart({
  data,
  colors,
}: {
  data: Array<TrendPoint & { label: string }>;
  colors: ChartTheme;
}) {
  if (!data.some((p) => p.acwr != null)) return <EmptyNote>No ACWR data yet.</EmptyNote>;
  return (
    <ResponsiveContainer>
      <ComposedChart data={data} margin={{ top: 5, right: 5, left: -20, bottom: 0 }}>
        <CartesianGrid stroke={colors.grid} strokeDasharray="3 3" vertical={false} />
        <XAxis dataKey="label" {...axisProps(colors)} minTickGap={32} />
        <YAxis {...axisProps(colors)} domain={[0, "auto"]} tickFormatter={(v: number) => v.toFixed(1)} />
        <ReferenceArea
          y1={0.8}
          y2={1.3}
          fill={colors.areaPos}
          fillOpacity={0.1}
          label={{ value: "Safe zone", position: "insideTopRight", fill: colors.axis, fontSize: 11 }}
        />
        <Tooltip content={<ChartTooltip formatter={(v) => v.toFixed(2)} />} />
        <Line
          type="monotone"
          dataKey="acwr"
          name="ACWR"
          stroke={colors.teal}
          strokeWidth={2}
          dot={false}
          connectNulls
        />
      </ComposedChart>
    </ResponsiveContainer>
  );
}

// ---------- VO2max ----------

export function Vo2maxChart({
  points,
  colors,
}: {
  points: Array<{ date: string; vo2max: number }>;
  colors: ChartTheme;
}) {
  const data = React.useMemo(
    () =>
      [...points]
        .sort((a, b) => a.date.localeCompare(b.date))
        .map((p) => ({ ...p, label: shortDate(p.date) })),
    [points],
  );
  if (data.length === 0) return <EmptyNote>No VO2max data yet.</EmptyNote>;
  return (
    <ResponsiveContainer>
      <ComposedChart data={data} margin={{ top: 5, right: 5, left: -20, bottom: 0 }}>
        <CartesianGrid stroke={colors.grid} strokeDasharray="3 3" vertical={false} />
        <XAxis dataKey="label" {...axisProps(colors)} minTickGap={32} />
        <YAxis {...axisProps(colors)} domain={["auto", "auto"]} />
        <Tooltip content={<ChartTooltip />} />
        <Line
          type="monotone"
          dataKey="vo2max"
          name="VO2max"
          stroke={colors.blue}
          strokeWidth={2}
          dot={false}
          connectNulls
        />
      </ComposedChart>
    </ResponsiveContainer>
  );
}

/** Race time for chart axis/tooltip: "2:01:13" (h:mm:ss) or "48:30" (m:ss).
 * Predictions cluster within a couple of minutes, so seconds precision is needed
 * or every tick collapses to the same "2:01". */
function axisTime(sec: number): string {
  const t = Math.round(sec);
  const h = Math.floor(t / 3600);
  const m = Math.floor((t % 3600) / 60);
  const s = t % 60;
  const pad = (n: number) => String(n).padStart(2, "0");
  return h > 0 ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`;
}

/**
 * Garmin's predicted finish for the primary race's distance, over time — trends
 * DOWN toward the goal line as fitness improves. Data is Garmin's race predictor
 * (Riegel-adjusted per day), stored daily in DailyHealth.race_predictions.
 */
export function RacePredictionTrendChart({
  series,
  goalS,
  colors,
}: {
  series: Array<{ date: string; predicted_time_s: number }>;
  goalS: number | null;
  colors: ChartTheme;
}) {
  const data = React.useMemo(
    () =>
      [...series]
        .sort((a, b) => a.date.localeCompare(b.date))
        .map((p) => ({ ...p, label: shortDate(p.date) })),
    [series],
  );
  if (data.length < 2) return <EmptyNote>Not enough prediction history yet.</EmptyNote>;
  return (
    <ResponsiveContainer>
      <ComposedChart data={data} margin={{ top: 5, right: 5, left: 5, bottom: 0 }}>
        <CartesianGrid stroke={colors.grid} strokeDasharray="3 3" vertical={false} />
        <XAxis dataKey="label" {...axisProps(colors)} minTickGap={32} />
        <YAxis
          {...axisProps(colors)}
          domain={["auto", "auto"]}
          width={64}
          tickFormatter={axisTime}
        />
        {goalS != null && (
          <ReferenceLine
            y={goalS}
            stroke={colors.accent}
            strokeDasharray="6 4"
            label={{
              value: `goal ${axisTime(goalS)}`,
              position: "insideBottomRight",
              fill: colors.axis,
              fontSize: 11,
            }}
          />
        )}
        <Tooltip content={<ChartTooltip formatter={(v) => axisTime(v)} />} />
        <Line
          type="monotone"
          dataKey="predicted_time_s"
          name="Predicted finish"
          stroke={colors.blue}
          strokeWidth={2}
          dot={false}
          connectNulls
        />
      </ComposedChart>
    </ResponsiveContainer>
  );
}

export function RaceOutlookCard({ races }: { races: Race[] }) {
  const primary = races.find((r) => r.is_primary) ?? races[0];
  if (!primary) return null;
  const others = races.filter((r) => r.id !== primary.id);
  const { likely_s, low_s, high_s, goal_time_s, likely_pace, confidence, garmin_time_s } =
    primary.prediction;
  // Default surfaces GARMIN's predicted finish; the flag swaps in Idaten's own
  // calibrated prediction (range + confidence).
  const predS = SHOW_RACE_PREDICTION ? likely_s : garmin_time_s;
  const predLabel = SHOW_RACE_PREDICTION ? "Likely" : "Predicted";
  const predPace =
    SHOW_RACE_PREDICTION
      ? likely_pace
      : garmin_time_s != null && primary.distance_km
        ? `${paceStr(garmin_time_s / primary.distance_km)}`
        : null;
  const hasRange = SHOW_RACE_PREDICTION && confidence !== "low" && low_s != null && high_s != null;
  const delta = predS != null && goal_time_s != null ? predS - goal_time_s : null;
  const onTrack = delta != null && delta <= 0;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Race outlook</CardTitle>
        <CardDescription>
          {primary.name} · {distanceLabel(primary.distance_km)} · {formatDay(primary.date)} (
          {countdownLabel(primary.days_to_race)})
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {predS == null ? (
          <p className="text-sm text-muted-foreground">
            Not enough data for a prediction yet — goal is{" "}
            <span className="tabular-nums">
              {goal_time_s != null ? formatSeconds(goal_time_s) : primary.goal_time}
            </span>
            .
          </p>
        ) : (
          <div className="flex flex-wrap items-start gap-x-8 gap-y-3">
            <div>
              <p className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                {predLabel}
                {!SHOW_RACE_PREDICTION && (
                  <Badge
                    variant="outline"
                    className="px-1.5 py-0 text-[10px] font-normal normal-case text-muted-foreground"
                  >
                    Garmin
                  </Badge>
                )}
              </p>
              <p className="text-2xl font-semibold tabular-nums">
                {SHOW_RACE_PREDICTION && confidence === "low" && "~"}
                {formatSeconds(predS)}
              </p>
              {hasRange ? (
                <p className="text-xs tabular-nums text-muted-foreground">
                  {formatSeconds(low_s!)}–{formatSeconds(high_s!)}
                  {predPace && <> · {predPace} /km</>}
                </p>
              ) : (
                predPace && (
                  <p className="text-xs tabular-nums text-muted-foreground">{predPace} /km</p>
                )
              )}
            </div>
            <div>
              <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Goal</p>
              <p className="text-2xl font-semibold tabular-nums">
                {goal_time_s != null ? formatSeconds(goal_time_s) : primary.goal_time}
              </p>
              {primary.prediction.goal_pace && (
                <p className="text-xs tabular-nums text-muted-foreground">
                  {primary.prediction.goal_pace} /km
                </p>
              )}
            </div>
            {delta != null && (
              <p
                className={
                  onTrack
                    ? "self-center rounded-full bg-success/10 px-3 py-1 text-sm font-medium tabular-nums text-success"
                    : "self-center rounded-full bg-amber-500/15 px-3 py-1 text-sm font-medium tabular-nums text-amber-600 dark:text-amber-400"
                }
              >
                {onTrack
                  ? `On track — ${formatSeconds(Math.abs(delta))} ahead of goal`
                  : `${formatSeconds(delta)} to close`}
              </p>
            )}
          </div>
        )}

        {others.length > 0 && (
          <div className="space-y-2 border-t border-border pt-3">
            <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Other upcoming races
            </p>
            {others.map((race) => (
              <div key={race.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
                <span className="font-medium">{race.name}</span>
                <span className="text-xs text-muted-foreground">
                  {formatDay(race.date)} ({countdownLabel(race.days_to_race)}) ·{" "}
                  {distanceLabel(race.distance_km)} · goal{" "}
                  <span className="tabular-nums">{race.goal_time}</span>
                </span>
                {SHOW_RACE_PREDICTION ? (
                  <PredictionChip prediction={race.prediction} />
                ) : (
                  <GarminPredictionChip prediction={race.prediction} />
                )}
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ---------- Time in zones ----------

/** Zone colors shared with the activity detail zones bar. */
export const ZONE_COLORS: Record<"z1" | "z2" | "z3" | "z4" | "z5", string> = {
  z1: "#3b82f6",
  z2: "#06b6d4",
  z3: "#eab308",
  z4: "#f97316",
  z5: "#ef4444",
};

const ZONES = [
  { key: "z1_h", name: "Z1", color: ZONE_COLORS.z1 },
  { key: "z2_h", name: "Z2", color: ZONE_COLORS.z2 },
  { key: "z3_h", name: "Z3", color: ZONE_COLORS.z3 },
  { key: "z4_h", name: "Z4", color: ZONE_COLORS.z4 },
  { key: "z5_h", name: "Z5", color: ZONE_COLORS.z5 },
] as const;

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

// Buckets are weekly (long ranges) or daily (7-day view); each carries a `start`
// ISO date used as the x-axis label.
export type ZonesBar = ZonesBucket & { start: string };

export function ZonesWeeklyChart({ buckets, colors }: { buckets: ZonesBar[]; colors: ChartTheme }) {
  const data = React.useMemo(
    () =>
      [...buckets]
        .sort((a, b) => a.start.localeCompare(b.start))
        .map((b) => ({
          label: shortDate(b.start),
          z1_h: Math.round((b.z1_s / 3600) * 100) / 100,
          z2_h: Math.round((b.z2_s / 3600) * 100) / 100,
          z3_h: Math.round((b.z3_s / 3600) * 100) / 100,
          z4_h: Math.round((b.z4_s / 3600) * 100) / 100,
          z5_h: Math.round((b.z5_s / 3600) * 100) / 100,
        })),
    [buckets],
  );
  if (data.length === 0) return <EmptyNote>No zone data yet.</EmptyNote>;
  return (
    <ResponsiveContainer>
      <ComposedChart data={data} margin={{ top: 5, right: 5, left: -20, bottom: 0 }}>
        <CartesianGrid stroke={colors.grid} strokeDasharray="3 3" vertical={false} />
        <XAxis dataKey="label" {...axisProps(colors)} minTickGap={24} />
        <YAxis {...axisProps(colors)} unit=" h" />
        <Tooltip content={<ChartTooltip formatter={(v) => `${v.toFixed(1)} h`} />} />
        <Legend wrapperStyle={{ fontSize: 12 }} />
        {ZONES.map((z, i) => (
          <Bar
            key={z.key}
            dataKey={z.key}
            name={z.name}
            stackId="zones"
            fill={z.color}
            radius={i === ZONES.length - 1 ? [3, 3, 0, 0] : undefined}
          />
        ))}
      </ComposedChart>
    </ResponsiveContainer>
  );
}
