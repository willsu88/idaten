"use client";

import * as React from "react";
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { SleepDay, SleepNight, SleepScoreComponent } from "@/lib/types";
import { api, safe } from "@/lib/api";
import {
  LEVEL_TO_STAGE,
  STAGE_LABELS,
  STAGE_ROWS,
  StageKey,
  bedtimeHour,
  clockHour,
  fmtDuration,
  fmtHourOfDay,
  stageShares,
} from "@/lib/sleep";
import { PageHeader } from "@/components/page-header";
import { ChartTooltip, useChartTheme, type ChartTheme } from "@/components/charts";
import { MetricInfo } from "@/components/metric-info";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { APP_LOCALE, cn } from "@/lib/utils";

const RANGES = [30, 90] as const;

function stageColor(colors: ChartTheme, stage: StageKey): string {
  return { deep: colors.indigo, light: colors.blue, rem: colors.teal, awake: colors.amber }[stage];
}

const QUALIFIER_CLASSES: Record<string, string> = {
  EXCELLENT: "text-success",
  GOOD: "text-success",
  FAIR: "text-warning",
  POOR: "text-danger",
};

function QualifierChip({ qualifier }: { qualifier: string | null | undefined }) {
  if (!qualifier) return null;
  return (
    <span className={cn("text-[11px] font-semibold uppercase tracking-wider",
      QUALIFIER_CLASSES[qualifier] ?? "text-muted-foreground")}>
      {qualifier.toLowerCase()}
    </span>
  );
}

function fmtClockMs(ms: number): string {
  return new Date(ms).toLocaleTimeString(APP_LOCALE, { hour: "numeric", minute: "2-digit" });
}

function shortDate(dateStr: string): string {
  return new Date(`${dateStr}T00:00:00`).toLocaleDateString(APP_LOCALE, {
    month: "short",
    day: "numeric",
  });
}

/** Sentence-case a Garmin feedback enum: "IDEAL_DURATION_LOW_NEED" → "Ideal duration low need". */
function humanizeEnum(value: string | null | undefined): string | null {
  if (!value) return null;
  const s = value.toLowerCase().replace(/_/g, " ");
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function ScoreDial({ score, qualifier }: { score: number | null; qualifier: string | null }) {
  const r = 44;
  const c = 2 * Math.PI * r;
  const filled = score == null ? 0 : (c * Math.min(Math.max(score, 0), 100)) / 100;
  const cls = qualifier ? QUALIFIER_CLASSES[qualifier] : undefined;
  return (
    <div className="relative h-28 w-28 shrink-0">
      <svg viewBox="0 0 100 100" className="h-full w-full -rotate-90">
        <circle cx="50" cy="50" r={r} fill="none" strokeWidth="8" className="stroke-muted" />
        <circle
          cx="50" cy="50" r={r} fill="none" strokeWidth="8" strokeLinecap="round"
          className={cn("stroke-current", cls ?? "text-accent")}
          strokeDasharray={`${filled} ${c - filled}`}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-3xl font-bold tabular-nums">{score ?? "–"}</span>
        <span className="text-[10px] uppercase tracking-wider text-muted-foreground">Score</span>
      </div>
    </div>
  );
}

/** The night's stage timeline: one colored band per hypnogram segment. */
function Hypnogram({ night, colors }: { night: SleepNight; colors: ChartTheme }) {
  const segs = night.hypnogram ?? [];
  if (segs.length === 0 || night.bedtime_ms == null || night.wake_ms == null) return null;
  const t0 = night.bedtime_ms;
  const t1 = night.wake_ms;
  const span = t1 - t0;
  if (span <= 0) return null;

  const W = 1000;
  const ROW_H = 26;
  const H = ROW_H * STAGE_ROWS.length;
  const x = (t: number) => Math.max(0, Math.min(W, ((t - t0) / span) * W));

  // Hour ticks, at most ~6 so labels never collide.
  const tickEveryH = Math.max(1, Math.ceil(span / 3600000 / 6));
  const ticks: number[] = [];
  const firstTick = Math.ceil(t0 / 3600000) * 3600000;
  for (let t = firstTick; t <= t1; t += tickEveryH * 3600000) ticks.push(t);

  return (
    <div>
      <div className="flex">
        <div className="flex w-12 shrink-0 flex-col justify-between py-0.5 pr-2 text-right text-[10px] text-muted-foreground"
          style={{ height: H }}>
          {STAGE_ROWS.map((s) => (
            <span key={s} style={{ lineHeight: `${ROW_H}px` }}>{STAGE_LABELS[s]}</span>
          ))}
        </div>
        <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ height: H }} preserveAspectRatio="none">
          {STAGE_ROWS.map((_, i) => (
            <line key={i} x1={0} x2={W} y1={ROW_H * (i + 1)} y2={ROW_H * (i + 1)}
              stroke={colors.grid} strokeWidth={1} />
          ))}
          {segs.map((seg, i) => {
            const stage = LEVEL_TO_STAGE[seg.level];
            if (!stage) return null;
            const row = STAGE_ROWS.indexOf(stage);
            const x0 = x(seg.start_ms);
            const w = Math.max(x(seg.end_ms) - x0, 2);
            return (
              <rect key={i} x={x0} y={row * ROW_H + 4} width={w} height={ROW_H - 8} rx={3}
                fill={stageColor(colors, stage)}>
                <title>{`${STAGE_LABELS[stage]} ${fmtClockMs(seg.start_ms)}–${fmtClockMs(seg.end_ms)}`}</title>
              </rect>
            );
          })}
        </svg>
      </div>
      <div className="ml-12 flex justify-between text-[10px] tabular-nums text-muted-foreground">
        <span>{fmtClockMs(t0)}</span>
        {ticks.slice(1, -1).map((t) => <span key={t}>{fmtClockMs(t)}</span>)}
        <span>{fmtClockMs(t1)}</span>
      </div>
    </div>
  );
}

