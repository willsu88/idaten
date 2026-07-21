"use client";

import * as React from "react";
import {
  Area,
  Bar,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { Analytics, Race, TrendPoint } from "@/lib/types";
import { api, safe } from "@/lib/api";
import { CoachHint } from "@/components/coach-hint";
import { PageHeader } from "@/components/page-header";
import { ChartTooltip, useChartTheme } from "@/components/charts";
import { MetricInfo } from "@/components/metric-info";
import { RampChart, RampStatusChip } from "@/components/ramp-chart";
import {
  AcwrChart,
  EfChart,
  EfLegend,
  HrDriftChart,
  RaceOutlookCard,
  RestingHrChart,
  Vo2maxChart,
  ZonesWeeklyChart,
  easySharePct,
} from "@/components/analytics-charts";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { APP_LOCALE, cn } from "@/lib/utils";

const RANGES = [7, 30, 90, 180] as const;
const RANGE_KEY = "trends_range_days";
const DEFAULT_RANGE = 7; // first-ever visit

function loadRange(): number {
  if (typeof window === "undefined") return DEFAULT_RANGE;
  const saved = Number(window.localStorage.getItem(RANGE_KEY));
  return RANGES.includes(saved as (typeof RANGES)[number]) ? saved : DEFAULT_RANGE;
}

const SECTIONS = [
  { id: "recovery", label: "Recovery" },
  { id: "training-load", label: "Training load" },
  { id: "progress", label: "Progress" },
] as const;

type SectionId = (typeof SECTIONS)[number]["id"];

function shortDate(dateStr: string): string {
  const d = new Date(`${dateStr}T00:00:00`);
  return d.toLocaleDateString(APP_LOCALE, { month: "short", day: "numeric" });
}

/** ISO week key like "2026-W29" and its Monday date for labeling. */
function isoWeekOf(dateStr: string): { key: string; monday: string } {
  const d = new Date(`${dateStr}T00:00:00`);
  const day = (d.getDay() + 6) % 7; // Mon = 0
  const monday = new Date(d);
  monday.setDate(d.getDate() - day);
  const thursday = new Date(monday);
  thursday.setDate(monday.getDate() + 3);
  const yearStart = new Date(thursday.getFullYear(), 0, 1);
  const week = Math.ceil(((thursday.getTime() - yearStart.getTime()) / 86400000 + 1) / 7);
  const mondayStr = `${monday.getFullYear()}-${String(monday.getMonth() + 1).padStart(2, "0")}-${String(monday.getDate()).padStart(2, "0")}`;
  return { key: `${thursday.getFullYear()}-W${String(week).padStart(2, "0")}`, monday: mondayStr };
}

function aggregateWeeklyDistance(daily: TrendPoint[]) {
  const weeks = new Map<string, { week: string; monday: string; distance_km: number }>();
  for (const p of daily) {
    if (p.distance_km == null) continue;
    const { key, monday } = isoWeekOf(p.date);
    const entry = weeks.get(key) ?? { week: key, monday, distance_km: 0 };
    entry.distance_km += p.distance_km;
    weeks.set(key, entry);
  }
  return Array.from(weeks.values())
    .sort((a, b) => a.monday.localeCompare(b.monday))
    .map((w) => ({ ...w, distance_km: Math.round(w.distance_km * 10) / 10 }));
}

function ChartCard({
  title,
  description,
  info,
  footer,
  children,
}: {
  title: string;
  description?: string;
  info?: React.ReactNode;
  footer?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-1.5">
          {title}
          {info}
        </CardTitle>
        {description && <CardDescription>{description}</CardDescription>}
      </CardHeader>
      <CardContent>
        <div className="h-52 w-full sm:h-64">{children}</div>
        {footer}
      </CardContent>
    </Card>
  );
}

function SectionHeading({ id, title }: { id: SectionId; title: string }) {
  return (
    <h2
      id={id}
      className="scroll-mt-20 pt-1 text-xs font-semibold uppercase tracking-wider text-muted-foreground"
    >
      {title}
    </h2>
  );
}

/** Sticky pill bar that jumps to a section and highlights the one in view. */
function SectionPills({ active }: { active: SectionId }) {
  const jump = (id: SectionId) => {
    document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
  };
  return (
    <div className="sticky top-0 z-30 -mx-4 mb-4 border-b border-border/60 bg-background/90 px-4 py-2 backdrop-blur md:-mx-8 md:px-8">
      <div className="flex gap-2 overflow-x-auto">
        {SECTIONS.map((s) => (
          <button
            key={s.id}
            type="button"
            onClick={() => jump(s.id)}
            className={cn(
              "min-h-9 shrink-0 rounded-full border px-4 text-sm font-medium transition-colors",
              active === s.id
                ? "border-accent bg-accent/10 text-accent"
                : "border-border bg-card text-muted-foreground hover:text-foreground",
            )}
          >
            {s.label}
          </button>
        ))}
      </div>
    </div>
  );
}

export default function TrendsPage() {
  // Resolved from localStorage on mount (null until then, to avoid a hydration
  // mismatch and a wasted fetch at the wrong range). First-ever visit -> 7d.
  const [range, setRange] = React.useState<number | null>(null);
  React.useEffect(() => setRange(loadRange()), []);
  const chooseRange = (r: number) => {
    setRange(r);
    if (typeof window !== "undefined") window.localStorage.setItem(RANGE_KEY, String(r));
  };
  const [daily, setDaily] = React.useState<TrendPoint[] | null>(null);
  const [analytics, setAnalytics] = React.useState<Analytics | null>(null);
  const [races, setRaces] = React.useState<Race[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState(false);
  const [activeSection, setActiveSection] = React.useState<SectionId>("recovery");
  const colors = useChartTheme();

  React.useEffect(() => {
    if (range == null) return; // wait for the stored range to resolve
    let cancelled = false;
    setLoading(true);
    Promise.all([safe(api.trends(range)), safe(api.analytics(range)), safe(api.races())])
      .then(([trendsRes, analyticsRes, racesRes]) => {
        if (cancelled) return;
        setAnalytics(analyticsRes);
        setRaces(racesRes ?? []);
        if (trendsRes) {
          setDaily(trendsRes.daily);
          setError(false);
        } else {
          setError(true);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [range]);

  const data = React.useMemo(
    () => (daily ?? []).map((p) => ({ ...p, label: shortDate(p.date) })),
    [daily],
  );
  const weekly = React.useMemo(() => aggregateWeeklyDistance(daily ?? []), [daily]);
  // The 7-day view shows the two "weekly" charts BY DAY (weekly rollups collapse
  // to one or two fat bars over a single week).
  const isDaily = range === 7;
  const distanceBars = React.useMemo(
    () =>
      isDaily
        ? (daily ?? [])
            .filter((p) => p.distance_km != null)
            .map((p) => ({ start: p.date, distance_km: Math.round((p.distance_km as number) * 10) / 10 }))
        : weekly.map((w) => ({ start: w.monday, distance_km: w.distance_km })),
    [isDaily, daily, weekly],
  );
  const zoneBuckets = React.useMemo(
    () =>
      isDaily
        ? (analytics?.zones_daily ?? []).map((d) => ({ ...d, start: d.date }))
        : (analytics?.zones_weekly ?? []).map((w) => ({ ...w, start: w.week_start })),
    [isDaily, analytics],
  );
  const easyShare = React.useMemo(() => easySharePct(zoneBuckets), [zoneBuckets]);
  const hasData = data.length > 0;

  // Scroll spy: highlight the pill of the section currently in view.
  React.useEffect(() => {
    if (!hasData) return;
    const onScroll = () => {
      let current: SectionId = SECTIONS[0].id;
      for (const s of SECTIONS) {
        const el = document.getElementById(s.id);
        if (el && el.getBoundingClientRect().top <= 96) current = s.id;
      }
      setActiveSection(current);
    };
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, [hasData]);

  const axisProps = {
    stroke: colors.axis,
    fontSize: 11,
    tickLine: false,
    axisLine: false,
  } as const;

  return (
    <div>
      <PageHeader
        title="Trends"
        subtitle="Recovery, training load, and progress over time"
        actions={
          <Tabs value={String(range ?? DEFAULT_RANGE)} onValueChange={(v) => chooseRange(Number(v))}>
            <TabsList>
              {RANGES.map((r) => (
                <TabsTrigger key={r} value={String(r)}>
                  {r}d
                </TabsTrigger>
              ))}
            </TabsList>
          </Tabs>
        }
      />

      <CoachHint page="trends" />

      {loading ? (
        <div className="space-y-5">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-80 rounded-2xl" />
          ))}
        </div>
      ) : error || !hasData ? (
        <Card>
          <CardContent className="p-6 text-sm text-muted-foreground">
            {error
              ? "Couldn't load trends — is the backend running?"
              : "No data yet — run a sync to pull your Garmin history."}
          </CardContent>
        </Card>
      ) : (
        <>
          <SectionPills active={activeSection} />

          <div className="space-y-5">
            <SectionHeading id="recovery" title="Recovery" />

            <ChartCard title="HRV" description="Nightly HRV vs 7-day baseline">
              <ResponsiveContainer>
                <ComposedChart data={data} margin={{ top: 5, right: 5, left: -20, bottom: 0 }}>
                  <CartesianGrid stroke={colors.grid} strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="label" {...axisProps} minTickGap={32} />
                  <YAxis {...axisProps} domain={["auto", "auto"]} />
                  <Tooltip content={<ChartTooltip />} />
                  <Legend iconType="plainline" wrapperStyle={{ fontSize: 12 }} />
                  <Line
                    type="monotone"
                    dataKey="hrv_baseline"
                    name="Baseline"
                    stroke={colors.muted}
                    strokeDasharray="5 4"
                    dot={false}
                    strokeWidth={1.5}
                    connectNulls
                  />
                  <Line
                    type="monotone"
                    dataKey="hrv"
                    name="HRV"
                    stroke={colors.blue}
                    dot={false}
                    strokeWidth={2}
                    connectNulls
                  />
                </ComposedChart>
              </ResponsiveContainer>
            </ChartCard>

            <ChartCard title="Sleep" description="Hours per night with Garmin sleep score">
              <ResponsiveContainer>
                <ComposedChart data={data} margin={{ top: 5, right: 5, left: -20, bottom: 0 }}>
                  <CartesianGrid stroke={colors.grid} strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="label" {...axisProps} minTickGap={32} />
                  <YAxis yAxisId="hours" {...axisProps} domain={[0, "auto"]} unit="h" />
                  <YAxis yAxisId="score" orientation="right" {...axisProps} domain={[0, 100]} hide />
                  <Tooltip content={<ChartTooltip />} />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                  <Bar
                    yAxisId="hours"
                    dataKey="sleep_hours"
                    name="Hours"
                    fill={colors.indigo}
                    opacity={0.75}
                    radius={[3, 3, 0, 0]}
                  />
                  <Line
                    yAxisId="score"
                    type="monotone"
                    dataKey="sleep_score"
                    name="Score"
                    stroke={colors.amber}
                    dot={false}
                    strokeWidth={2}
                    connectNulls
                  />
                </ComposedChart>
              </ResponsiveContainer>
            </ChartCard>

            <ChartCard title="Resting HR" description="Morning resting heart rate">
              <RestingHrChart data={data} colors={colors} />
            </ChartCard>

            <SectionHeading id="training-load" title="Training load" />

            <ChartCard
              title="Training load"
              description="Daily load with fitness (CTL) and fatigue (ATL)"
              info={
                <span className="inline-flex items-center gap-3">
                  <MetricInfo id="ctl" label="CTL" />
                  <MetricInfo id="atl" label="ATL" />
                </span>
              }
            >
              <ResponsiveContainer>
                <ComposedChart data={data} margin={{ top: 5, right: 5, left: -20, bottom: 0 }}>
                  <CartesianGrid stroke={colors.grid} strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="label" {...axisProps} minTickGap={32} />
                  <YAxis {...axisProps} />
                  <Tooltip content={<ChartTooltip />} />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                  <Bar
                    dataKey="training_load"
                    name="Load"
                    fill={colors.muted}
                    opacity={0.5}
                    radius={[3, 3, 0, 0]}
                  />
                  <Line
                    type="monotone"
                    dataKey="ctl"
                    name="CTL"
                    stroke={colors.blue}
                    dot={false}
                    strokeWidth={2}
                    connectNulls
                  />
                  <Line
                    type="monotone"
                    dataKey="atl"
                    name="ATL"
                    stroke={colors.accent}
                    dot={false}
                    strokeWidth={2}
                    connectNulls
                  />
                </ComposedChart>
              </ResponsiveContainer>
            </ChartCard>

            <ChartCard
              title="Form (TSB)"
              description="Fitness minus fatigue — positive is fresh, negative is fatigued"
              info={<MetricInfo id="tsb" />}
            >
              <ResponsiveContainer>
                <ComposedChart data={data} margin={{ top: 5, right: 5, left: -20, bottom: 0 }}>
                  <CartesianGrid stroke={colors.grid} strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="label" {...axisProps} minTickGap={32} />
                  <YAxis {...axisProps} domain={["auto", "auto"]} />
                  <ReferenceLine y={0} stroke={colors.muted} strokeDasharray="4 4" />
                  <Tooltip content={<ChartTooltip />} />
                  <Area
                    type="monotone"
                    dataKey="tsb"
                    name="TSB"
                    stroke={colors.teal}
                    fill={colors.teal}
                    fillOpacity={0.18}
                    strokeWidth={2}
                    connectNulls
                  />
                </ComposedChart>
              </ResponsiveContainer>
            </ChartCard>

            <ChartCard
              title="ACWR"
              description="Acute:chronic workload ratio — 0.8 to 1.3 is the safe zone"
              info={<MetricInfo id="acwr" />}
            >
              <AcwrChart data={data} colors={colors} />
            </ChartCard>

            <ChartCard
              title="Load ramp"
              description={`How fast your training load is growing vs what your body is used to. Staying under ${analytics?.ramp.caution ?? 1.3} is a sustainable build; above ${analytics?.ramp.high ?? 1.5} is injury territory.`}
              info={
                <span className="inline-flex items-center gap-2">
                  <MetricInfo id="ramp" />
                  <RampStatusChip ramp={analytics?.ramp ?? null} />
                </span>
              }
            >
              <RampChart ramp={analytics?.ramp ?? null} colors={colors} />
            </ChartCard>

            <ChartCard
              title={isDaily ? "Daily distance" : "Weekly distance"}
              description={isDaily ? "Kilometers per day" : "Kilometers per ISO week"}
            >
              <ResponsiveContainer>
                <ComposedChart data={distanceBars} margin={{ top: 5, right: 5, left: -20, bottom: 0 }}>
                  <CartesianGrid stroke={colors.grid} strokeDasharray="3 3" vertical={false} />
                  <XAxis
                    dataKey="start"
                    {...axisProps}
                    minTickGap={24}
                    tickFormatter={(v: string) => shortDate(v)}
                  />
                  <YAxis {...axisProps} unit=" km" />
                  <Tooltip
                    content={<ChartTooltip formatter={(v) => `${v.toFixed(1)} km`} />}
                  />
                  <Bar
                    dataKey="distance_km"
                    name="Distance"
                    fill={colors.accent}
                    radius={[4, 4, 0, 0]}
                  />
                </ComposedChart>
              </ResponsiveContainer>
            </ChartCard>

            <ChartCard
              title="Time in zones"
              description={isDaily ? "Daily time per heart-rate zone" : "Weekly time per heart-rate zone"}
              footer={
                easyShare != null ? (
                  <p className="mt-2 text-xs text-muted-foreground">
                    <span className="font-semibold text-foreground">{easyShare}%</span> of your time
                    is easy (Z1+Z2). Polarized training aims for roughly 80/20 easy vs hard.
                  </p>
                ) : undefined
              }
            >
              <ZonesWeeklyChart buckets={zoneBuckets} colors={colors} />
            </ChartCard>

            <SectionHeading id="progress" title="Progress" />

            <ChartCard
              title="Aerobic efficiency"
              description="Efficiency factor per easy run, colored by temperature, with a rolling average"
              info={<MetricInfo id="ef" />}
              footer={<EfLegend />}
            >
              <EfChart points={analytics?.ef_series ?? []} colors={colors} />
            </ChartCard>

            <ChartCard
              title="HR drift"
              description="Aerobic decoupling per run — under 5% means your aerobic base is holding up"
              info={<MetricInfo id="hr_drift" />}
            >
              <HrDriftChart points={analytics?.ef_series ?? []} colors={colors} />
            </ChartCard>

            <ChartCard
              title="VO2max"
              description="Estimated VO2max over time"
              info={<MetricInfo id="vo2max" />}
            >
              <Vo2maxChart points={analytics?.vo2max_series ?? []} colors={colors} />
            </ChartCard>

            {races.length > 0 && <RaceOutlookCard races={races} />}
          </div>
        </>
      )}
    </div>
  );
}
