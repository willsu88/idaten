"use client";

import * as React from "react";
import Link from "next/link";
import { ArrowLeft, MessageSquare, Watch } from "lucide-react";
import type { ActivityDetail } from "@/lib/types";
import { api } from "@/lib/api";
import { WORKOUT_BADGE_CLASSES, WORKOUT_LABELS } from "@/lib/workout";
import { ActivityTypeIcon } from "@/components/activity-icon";
import {
  ActivityRouteSection,
  ActivitySeriesSection,
  useActivitySeries,
} from "@/components/activity-series";
import { MetricInfo } from "@/components/metric-info";
import { ZONE_COLORS } from "@/components/analytics-charts";
import { RpeScale } from "@/components/rpe-card";
import { ExecutionScore } from "@/components/execution-score";
import { WorkoutMeta } from "@/components/workout-card";
import { ThemeToggle } from "@/components/theme-toggle";
import { Badge } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { APP_LOCALE, cn, formatDay, formatDuration, formatSeconds, prettyType } from "@/lib/utils";

function startTimeLabel(detail: ActivityDetail): string {
  if (detail.start_time_local) {
    const d = new Date(detail.start_time_local.replace(" ", "T"));
    if (!Number.isNaN(d.getTime())) {
      return `${formatDay(detail.date)} · ${d.toLocaleTimeString(APP_LOCALE, {
        hour: "2-digit",
        minute: "2-digit",
      })}`;
    }
  }
  return formatDay(detail.date);
}

// Garmin's "How did you feel?" scale (1-5), stored on the activity.
const FEEL_LABELS: Record<number, string> = {
  1: "Very Weak",
  2: "Weak",
  3: "Normal",
  4: "Strong",
  5: "Very Strong",
};

function StatTile({
  label,
  value,
  sub,
  className,
}: {
  label: string;
  value: string;
  sub?: string;
  className?: string;
}) {
  return (
    <div className={cn("rounded-xl border border-border bg-background/50 px-3 py-2.5", className)}>
      <p className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
        {label}
      </p>
      <p className="mt-0.5 text-lg font-semibold tabular-nums">
        {value}
        {sub && <span className="ml-1 text-xs font-normal text-muted-foreground">{sub}</span>}
      </p>
    </div>
  );
}

/**
 * Column spans that keep the stat grid flush for any tile count — no dangling
 * last tile. Mobile is a 2-col grid (a lone last tile goes full-width);
 * sm+ is a 6-col grid of 3 tiles per row, with the last row rebalanced to
 * rows of 2 half-and-half tiles when the count doesn't divide by 3.
 */
function statTileClass(index: number, count: number): string {
  const mobile = count % 2 === 1 && index === count - 1 ? "col-span-2" : "col-span-1";
  let sm = "sm:col-span-2";
  const rem = count % 3;
  if (count === 1) {
    sm = "sm:col-span-6";
  } else if (count === 2 || (rem === 2 && index >= count - 2)) {
    sm = "sm:col-span-3";
  } else if (rem === 1 && index >= count - 4) {
    sm = "sm:col-span-3";
  }
  return `${mobile} ${sm}`;
}

const ZONE_KEYS = ["z1", "z2", "z3", "z4", "z5"] as const;

function ZonesBar({ zones }: { zones: NonNullable<ActivityDetail["time_in_zones"]> }) {
  const total = ZONE_KEYS.reduce((sum, k) => sum + zones[k], 0);
  if (total === 0) return null;
  return (
    <div>
      <div className="flex h-4 w-full overflow-hidden rounded-full">
        {ZONE_KEYS.map(
          (k) =>
            zones[k] > 0 && (
              <div
                key={k}
                style={{ width: `${(zones[k] / total) * 100}%`, background: ZONE_COLORS[k] }}
                title={`${k.toUpperCase()} ${formatSeconds(zones[k])}`}
              />
            ),
        )}
      </div>
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1">
        {ZONE_KEYS.map(
          (k) =>
            zones[k] > 0 && (
              <span key={k} className="inline-flex items-center gap-1.5 text-xs tabular-nums">
                <span className="h-2 w-2 rounded-full" style={{ background: ZONE_COLORS[k] }} />
                <span className="font-medium">{k.toUpperCase()}</span>
                <span className="text-muted-foreground">{formatSeconds(zones[k])}</span>
              </span>
            ),
        )}
      </div>
    </div>
  );
}

