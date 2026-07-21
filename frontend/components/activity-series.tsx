"use client";

import * as React from "react";
import {
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceArea,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { TooltipProps } from "recharts";
import type { ActivitySeries } from "@/lib/types";
import { api } from "@/lib/api";
import { ActivityMap } from "@/components/activity-map";
import { useChartTheme, type ChartTheme } from "@/components/charts";
import { ZONE_COLORS } from "@/components/analytics-charts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { formatSeconds } from "@/lib/utils";

const MAX_POINTS = 800; // downsample long activities so recharts stays smooth
const MAX_PACE_S = 1200; // treat slower than 20:00 /km as standing still (gaps, pauses)

interface SeriesPoint {
  t: number; // elapsed seconds
  pace: number | null; // sec/km
  hr: number | null;
  elev: number | null;
  cad: number | null;
}

function preparePoints(series: NonNullable<ActivitySeries["series"]>): SeriesPoint[] {
  const n = series.t_s.length;
  const stride = Math.max(1, Math.ceil(n / MAX_POINTS));
  const points: SeriesPoint[] = [];
  for (let i = 0; i < n; i += stride) {
    const speed = series.speed_mps?.[i] ?? null;
    let pace: number | null = null;
    if (speed != null && speed > 0) {
      const p = 1000 / speed;
      if (p <= MAX_PACE_S) pace = Math.round(p);
    }
    points.push({
      t: series.t_s[i],
      pace,
      hr: series.hr?.[i] ?? null,
      elev: series.elevation_m?.[i] ?? null,
      cad: series.cadence_spm?.[i] ?? null,
    });
  }
  return points;
}

const axisProps = (colors: ChartTheme) =>
  ({ stroke: colors.axis, fontSize: 11, tickLine: false, axisLine: false }) as const;

function SeriesTooltip({
  active,
  payload,
  label,
  formatter,
}: TooltipProps<number, string> & { formatter: (value: number) => string }) {
  const value = payload?.[0]?.value;
  if (!active || value == null) return null;
  return (
    <div className="rounded-xl border border-border bg-card px-3 py-2 text-xs shadow-lg tabular-nums">
      <p className="mb-0.5 text-muted-foreground">{formatSeconds(Number(label))}</p>
      <p className="font-semibold">{formatter(Number(value))}</p>
    </div>
  );
}

function SeriesChart({
  data,
  dataKey,
  name,
  color,
  colors,
  format,
  inverted,
  unit,
  zones,
}: {
  data: SeriesPoint[];
  dataKey: keyof SeriesPoint;
  name: string;
  color: string;
  colors: ChartTheme;
  format: (value: number) => string;
  inverted?: boolean;
  unit?: string;
  zones?: NonNullable<ActivitySeries["hr_zones"]> | null;
}) {
  return (
    <ResponsiveContainer>
      <ComposedChart data={data} margin={{ top: 5, right: 5, left: -15, bottom: 0 }}>
        <CartesianGrid stroke={colors.grid} strokeDasharray="3 3" vertical={false} />
        <XAxis
          dataKey="t"
          type="number"
          domain={[0, "dataMax"]}
          {...axisProps(colors)}
          minTickGap={48}
          tickFormatter={(v: number) => formatSeconds(v)}
        />
        <YAxis
          {...axisProps(colors)}
          domain={["auto", "auto"]}
          reversed={inverted}
          unit={unit}
          tickFormatter={(v: number) => format(v)}
        />
        {zones &&
          (Object.keys(ZONE_COLORS) as Array<keyof typeof ZONE_COLORS>).map((z) => (
            <ReferenceArea
              key={z}
              y1={zones[z][0]}
              y2={zones[z][1]}
              fill={ZONE_COLORS[z]}
              fillOpacity={0.09}
              ifOverflow="hidden"
            />
          ))}
        <Tooltip content={<SeriesTooltip formatter={format} />} />
        <Line
          type="monotone"
          dataKey={dataKey}
          name={name}
          stroke={color}
          strokeWidth={1.5}
          dot={false}
          connectNulls
        />
      </ComposedChart>
    </ResponsiveContainer>
  );
}

function SplitsTable({ splits }: { splits: NonNullable<ActivitySeries["splits"]> }) {
  return (
    <div className="relative">
      {/* Right-edge fade hints that the table scrolls horizontally on narrow screens. */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-y-0 right-0 w-6 bg-gradient-to-r from-transparent to-card"
      />
      <div className="overflow-x-auto">
        <table className="w-full text-sm tabular-nums">
          <thead>
            <tr className="text-left text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
              <th className="py-1.5 pr-3 font-medium">km</th>
              <th className="py-1.5 pr-3 font-medium">Pace</th>
              <th className="py-1.5 pr-3 font-medium">HR</th>
              <th className="py-1.5 font-medium">Elev</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {splits.map((s) => {
              // Partial (non-1 km) laps show their real distance instead of the lap number.
              const partial = s.distance_m != null && Math.abs(s.distance_m - 1000) > 50;
              return (
                <tr key={s.index}>
                  <td className="py-1.5 pr-3 font-medium">
                    {partial ? `${((s.distance_m ?? 0) / 1000).toFixed(2)} km` : s.index}
                  </td>
                  <td className="py-1.5 pr-3">{s.avg_pace ? `${s.avg_pace} /km` : "–"}</td>
                  <td className="py-1.5 pr-3">{s.avg_hr != null ? Math.round(s.avg_hr) : "–"}</td>
                  <td className="py-1.5 text-muted-foreground">
                    {s.elevation_gain_m != null ? `+${Math.round(s.elevation_gain_m)} m` : "–"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/**
 * Series/splits/route for an activity, fetched separately from the detail
 * payload because the first call hits Garmin and can take a couple of seconds.
 * Lifted to a hook so the page can feed both the top-of-page route map and
 * the charts section from ONE request.
 */
export function useActivitySeries(activityId: number) {
  const [data, setData] = React.useState<ActivitySeries | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState(false);

  React.useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(false);
    api
      .activitySeries(activityId)
      .then((d) => {
        if (!cancelled) setData(d);
      })
      .catch(() => {
        // 502 = Garmin unreachable and nothing cached; treat like "no data".
        if (!cancelled) setError(true);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [activityId]);

  return { data, loading, error };
}

/** Route map slot: map-sized skeleton while loading (avoids layout shift for
 *  GPS runs), collapses to nothing once we know the run has no route. */
export function ActivityRouteSection({
  data,
  loading,
}: {
  data: ActivitySeries | null;
  loading: boolean;
}) {
  if (loading) return <Skeleton className="h-64 rounded-2xl sm:h-96" />;
  if (!data?.route || data.route.length < 2) return null;
  return <ActivityMap route={data.route} />;
}

/** Per-second charts + splits for an activity. */
export function ActivitySeriesSection({
  data,
  loading,
  error,
}: {
  data: ActivitySeries | null;
  loading: boolean;
  error: boolean;
}) {
  const colors = useChartTheme();

  if (loading) {
    return (
      <div className="space-y-5">
        <Skeleton className="h-64 rounded-2xl" />
        <Skeleton className="h-64 rounded-2xl" />
      </div>
    );
  }

  if (error || !data || (!data.series && !data.splits)) {
    return <p className="text-xs text-muted-foreground">No per-second data for this activity.</p>;
  }

  const points = data.series ? preparePoints(data.series) : [];
  const hasPace = points.some((p) => p.pace != null);
  const hasHr = points.some((p) => p.hr != null);
  const hasElev = points.some((p) => p.elev != null);
  const hasCad = points.some((p) => p.cad != null);

  return (
    <div className="space-y-5">
      {hasPace && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle>Pace</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="h-48 w-full sm:h-56">
              <SeriesChart
                data={points}
                dataKey="pace"
                name="Pace"
                color={colors.blue}
                colors={colors}
                format={(v) => `${formatSeconds(v)} /km`}
                inverted
              />
            </div>
          </CardContent>
        </Card>
      )}

      {hasHr && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle>Heart rate</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="h-48 w-full sm:h-56">
              <SeriesChart
                data={points}
                dataKey="hr"
                name="HR"
                color={colors.accent}
                colors={colors}
                format={(v) => `${Math.round(v)} bpm`}
                zones={data.hr_zones}
              />
            </div>
          </CardContent>
        </Card>
      )}

      {(hasElev || hasCad) && (
        <div className="grid gap-5 sm:grid-cols-2">
          {hasElev && (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-medium">Elevation</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="h-32 w-full">
                  <SeriesChart
                    data={points}
                    dataKey="elev"
                    name="Elevation"
                    color={colors.teal}
                    colors={colors}
                    format={(v) => `${Math.round(v)} m`}
                  />
                </div>
              </CardContent>
            </Card>
          )}
          {hasCad && (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-medium">Cadence</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="h-32 w-full">
                  <SeriesChart
                    data={points}
                    dataKey="cad"
                    name="Cadence"
                    color={colors.indigo}
                    colors={colors}
                    format={(v) => `${Math.round(v)} spm`}
                  />
                </div>
              </CardContent>
            </Card>
          )}
        </div>
      )}

      {data.splits && data.splits.length > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle>Splits</CardTitle>
          </CardHeader>
          <CardContent>
            <SplitsTable splits={data.splits} />
          </CardContent>
        </Card>
      )}
    </div>
  );
}
