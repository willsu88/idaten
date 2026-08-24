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
import { ChevronDown } from "lucide-react";
import type { Analytics, Race, TrendPoint } from "@/lib/types";
import { api, safe } from "@/lib/api";
import { aggregateWeeklyDistance, deriveTrendTiles, easySharePct } from "@/lib/trends";
import { CoachHint } from "@/components/coach-hint";
import { PageHeader } from "@/components/page-header";
import { ChartTooltip, useChartTheme } from "@/components/charts";
import { MetricInfo } from "@/components/metric-info";
import { StatTile } from "@/components/stat-tile";
import { RampChart, RampStatusChip } from "@/components/ramp-chart";
import {
  AcwrChart,
  EasyHardChart,
  EfChart,
  HrDriftChart,
  RaceOutlookCard,
  RestingHrChart,
  Vo2maxChart,
  ZonesWeeklyChart,
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

/**
 * Per-section disclosure for the deep-dive charts. Children only mount when
 * opened, so a closed section costs nothing and recharts always measures a
 * visible container.
 */
function MoreCharts({ count, children }: { count: number; children: React.ReactNode }) {
  const [open, setOpen] = React.useState(false);
  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex min-h-9 items-center gap-1.5 rounded-full border border-border bg-card px-4 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground"
      >
        <ChevronDown className={cn("h-4 w-4 transition-transform", open && "rotate-180")} />
        {open ? "Hide detail charts" : `More charts (${count})`}
      </button>
      {open && <div className="mt-5 space-y-5">{children}</div>}
    </div>
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
  const tiles = React.useMemo(() => deriveTrendTiles(daily ?? [], analytics), [daily, analytics]);
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
          {/* The glanceable tier: four verdicts before any chart. */}
          <div className="mb-5 grid grid-cols-2 gap-2 lg:grid-cols-4">
            {tiles.map((t) => (
              <StatTile
                key={t.key}
                label={t.label}
                value={t.value}
                sub={t.sub}
                tone={t.tone}
                direction={t.direction}
                spark={t.spark}
                href={t.key === "sleep" ? "/sleep" : undefined}
              />
            ))}
          </div>

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

            <MoreCharts count={2}>
              <ChartCard title="Sleep" description="Hours per night — score and stages live on the Sleep page">
                <ResponsiveContainer>
                  <ComposedChart data={data} margin={{ top: 5, right: 5, left: -20, bottom: 0 }}>
                    <CartesianGrid stroke={colors.grid} strokeDasharray="3 3" vertical={false} />
                    <XAxis dataKey="label" {...axisProps} minTickGap={32} />
                    <YAxis {...axisProps} domain={[0, "auto"]} unit="h" />
                    <Tooltip content={<ChartTooltip />} />
                    <Bar
                      dataKey="sleep_hours"
                      name="Hours"
                      fill={colors.indigo}
                      opacity={0.75}
                      radius={[3, 3, 0, 0]}
                    />
                  </ComposedChart>
                </ResponsiveContainer>
              </ChartCard>

              <ChartCard title="Resting HR" description="Morning resting heart rate">
                <RestingHrChart data={data} colors={colors} />
              </ChartCard>
            </MoreCharts>

            <SectionHeading id="training-load" title="Training load" />

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

            <MoreCharts count={7}>
              <ChartCard
                title="Fitness & fatigue"
                description="Long-term fitness (CTL) vs short-term fatigue (ATL)"
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
                    <Legend iconType="plainline" wrapperStyle={{ fontSize: 12 }} />
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

              <ChartCard title="Daily load" description="Training load per day">
                <ResponsiveContainer>
                  <ComposedChart data={data} margin={{ top: 5, right: 5, left: -20, bottom: 0 }}>
                    <CartesianGrid stroke={colors.grid} strokeDasharray="3 3" vertical={false} />
                    <XAxis dataKey="label" {...axisProps} minTickGap={32} />
                    <YAxis {...axisProps} />
                    <Tooltip content={<ChartTooltip formatter={(v) => String(Math.round(v))} />} />
                    <Bar
                      dataKey="training_load"
                      name="Load"
                      fill={colors.indigo}
                      opacity={0.6}
                      radius={[3, 3, 0, 0]}
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
                title="Easy vs hard"
                description={`Share of ${isDaily ? "daily" : "weekly"} time in easy zones (Z1+Z2) — polarized training aims for roughly 80/20`}
                footer={
                  easyShare != null ? (
                    <p className="mt-2 text-xs text-muted-foreground">
                      <span className="font-semibold text-foreground">{easyShare}%</span> of your
                      time in this range is easy.
                    </p>
                  ) : undefined
                }
              >
                <EasyHardChart buckets={zoneBuckets} colors={colors} />
              </ChartCard>

              <ChartCard
                title="Time in zones"
                description={isDaily ? "Daily time per heart-rate zone" : "Weekly time per heart-rate zone"}
              >
                <ZonesWeeklyChart buckets={zoneBuckets} colors={colors} />
              </ChartCard>
            </MoreCharts>

            <SectionHeading id="progress" title="Progress" />

            <ChartCard
              title="Aerobic efficiency"
              description="Efficiency factor per easy run, with the rolling average as the trend"
              info={<MetricInfo id="ef" />}
            >
              <EfChart points={analytics?.ef_series ?? []} colors={colors} />
            </ChartCard>

            <MoreCharts count={2}>
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
            </MoreCharts>

            {races.length > 0 && <RaceOutlookCard races={races} />}
          </div>
        </>
      )}
    </div>
  );
}