export default function ActivityDetailPage({ params }: { params: { id: string } }) {
  const id = Number(params.id);
  const [detail, setDetail] = React.useState<ActivityDetail | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState(false);
  // Fetched in parallel with the detail payload; feeds the route map up top
  // and the charts further down from one request.
  const series = useActivitySeries(id);

  const load = React.useCallback(() => {
    api
      .activityDetail(id)
      .then((d) => {
        setDetail(d);
        setError(false);
      })
      .catch(() => setError(true))
      .finally(() => setLoading(false));
  }, [id]);

  React.useEffect(() => {
    load();
  }, [load]);

  const back = (
    <Link
      href="/activities"
      className="mb-4 inline-flex min-h-9 items-center gap-1.5 text-sm font-medium text-muted-foreground hover:text-foreground"
    >
      <ArrowLeft className="h-4 w-4" />
      Activities
    </Link>
  );

  if (loading) {
    return (
      <div>
        {back}
        <div className="space-y-5">
          <Skeleton className="h-16 rounded-2xl" />
          <Skeleton className="h-64 rounded-2xl" />
          <Skeleton className="h-40 rounded-2xl" />
        </div>
      </div>
    );
  }

  if (error || !detail) {
    return (
      <div>
        {back}
        <Card>
          <CardContent className="p-6 text-sm text-muted-foreground">
            Couldn&apos;t load this activity — is the backend running?
          </CardContent>
        </Card>
      </div>
    );
  }

  const stats: Array<{ label: string; value: string; sub?: string }> = [];
  if (detail.distance_km != null)
    stats.push({ label: "Distance", value: detail.distance_km.toFixed(1), sub: "km" });
  const dur = formatDuration(detail.duration_min);
  if (dur) stats.push({ label: "Duration", value: dur });
  if (detail.avg_pace) stats.push({ label: "Pace", value: detail.avg_pace, sub: "/km" });
  if (detail.avg_hr != null || detail.max_hr != null)
    stats.push({
      label: "HR avg / max",
      value: detail.avg_hr != null ? String(Math.round(detail.avg_hr)) : "–",
      sub: detail.max_hr != null ? `/ ${Math.round(detail.max_hr)} bpm` : "bpm",
    });
  if (detail.cadence != null)
    stats.push({ label: "Cadence", value: String(Math.round(detail.cadence)), sub: "spm" });
  if (detail.calories != null)
    stats.push({ label: "Calories", value: String(Math.round(detail.calories)), sub: "kcal" });
  if (detail.elevation_gain_m != null)
    stats.push({ label: "Elevation", value: String(Math.round(detail.elevation_gain_m)), sub: "m" });
  if (detail.temperature_c != null)
    stats.push({ label: "Temperature", value: detail.temperature_c.toFixed(1), sub: "°C" });
  if (detail.training_load != null)
    stats.push({ label: "Training load", value: String(Math.round(detail.training_load)) });
  if (detail.body_battery_change != null)
    stats.push({
      label: "Body Battery",
      value: `${detail.body_battery_change > 0 ? "+" : ""}${Math.round(detail.body_battery_change)}`,
    });

  return (
    <div>
      {back}

      <header className="mb-6 flex items-start justify-between gap-4">
        <div className="flex items-start gap-3">
          <ActivityTypeIcon type={detail.type} className="mt-0.5 h-10 w-10" />
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">{detail.name}</h1>
            <div className="mt-1.5 flex flex-wrap items-center gap-2">
              <p className="text-sm text-muted-foreground">{startTimeLabel(detail)}</p>
              <Badge variant="secondary">{prettyType(detail.type)}</Badge>
            </div>
          </div>
        </div>
        <ThemeToggle />
      </header>

      <div className="space-y-5">
        {/* Read order: where the run was (map), the numbers (stats), the
            interpretation (execution + coach's take), then the deep dive. */}
        <ActivityRouteSection data={series.data} loading={series.loading} />

        {stats.length > 0 && (
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-6">
            {stats.map((s, i) => (
              <StatTile
                key={s.label}
                label={s.label}
                value={s.value}
                sub={s.sub}
                className={statTileClass(i, stats.length)}
              />
            ))}
          </div>
        )}

        {detail.execution_score != null && (
          <Card>
            <CardHeader>
              <CardTitle>How you executed it</CardTitle>
              <CardDescription>
                How closely you held the planned targets, segment by segment.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <ExecutionScore activity={detail} />
            </CardContent>
          </Card>
        )}

        <ActivitySeriesSection data={series.data} loading={series.loading} error={series.error} />

        {detail.time_in_zones && (
          <Card>
            <CardHeader>
              <CardTitle>Time in zones</CardTitle>
            </CardHeader>
            <CardContent>
              <ZonesBar zones={detail.time_in_zones} />
            </CardContent>
          </Card>
        )}

        {(detail.ef != null || detail.hr_drift_pct != null) && (
          <Card>
            <CardHeader>
              <CardTitle>Efficiency</CardTitle>
            </CardHeader>
            <CardContent>
              {/* Single metric fills the row — no half-width dangling tile. */}
              <div
                className={cn(
                  "grid gap-2",
                  detail.ef != null && detail.hr_drift_pct != null
                    ? "grid-cols-2"
                    : "grid-cols-1",
                )}
              >
                {detail.ef != null && (
                  <div className="rounded-xl border border-border bg-background/50 px-3 py-2.5">
                    <p className="flex items-center gap-1 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
                      EF
                      <MetricInfo id="ef" />
                    </p>
                    <p className="mt-0.5 text-lg font-semibold tabular-nums">
                      {detail.ef.toFixed(3)}
                    </p>
                  </div>
                )}
                {detail.hr_drift_pct != null && (
                  <div className="rounded-xl border border-border bg-background/50 px-3 py-2.5">
                    <p className="flex items-center gap-1 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
                      HR drift
                      <MetricInfo id="hr_drift" />
                    </p>
                    <p className="mt-0.5 text-lg font-semibold tabular-nums">
                      {detail.hr_drift_pct.toFixed(1)}%
                    </p>
                  </div>
                )}
              </div>
            </CardContent>
          </Card>
        )}

        {/* Effort already logged on the watch (and not overridden in-app) — show
            it read-only; no need to ask the athlete to enter it again. */}
        {detail.rpe == null && detail.garmin_rpe != null ? (
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="flex items-center gap-0.5">
                Effort
                <MetricInfo id="rpe" />
              </CardTitle>
              <CardDescription>Logged on your watch</CardDescription>
            </CardHeader>
            <CardContent className="flex flex-wrap items-center gap-2">
              <Badge variant="secondary" className="tabular-nums">
                <Watch className="h-3 w-3" />
                RPE {detail.garmin_rpe}/10
              </Badge>
              {detail.feel != null && (
                <Badge variant="secondary">Felt {FEEL_LABELS[detail.feel] ?? "—"}</Badge>
              )}
            </CardContent>
          </Card>
        ) : (
          <Card>
            <CardHeader className="pb-2">
              <CardTitle>Effort</CardTitle>
              <CardDescription>
                {detail.rpe != null
                  ? `You rated this run ${detail.rpe}/10 — tap to change it.`
                  : "How hard did this run feel? 1 is easy, 10 is max effort."}
              </CardDescription>
            </CardHeader>
            <CardContent>
              <RpeScale
                activityId={detail.id}
                currentRpe={detail.rpe}
                currentNote={detail.rpe_note}
                onRated={load}
              />
            </CardContent>
          </Card>
        )}

        {detail.plan_day && (
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium">
                Planned: <span className="text-accent">{detail.plan_day.title}</span>
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-1.5">
              <Badge className={WORKOUT_BADGE_CLASSES[detail.plan_day.workout_type]}>
                {WORKOUT_LABELS[detail.plan_day.workout_type]}
              </Badge>
              <WorkoutMeta workout={detail.plan_day} />
              {detail.plan_day.description && (
                <p className="text-sm text-muted-foreground">{detail.plan_day.description}</p>
              )}
            </CardContent>
          </Card>
        )}

        <div>
          <Link
            href={`/chat?date=${detail.date}`}
            className={buttonVariants({ variant: "outline" })}
          >
            <MessageSquare className="h-4 w-4" />
            Ask about this run
          </Link>
        </div>
      </div>
    </div>
  );
}
