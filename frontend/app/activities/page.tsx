"use client";

import * as React from "react";
import Link from "next/link";
import { ChevronDown, ChevronLeft, ChevronRight } from "lucide-react";
import type { Activity, ActivityMonthCount, ActivityTypeCount } from "@/lib/types";
import { api, safe } from "@/lib/api";
import { cn } from "@/lib/utils";
import { ActivityTypeIcon } from "@/components/activity-icon";
import { ScoreRing } from "@/components/execution-score";
import { CoachHint } from "@/components/coach-hint";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { DropdownItem, DropdownMenu } from "@/components/ui/dropdown-menu";
import { Skeleton } from "@/components/ui/skeleton";
import { APP_LOCALE, formatDay, formatDuration, prettyType } from "@/lib/utils";

/** "July 2026" for a "YYYY-MM" month key. */
function monthLabel(month: string): string {
  return new Date(`${month}-01T00:00:00`).toLocaleDateString(APP_LOCALE, {
    month: "long",
    year: "numeric",
  });
}

/** This month as a "YYYY-MM" key. */
function currentMonth(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

function TypeChip({
  label,
  count,
  active,
  onClick,
}: {
  label: string;
  count?: number;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "inline-flex min-h-8 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full border px-3 py-1 text-xs font-medium transition-colors",
        active
          ? "border-accent bg-accent/15 text-accent"
          : "border-border bg-card text-muted-foreground hover:border-accent/50 hover:text-foreground",
      )}
    >
      {label}
      {count != null && <span className="tabular-nums opacity-70">{count}</span>}
    </button>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <span className="whitespace-nowrap text-xs tabular-nums text-muted-foreground">
      <span className="font-semibold text-foreground">{value}</span> {label}
    </span>
  );
}

function ActivityRow({ activity }: { activity: Activity }) {
  const stats: Array<{ label: string; value: string }> = [];
  if (activity.distance_km != null)
    stats.push({ label: "km", value: activity.distance_km.toFixed(1) });
  const dur = formatDuration(activity.duration_min);
  if (dur) stats.push({ label: "", value: dur });
  if (activity.avg_pace) stats.push({ label: "/km", value: activity.avg_pace });
  if (activity.avg_hr != null)
    stats.push({ label: "bpm", value: String(Math.round(activity.avg_hr)) });

  return (
    <Link
      href={`/activities/${activity.id}`}
      className="flex min-h-11 items-center gap-3 rounded-xl border border-border bg-card px-4 py-3 transition-colors hover:border-accent/50"
    >
      <ActivityTypeIcon type={activity.type} />
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-semibold">{activity.name}</p>
        <p className="mt-0.5 text-xs text-muted-foreground">{formatDay(activity.date)}</p>
        <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1">
          {stats.map((s, i) => (
            <Stat key={i} label={s.label} value={s.value} />
          ))}
        </div>
      </div>
      {/* Scored runs get the same medallion as the Week page — one glyph, no
          badge clutter. RPE lives on the detail page only. */}
      {activity.execution_score != null && (
        <span className="shrink-0" aria-label={`Execution score ${activity.execution_score}`}>
          <ScoreRing score={activity.execution_score} size="sm" check />
        </span>
      )}
      <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />
    </Link>
  );
}

export default function ActivitiesPage() {
  const [activities, setActivities] = React.useState<Activity[]>([]);
  const [types, setTypes] = React.useState<ActivityTypeCount[]>([]);
  const [months, setMonths] = React.useState<ActivityMonthCount[]>([]);
  const [selectedType, setSelectedType] = React.useState<string | null>(null);
  // The viewed month ("YYYY-MM"); null until the months index loads.
  const [month, setMonth] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState(false);

  React.useEffect(() => {
    safe(api.activityTypes()).then((rows) => setTypes(rows ?? []));
    // Land on the newest month that has data (usually this month).
    api
      .activityMonths()
      .then((rows) => {
        setMonths(rows);
        setMonth(rows[0]?.month ?? currentMonth());
      })
      .catch(() => {
        setError(true);
        setLoading(false);
      });
  }, []);

  React.useEffect(() => {
    if (!month) return;
    setLoading(true);
    setError(false);
    api
      // A month is bounded, so one fetch covers it (backend caps at 100).
      .activities(100, 0, selectedType ?? undefined, undefined, month)
      .then(setActivities)
      .catch(() => setError(true))
      .finally(() => setLoading(false));
  }, [selectedType, month]);

  // Arrows step through months that HAVE data — an empty page is never shown.
  const monthIdx = months.findIndex((m) => m.month === month);
  const olderMonth = monthIdx >= 0 ? months[monthIdx + 1]?.month : undefined;
  const newerMonth = monthIdx > 0 ? months[monthIdx - 1]?.month : undefined;

  return (
    <div>
      <PageHeader title="Activities" subtitle="Every synced activity, newest first" />

      <CoachHint page="activities" />

      {/* Month navigator: arrows step through months with data; the label is a
          picker (scrollable, with counts) for jumping straight to e.g. 2025. */}
      {month && months.length > 0 && (
        <div className="mb-4 flex items-center justify-center gap-2 sm:justify-start">
          <Button
            variant="outline"
            size="icon-sm"
            onClick={() => olderMonth && setMonth(olderMonth)}
            disabled={!olderMonth}
            aria-label="Older month"
          >
            <ChevronLeft className="h-4 w-4" />
          </Button>
          <DropdownMenu
            align="start"
            trigger={
              <Button variant="ghost" size="sm" className="font-medium">
                {monthLabel(month)}
                <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
              </Button>
            }
          >
            <div className="max-h-72 overflow-y-auto">
              {months.map((m) => (
                <DropdownItem key={m.month} onClick={() => setMonth(m.month)}>
                  <span className={cn("flex-1", m.month === month && "font-semibold")}>
                    {monthLabel(m.month)}
                  </span>
                  <span className="tabular-nums text-muted-foreground">{m.count}</span>
                </DropdownItem>
              ))}
            </div>
          </DropdownMenu>
          <Button
            variant="outline"
            size="icon-sm"
            onClick={() => newerMonth && setMonth(newerMonth)}
            disabled={!newerMonth}
            aria-label="Newer month"
          >
            <ChevronRight className="h-4 w-4" />
          </Button>
        </div>
      )}

      {types.length > 0 && (
        <div className="-mx-1 mb-4 flex gap-2 overflow-x-auto px-1 pb-1">
          <TypeChip label="All" active={selectedType === null} onClick={() => setSelectedType(null)} />
          {types.map((t) => (
            <TypeChip
              key={t.type}
              label={prettyType(t.type)}
              count={t.count}
              active={selectedType === t.type}
              onClick={() => setSelectedType(t.type)}
            />
          ))}
        </div>
      )}

      {loading ? (
        <div className="space-y-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-20 rounded-xl" />
          ))}
        </div>
      ) : error ? (
        <Card>
          <CardContent className="p-6 text-sm text-muted-foreground">
            Couldn&apos;t load activities — is the backend running?
          </CardContent>
        </Card>
      ) : activities.length === 0 ? (
        <Card>
          <CardContent className="p-6 text-sm text-muted-foreground">
            {months.length === 0
              ? "No activities yet — run a sync to pull your Garmin history."
              : selectedType && month
                ? `No ${prettyType(selectedType).toLowerCase()} activities in ${monthLabel(month)}.`
                : month
                  ? `No activities in ${monthLabel(month)}.`
                  : "No activities match this filter."}
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-3">
          {activities.map((a) => (
            <ActivityRow key={a.id} activity={a} />
          ))}
        </div>
      )}
    </div>
  );
}