/** One stage's share of the night with Garmin's optimal band under it. */
function StageBars({ night, colors }: { night: SleepNight; colors: ChartTheme }) {
  if (!night.stages) return null;
  const shares = stageShares(night.stages);
  const comp = night.score?.components ?? {};
  const OPTIMAL_KEY: Partial<Record<StageKey, string>> = {
    deep: "deep_percentage",
    light: "light_percentage",
    rem: "rem_percentage",
  };
  return (
    <div className="grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-4">
      {shares.map(({ key, seconds, pct }) => {
        const c = OPTIMAL_KEY[key] ? comp[OPTIMAL_KEY[key] as string] : undefined;
        return (
          <div key={key}>
            <div className="flex items-baseline justify-between">
              <span className="text-xs font-medium text-muted-foreground">{STAGE_LABELS[key]}</span>
              <span className="text-xs tabular-nums text-muted-foreground">{pct}%</span>
            </div>
            <p className="text-sm font-semibold tabular-nums">{fmtDuration(seconds)}</p>
            <div className="relative mt-1 h-1.5 overflow-hidden rounded-full bg-muted">
              {c?.optimal_start != null && c?.optimal_end != null && (
                <div
                  className="absolute inset-y-0 rounded-full bg-foreground/15"
                  style={{ left: `${c.optimal_start}%`, width: `${c.optimal_end - c.optimal_start}%` }}
                />
              )}
              <div
                className="absolute inset-y-0 left-0 rounded-full"
                style={{ width: `${Math.min(pct, 100)}%`, background: stageColor(colors, key) }}
              />
            </div>
            {c && <QualifierChip qualifier={c.qualifier} />}
          </div>
        );
      })}
    </div>
  );
}

const COMPONENT_LABELS: Record<string, string> = {
  total_duration: "Duration",
  stress: "Overnight stress",
  awake_count: "Awakenings",
  restlessness: "Restlessness",
  rem_percentage: "REM share",
  light_percentage: "Light share",
  deep_percentage: "Deep share",
};

