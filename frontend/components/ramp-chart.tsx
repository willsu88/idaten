"use client";

import * as React from "react";
import {
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { TooltipProps } from "recharts";
import type { Analytics } from "@/lib/types";
import type { ChartTheme } from "@/components/charts";
import { APP_LOCALE, cn } from "@/lib/utils";

type Ramp = Analytics["ramp"];

// Clamped y domain - ratios beyond this are all "way too much"; keeping the
// scale fixed makes the bands read the same across athletes and windows.
const Y_MIN = 0.5;
const Y_MAX = 2.0;

function shortDate(dateStr: string): string {
  const d = new Date(`${dateStr}T00:00:00`);
  return d.toLocaleDateString(APP_LOCALE, { month: "short", day: "numeric" });
}

type RampDatum = {
  date: string;
  label: string;
  ratio: number | null; // clamped for plotting - the tooltip shows the raw value
  raw: number | null;
  acute: number;
  chronic: number;
};

function RampTooltip({ active, payload }: TooltipProps<number, string>) {
  const p = payload?.[0]?.payload as RampDatum | undefined;
  if (!active || !p || p.raw == null) return null;
  const rows: Array<[string, string]> = [
    ["Ratio", p.raw.toFixed(2)],
    ["7-day load", `${Math.round(p.acute)}`],
    ["28-day load", `${Math.round(p.chronic)}`],
  ];
  return (
    <div className="rounded-xl border border-border bg-card px-3 py-2 text-xs shadow-lg">
      <p className="mb-1 font-medium text-muted-foreground">{p.label}</p>
      {rows.map(([k, v]) => (
        <p key={k} className="flex justify-between gap-4 tabular-nums">
          <span className="text-muted-foreground">{k}</span>
          <span className="font-semibold text-foreground">{v}</span>
        </p>
      ))}
    </div>
  );
}

/** Header chip from today's zone + the chronic-load trend. Hidden when unknown. */
export function RampStatusChip({ ramp }: { ramp: Ramp | null }) {
  if (!ramp) return null;
  const { zone_today, chronic_trend } = ramp;
  let text: string | null = null;
  let tone = "";
  if (chronic_trend === "detraining") {
    text = "Detraining";
    tone = "bg-slate-500/15 text-slate-600 dark:text-slate-400";
  } else if (zone_today === "high") {
    text = "High";
    tone = "bg-rose-500/15 text-rose-600 dark:text-rose-400";
  } else if (zone_today === "caution") {
    text = "Caution";
    tone = "bg-amber-500/15 text-amber-600 dark:text-amber-400";
  } else if (zone_today === "safe") {
    text = chronic_trend === "building" ? "Safe - building" : "Safe";
    tone = "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400";
  }
  if (!text) return null;
  return (
    <span
      className={cn("rounded-full px-2.5 py-0.5 text-[11px] font-medium normal-case", tone)}
    >
      {text}
    </span>
  );
}

export function RampChart({ ramp, colors }: { ramp: Ramp | null; colors: ChartTheme }) {
  const data = React.useMemo<RampDatum[]>(() => {
    if (!ramp) return [];
    return [...ramp.series]
      .sort((a, b) => a.date.localeCompare(b.date))
      .map((p) => ({
        date: p.date,
        label: shortDate(p.date),
        ratio: p.ratio == null ? null : Math.min(Y_MAX, Math.max(Y_MIN, p.ratio)),
        raw: p.ratio,
        acute: p.acute,
        chronic: p.chronic,
      }));
  }, [ramp]);

  if (!ramp || !data.some((p) => p.ratio != null)) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        No load-ramp data yet.
      </div>
    );
  }

  // Race marker only when the primary race's date falls inside the visible window.
  const raceLabel =
    ramp.race && data.some((p) => p.date === ramp.race!.date)
      ? { x: shortDate(ramp.race.date), name: ramp.race.name }
      : null;

  return (
    <ResponsiveContainer>
      <ComposedChart data={data} margin={{ top: 5, right: 5, left: -20, bottom: 0 }}>
        <CartesianGrid stroke={colors.grid} strokeDasharray="3 3" vertical={false} />
        <XAxis
          dataKey="label"
          stroke={colors.axis}
          fontSize={11}
          tickLine={false}
          axisLine={false}
          minTickGap={32}
        />
        <YAxis
          stroke={colors.axis}
          fontSize={11}
          tickLine={false}
          axisLine={false}
          domain={[Y_MIN, Y_MAX]}
          tickFormatter={(v: number) => v.toFixed(1)}
        />
        <ReferenceArea y1={Y_MIN} y2={ramp.caution} fill={colors.areaPos} fillOpacity={0.1} />
        <ReferenceArea y1={ramp.caution} y2={ramp.high} fill={colors.amber} fillOpacity={0.1} />
        <ReferenceArea y1={ramp.high} y2={Y_MAX} fill={colors.areaNeg} fillOpacity={0.1} />
        <ReferenceLine
          y={ramp.caution}
          stroke={colors.amber}
          strokeDasharray="6 4"
          label={{
            value: ramp.caution.toFixed(1),
            position: "insideTopRight",
            fill: colors.axis,
            fontSize: 11,
          }}
        />
        {raceLabel && (
          <ReferenceLine
            x={raceLabel.x}
            stroke={colors.muted}
            strokeDasharray="4 4"
            label={{
              value: raceLabel.name,
              position: "insideTopLeft",
              fill: colors.axis,
              fontSize: 11,
            }}
          />
        )}
        <Tooltip content={<RampTooltip />} />
        <Line
          type="monotone"
          dataKey="ratio"
          name="Ramp"
          stroke={colors.accent}
          strokeWidth={2}
          dot={false}
        />
      </ComposedChart>
    </ResponsiveContainer>
  );
}
