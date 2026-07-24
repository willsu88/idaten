"use client";

import * as React from "react";
import { Bike, Check, Footprints } from "lucide-react";
import type { DayIntent, PlanDay, WeekSummary } from "@/lib/types";
import { scoreChipTone } from "@/components/execution-score";
import { MetricInfo } from "@/components/metric-info";
import { cn, formatDay, formatDuration, formatWeekday } from "@/lib/utils";

/** "3 h 05 of 4 h 10 · 78% easy (Z1+Z2) ⓘ · 31.2 km run" — the week's load in
 * the plan's own time-at-intensity currency; km is an actuals-only footnote,
 * never a target (these plans are time-based). The easy share carries the
 * MetricInfo popover (the 80/20 explanation). Renders null when there is
 * nothing to say. `prefix` is the Week page's "3 / 5 done". */
export function WeekSummaryLine({
  summary,
  prefix,
  className,
}: {
  summary: WeekSummary | null;
  prefix?: string | null;
  className?: string;
}) {
  const parts: React.ReactNode[] = [];
  if (prefix) parts.push(prefix);
  if (summary) {
    const done = summary.done_min > 0 ? formatDuration(summary.done_min) : null;
    const planned = formatDuration(summary.planned_min);
    if (done && planned) parts.push(`${done} of ${planned}`);
    else if (planned) parts.push(`${planned} planned`);
    else if (done) parts.push(`${done} done`);
    if (summary.easy_pct != null) {
      parts.push(
        <span key="easy" className="inline-flex items-center whitespace-nowrap">
          {summary.easy_pct}% easy (Z1+Z2)
          <MetricInfo id="easy_pct" className="ml-0.5" />
        </span>,
      );
    }
    if (summary.run_km != null) parts.push(`${summary.run_km} km run`);
    if (summary.strength) {
      parts.push(`${summary.strength.done} of ${summary.strength.target} strength`);
    }
  }
  if (parts.length === 0) return null;
  return (
    <p className={cn("text-xs tabular-nums text-muted-foreground", className)}>
      {parts.map((p, i) => (
        <React.Fragment key={i}>
          {i > 0 && " · "}
          {p}
        </React.Fragment>
      ))}
    </p>
  );
}

/** One day in the overview strip. Content encodes state at a glance:
 * completed → its execution score (colored); planned run → a workout-colored
 * dot; other-sport → the emerald bike; rest/empty → a dim dash. Today is ringed
 * and dotted. Tapping fires `onJump` (Week: open + scroll to the card; Today:
 * navigate to that day on the Week page). */
function StripCell({
  date,
  day,
  hasIntent,
  isToday,
  onJump,
}: {
  date: string;
  day: PlanDay | undefined;
  hasIntent: boolean;
  isToday: boolean;
  onJump: (date: string) => void;
}) {
  const initial = formatWeekday(date).charAt(0); // M T W T F S S
  const isDone = day?.status === "completed";
  const isRest = !day || day.workout_type === "rest";

  let inner: React.ReactNode;
  let cellClass = "border-border/60 bg-muted/30 text-muted-foreground";
  if (isDone && day?.execution) {
    inner = day.execution.score;
    cellClass = scoreChipTone(day.execution.score);
  } else if (isDone) {
    inner = <Check className="h-4 w-4" strokeWidth={3} />;
    cellClass = "border-success/40 bg-success/15 text-success";
  } else if (hasIntent) {
    inner = <Bike className="h-4 w-4" />;
    cellClass = "border-emerald-500/40 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400";
  } else if (day && !isRest) {
    if (day.status === "skipped") {
      inner = <span className="text-xs">–</span>;
      cellClass = "border-border/50 bg-muted/30 text-muted-foreground/60 line-through";
    } else {
      // Upcoming run — a runner glyph (Garmin's shoe cue), plain cell.
      inner = <Footprints className="h-4 w-4" />;
      cellClass = "border-border bg-card text-muted-foreground";
    }
  } else {
    inner = <span className="text-xs opacity-40">–</span>;
  }

  return (
    <button
      type="button"
      onClick={() => onJump(date)}
      aria-label={`Jump to ${formatDay(date)}`}
      className="flex flex-col items-center gap-1"
    >
      <span
        className={cn(
          "flex h-9 w-full items-center justify-center rounded-lg border text-[13px] font-bold tabular-nums transition-colors",
          cellClass,
          isToday && "ring-2 ring-accent ring-offset-1 ring-offset-background",
        )}
      >
        {inner}
      </span>
      <span
        className={cn(
          "flex h-3 flex-col items-center text-[10px]",
          isToday ? "font-semibold text-accent" : "text-muted-foreground",
        )}
      >
        {initial}
        {isToday && <span className="mt-0.5 h-1 w-1 rounded-full bg-accent" />}
      </span>
    </button>
  );
}

/** The at-a-glance Mon-Sun strip — the Week page's quick-jump row, also reused
 * as compact week context on Today. */
export function WeekStrip({
  dates,
  days,
  intents,
  today,
  onJump,
}: {
  dates: string[];
  days: PlanDay[];
  intents: DayIntent[];
  today: string;
  onJump: (date: string) => void;
}) {
  const byDate = new Map(days.map((d) => [d.date, d]));
  return (
    <div className="grid grid-cols-7 gap-1.5">
      {dates.map((date) => (
        <StripCell
          key={date}
          date={date}
          day={byDate.get(date)}
          hasIntent={intents.some((i) => i.date === date)}
          isToday={date === today}
          onJump={onJump}
        />
      ))}
    </div>
  );
}