function ScoreBreakdown({ components }: { components: Record<string, SleepScoreComponent> }) {
  const rows = Object.entries(COMPONENT_LABELS)
    .filter(([key]) => components[key])
    .map(([key, label]) => ({ key, label, c: components[key] }));
  if (rows.length === 0) return null;
  return (
    <div className="divide-y divide-border/60">
      {rows.map(({ key, label, c }) => (
        <div key={key} className="flex items-center justify-between py-2 first:pt-0 last:pb-0">
          <span className="text-sm">{label}</span>
          <span className="flex items-baseline gap-2">
            {c.value != null && (
              <span className="text-sm font-semibold tabular-nums">{c.value}%</span>
            )}
            <QualifierChip qualifier={c.qualifier} />
          </span>
        </div>
      ))}
    </div>
  );
}

const ADJUSTMENT_LABELS: Record<string, string> = {
  history_adjustment: "Sleep history",
  training_feedback: "Training",
  hrv_adjustment: "HRV",
  nap_adjustment: "Naps",
};

function NeedCard({ night }: { night: SleepNight }) {
  const need = night.need;
  if (!need || need.actual_min == null) return null;
  const sleptS =
    (night.stages?.deep_s ?? 0) + (night.stages?.light_s ?? 0) + (night.stages?.rem_s ?? 0);
  const needS = need.actual_min * 60;
  const met = needS > 0 ? Math.min(Math.round((sleptS / needS) * 100), 100) : null;
  const adjustments = Object.entries(ADJUSTMENT_LABELS)
    .map(([key, label]) => ({ label, value: need[key as keyof typeof need] as string | null }))
    .filter((a) => a.value && a.value !== "NO_CHANGE");
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-1.5">
          Sleep need
          <MetricInfo id="sleep_need" />
        </CardTitle>
        <CardDescription>
          You needed {fmtDuration(needS)} and slept {fmtDuration(sleptS)}
          {met != null && ` — ${met}% of your need`}
        </CardDescription>
      </CardHeader>
      <CardContent>
        {met != null && (
          <div className="mb-3 h-2 overflow-hidden rounded-full bg-muted">
            <div
              className={cn("h-full rounded-full", met >= 95 ? "bg-success" : met >= 80 ? "bg-warning" : "bg-danger")}
              style={{ width: `${met}%` }}
            />
          </div>
        )}
        {adjustments.length > 0 && (
          <div className="space-y-1">
            {adjustments.map((a) => (
              <p key={a.label} className="flex justify-between text-xs">
                <span className="text-muted-foreground">{a.label}</span>
                <span className="font-medium">{humanizeEnum(a.value)}</span>
              </p>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function NapsCard({ night }: { night: SleepNight }) {
  const naps = night.naps ?? [];
  if (naps.length === 0) return null;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Naps</CardTitle>
        <CardDescription>
          {naps.length === 1 ? "One nap" : `${naps.length} naps`} — naps count toward tonight&apos;s
          sleep need
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        {naps.map((n, i) => (
          <div key={i} className="flex items-center justify-between rounded-xl border border-border bg-background/50 px-3 py-2">
            <span className="text-sm tabular-nums">
              {n.start_ms != null && n.end_ms != null
                ? `${fmtClockMs(n.start_ms)} – ${fmtClockMs(n.end_ms)}`
                : "–"}
            </span>
            <span className="flex items-baseline gap-2">
              <span className="text-sm font-semibold tabular-nums">{fmtDuration(n.seconds)}</span>
              {n.feedback && (
                <span className="text-xs text-muted-foreground">{humanizeEnum(n.feedback)}</span>
              )}
            </span>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

function OvernightChart({
  title, points, color, unit, domain, colors,
}: {
  title: string;
  points: { t: number; v: number }[];
  color: string;
  unit?: string;
  // Units live in the tooltip, not the axis ticks — a fixed 34px axis keeps
  // the four small multiples aligned without clipping labels.
  domain?: [number | "auto", number | "auto"];
  colors: ChartTheme;
}) {
  if (points.length === 0) return null;
  return (
    <div>
      <p className="mb-1 text-xs font-medium uppercase tracking-wider text-muted-foreground">{title}</p>
      <div className="h-28 w-full">
        <ResponsiveContainer>
          <ComposedChart data={points} margin={{ top: 5, right: 5, left: 0, bottom: 0 }}>
            <CartesianGrid stroke={colors.grid} strokeDasharray="3 3" vertical={false} />
            <XAxis
              dataKey="t" type="number" domain={["dataMin", "dataMax"]} scale="time"
              stroke={colors.axis} fontSize={10} tickLine={false} axisLine={false}
              tickFormatter={(t: number) => fmtClockMs(t)} minTickGap={48}
            />
            <YAxis stroke={colors.axis} fontSize={10} tickLine={false} axisLine={false}
              domain={domain ?? ["auto", "auto"]} width={34} allowDataOverflow={false} />
            <Tooltip
              content={<ChartTooltip formatter={(v) => `${Math.round(v * 10) / 10}${unit ?? ""}`} />}
              labelFormatter={(t) => fmtClockMs(Number(t))}
            />
            <Line dataKey="v" name={title} type="monotone" stroke={color} dot={false} strokeWidth={2} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function ChartCard({
  title, description, info, children,
}: {
  title: string;
  description?: string;
  info?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-1.5">{title}{info}</CardTitle>
        {description && <CardDescription>{description}</CardDescription>}
      </CardHeader>
      <CardContent>
        <div className="h-52 w-full sm:h-60">{children}</div>
      </CardContent>
    </Card>
  );
}

export default function SleepPage() {
  const [range, setRange] = React.useState<number>(30);
  const [daily, setDaily] = React.useState<SleepDay[] | null>(null);
  const [night, setNight] = React.useState<SleepNight | null>(null);
  const [loading, setLoading] = React.useState(true);
  const colors = useChartTheme();

  React.useEffect(() => {
    let cancelled = false;
    setLoading(true);
    safe(api.sleepDaily(range))
      .then(async (res) => {
        if (cancelled) return;
        const days = res?.daily ?? [];
        setDaily(days);
        const latest = [...days].reverse().find((d) => d.sleep_hours != null);
        if (latest) {
          const n = await safe(api.sleepNight(latest.date));
          if (!cancelled) setNight(n);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [range]);

  const trendData = React.useMemo(
    () =>
      (daily ?? []).map((d) => ({
        ...d,
        label: shortDate(d.date),
        bed_h: d.bedtime ? bedtimeHour(d.bedtime) : null,
        wake_h: d.wake_time ? clockHour(d.wake_time) : null,
      })),
    [daily],
  );
  const hasStageTrend = trendData.some((d) => d.deep_hours != null);
  const hasNight = night?.available === true;
  const latestDay = React.useMemo(
    () => [...(daily ?? [])].reverse().find((d) => d.sleep_hours != null) ?? null,
    [daily],
  );

  const axisProps = { stroke: colors.axis, fontSize: 11, tickLine: false, axisLine: false } as const;
  const hourTick = (v: number) => fmtHourOfDay(v, APP_LOCALE);

  return (
    <div>
      <PageHeader
        title="Sleep"
        subtitle="Last night in detail, and how your sleep is trending"
        actions={
          <Tabs value={String(range)} onValueChange={(v) => setRange(Number(v))}>
            <TabsList>
              {RANGES.map((r) => (
                <TabsTrigger key={r} value={String(r)}>{r}d</TabsTrigger>
              ))}
            </TabsList>
          </Tabs>
        }
      />

      {loading ? (
        <div className="space-y-5">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-72 rounded-2xl" />
          ))}
        </div>
      ) : !daily || daily.every((d) => d.sleep_hours == null) ? (
        <Card>
          <CardContent className="p-6 text-sm text-muted-foreground">
            No sleep data yet — run a sync to pull your Garmin history.
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-5">
          {/* Last night */}
          {hasNight && night && latestDay ? (
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-1.5">
                  {shortDate(night.date)}
                  <MetricInfo id="sleep_score" />
                </CardTitle>
                <CardDescription>
                  {night.bedtime_ms != null && night.wake_ms != null &&
                    `${fmtClockMs(night.bedtime_ms)} – ${fmtClockMs(night.wake_ms)}`}
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-5">
                <div className="flex flex-col gap-5 sm:flex-row sm:items-center">
                  <div className="flex items-center gap-5">
                    <ScoreDial score={night.score?.overall ?? null} qualifier={night.score?.qualifier ?? null} />
                    <div>
                      <p className="text-2xl font-bold tabular-nums">
                        {fmtDuration(
                          (night.stages?.deep_s ?? 0) + (night.stages?.light_s ?? 0) + (night.stages?.rem_s ?? 0),
                        )}
                      </p>
                      <p className="text-xs text-muted-foreground">asleep</p>
                      {night.score?.qualifier && <QualifierChip qualifier={night.score.qualifier} />}
                    </div>
                  </div>
                  <div className="flex-1">
                    <StageBars night={night} colors={colors} />
                  </div>
                </div>
                <Hypnogram night={night} colors={colors} />
              </CardContent>
            </Card>
          ) : (
            <Card>
              <CardContent className="p-6 text-sm text-muted-foreground">
                No detailed data for the most recent night yet — details appear for nights synced
                after the sleep page shipped (or once a backfill has run).
              </CardContent>
            </Card>
          )}

          {hasNight && night && (
            <div className="grid gap-5 lg:grid-cols-2">
              {night.score && Object.keys(night.score.components).length > 0 && (
                <Card>
                  <CardHeader>
                    <CardTitle>Why this score</CardTitle>
                    <CardDescription>Garmin&apos;s ingredients for last night&apos;s {night.score.overall}</CardDescription>
                  </CardHeader>
                  <CardContent>
                    <ScoreBreakdown components={night.score.components} />
                  </CardContent>
                </Card>
              )}
              <div className="space-y-5">
                <NeedCard night={night} />
                <NapsCard night={night} />
              </div>
            </div>
          )}

          {hasNight && night?.series && (
            <Card>
              <CardHeader>
                <CardTitle>Overnight</CardTitle>
                <CardDescription>
                  {[
                    night.physio?.avg_overnight_hrv != null && `HRV ${Math.round(night.physio.avg_overnight_hrv)} ms`,
                    night.physio?.resting_hr != null && `resting HR ${night.physio.resting_hr}`,
                    night.physio?.body_battery_change != null && `body battery +${night.physio.body_battery_change}`,
                    night.physio?.respiration?.avg != null && `${night.physio.respiration.avg} brpm`,
                  ].filter(Boolean).join(" · ")}
                </CardDescription>
              </CardHeader>
              <CardContent className="grid gap-5 sm:grid-cols-2">
                <OvernightChart title="Heart rate" points={night.series.heart_rate}
                  color={colors.accent} unit=" bpm" colors={colors} />
                <OvernightChart title="HRV" points={night.series.hrv}
                  color={colors.blue} unit=" ms" colors={colors} />
                <OvernightChart title="Body battery" points={night.series.body_battery}
                  color={colors.teal} domain={[0, 100]} colors={colors} />
                <OvernightChart title="Stress" points={night.series.stress}
                  color={colors.amber} domain={[0, "auto"]} colors={colors} />
              </CardContent>
            </Card>
          )}

          {/* Trends */}
          <ChartCard
            title="Duration vs need"
            description={hasStageTrend
              ? "Time in each stage per night, against Garmin's sleep need"
              : "Hours per night against Garmin's sleep need (stages appear after a backfill)"}
            info={<MetricInfo id="sleep_need" />}
          >
            <ResponsiveContainer>
              <ComposedChart data={trendData} margin={{ top: 5, right: 5, left: -20, bottom: 0 }}>
                <CartesianGrid stroke={colors.grid} strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="label" {...axisProps} minTickGap={32} />
                <YAxis {...axisProps} domain={[0, "auto"]} unit="h" />
                <Tooltip content={<ChartTooltip formatter={(v) => `${v.toFixed(1)}h`} />} />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                {hasStageTrend ? (
                  <>
                    <Bar dataKey="deep_hours" name="Deep" stackId="s" fill={stageColor(colors, "deep")} />
                    <Bar dataKey="light_hours" name="Light" stackId="s" fill={stageColor(colors, "light")} />
                    <Bar dataKey="rem_hours" name="REM" stackId="s" fill={stageColor(colors, "rem")}
                      radius={[3, 3, 0, 0]} />
                    <Bar dataKey="nap_hours" name="Naps" stackId="s" fill={colors.muted}
                      radius={[3, 3, 0, 0]} />
                  </>
                ) : (
                  <Bar dataKey="sleep_hours" name="Hours" stackId="s" fill={colors.indigo}
                    opacity={0.75} radius={[3, 3, 0, 0]} />
                )}
                <Line type="monotone" dataKey="need_hours" name="Need" stroke={colors.muted}
                  strokeDasharray="5 4" dot={false} strokeWidth={1.5} connectNulls />
              </ComposedChart>
            </ResponsiveContainer>
          </ChartCard>

          <ChartCard title="Sleep score" description="Garmin sleep score per night"
            info={<MetricInfo id="sleep_score" />}>
            <ResponsiveContainer>
              <ComposedChart data={trendData} margin={{ top: 5, right: 5, left: -20, bottom: 0 }}>
                <CartesianGrid stroke={colors.grid} strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="label" {...axisProps} minTickGap={32} />
                <YAxis {...axisProps} domain={[0, 100]} />
                <Tooltip content={<ChartTooltip formatter={(v) => String(Math.round(v))} />} />
                <Line type="monotone" dataKey="sleep_score" name="Score" stroke={colors.amber}
                  dot={false} strokeWidth={2} connectNulls />
              </ComposedChart>
            </ResponsiveContainer>
          </ChartCard>

          {trendData.some((d) => d.bed_h != null) && (
            <Card>
              <CardHeader>
                <CardTitle>Consistency</CardTitle>
                <CardDescription>
                  Bed and wake times per night — a steady rhythm is worth as much as total hours
                </CardDescription>
              </CardHeader>
              <CardContent className="grid gap-5 sm:grid-cols-2">
                <div>
                  <p className="mb-1 text-xs font-medium uppercase tracking-wider text-muted-foreground">Bedtime</p>
                  <div className="h-36 w-full">
                    <ResponsiveContainer>
                      <ComposedChart data={trendData} margin={{ top: 5, right: 5, left: -15, bottom: 0 }}>
                        <CartesianGrid stroke={colors.grid} strokeDasharray="3 3" vertical={false} />
                        <XAxis dataKey="label" {...axisProps} minTickGap={32} />
                        <YAxis {...axisProps} domain={["auto", "auto"]} tickFormatter={hourTick} width={70} />
                        <Tooltip content={<ChartTooltip formatter={(v) => fmtHourOfDay(v, APP_LOCALE)} />} />
                        <Line type="monotone" dataKey="bed_h" name="Bedtime" stroke={colors.indigo}
                          dot={false} strokeWidth={2} connectNulls />
                      </ComposedChart>
                    </ResponsiveContainer>
                  </div>
                </div>
                <div>
                  <p className="mb-1 text-xs font-medium uppercase tracking-wider text-muted-foreground">Wake</p>
                  <div className="h-36 w-full">
                    <ResponsiveContainer>
                      <ComposedChart data={trendData} margin={{ top: 5, right: 5, left: -15, bottom: 0 }}>
                        <CartesianGrid stroke={colors.grid} strokeDasharray="3 3" vertical={false} />
                        <XAxis dataKey="label" {...axisProps} minTickGap={32} />
                        <YAxis {...axisProps} domain={["auto", "auto"]} tickFormatter={hourTick} width={70} />
                        <Tooltip content={<ChartTooltip formatter={(v) => fmtHourOfDay(v, APP_LOCALE)} />} />
                        <Line type="monotone" dataKey="wake_h" name="Wake" stroke={colors.teal}
                          dot={false} strokeWidth={2} connectNulls />
                      </ComposedChart>
                    </ResponsiveContainer>
                  </div>
                </div>
              </CardContent>
            </Card>
          )}
        </div>
      )}
    </div>
  );
}
