"use client";

import * as React from "react";
import type { CycleCalendarDay } from "@/lib/types";
import { api } from "@/lib/api";
import { APP_LOCALE, cn } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";

const WEEKDAYS = ["S", "M", "T", "W", "T", "F", "S"];

// Only the actionable phases get a tint; luteal/follicular stay neutral so the
// period (rose) and the pre-period ease window (amber) read at a glance.
const CELL: Record<string, string> = {
  menstrual: "bg-rose-500/25 text-rose-700 dark:text-rose-300 font-medium",
  premenstrual: "bg-amber-500/20 text-amber-700 dark:text-amber-300",
};

function parse(iso: string): Date {
  return new Date(iso + "T12:00:00"); // noon avoids DST/TZ edge cases
}

interface Month {
  key: string;
  label: string;
  lead: number; // blank cells before day 1
  days: CycleCalendarDay[];
}

function groupByMonth(days: CycleCalendarDay[]): Month[] {
  const months: Month[] = [];
  let cur: Month | null = null;
  for (const d of days) {
    const dt = parse(d.date);
    const key = `${dt.getFullYear()}-${dt.getMonth()}`;
    if (!cur || cur.key !== key) {
      cur = {
        key,
        label: dt.toLocaleDateString(APP_LOCALE, { month: "long", year: "numeric" }),
        // blanks before day 1 = weekday of the 1st (calendar is contiguous from the 1st)
        lead: new Date(dt.getFullYear(), dt.getMonth(), 1).getDay(),
        days: [],
      };
      months.push(cur);
    }
    cur.days.push(d);
  }
  return months;
}

/** Read-only 3-month projection: eyeball the predicted periods. */
export function CycleMonthStrip({ refreshKey = 0 }: { refreshKey?: number }) {
  const [days, setDays] = React.useState<CycleCalendarDay[] | null>(null);
  const [error, setError] = React.useState(false);
  const todayIso = React.useMemo(() => {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(
      d.getDate(),
    ).padStart(2, "0")}`;
  }, []);

  React.useEffect(() => {
    let live = true;
    setDays(null);
    setError(false);
    api
      .cycleCalendar(3)
      .then((r) => live && setDays(r.days))
      .catch(() => live && setError(true));
    return () => {
      live = false;
    };
  }, [refreshKey]);

  if (error) {
    return <p className="text-sm text-muted-foreground">Couldn&apos;t load the calendar.</p>;
  }
  if (!days) return <Skeleton className="h-56 rounded-xl" />;

  const months = groupByMonth(days);

  return (
    <div className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {months.map((m) => (
          <div key={m.key}>
            <p className="mb-1.5 text-xs font-medium text-muted-foreground">{m.label}</p>
            <div className="grid grid-cols-7 gap-0.5 text-center text-[10px] text-muted-foreground">
              {WEEKDAYS.map((w, i) => (
                <div key={i} className="py-0.5">
                  {w}
                </div>
              ))}
              {Array.from({ length: m.lead }).map((_, i) => (
                <div key={`lead-${i}`} />
              ))}
              {m.days.map((d) => {
                const isToday = d.date === todayIso;
                return (
                  <div
                    key={d.date}
                    className={cn(
                      "flex h-6 items-center justify-center rounded text-xs tabular-nums",
                      d.phase && CELL[d.phase],
                      isToday && "ring-1 ring-accent ring-offset-1 ring-offset-background",
                    )}
                  >
                    {parse(d.date).getDate()}
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>
      <div className="flex flex-wrap gap-4 text-xs text-muted-foreground">
        <span className="inline-flex items-center gap-1.5">
          <span className="h-3 w-3 rounded bg-rose-500/25" /> Period
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="h-3 w-3 rounded bg-amber-500/20" /> Premenstrual
        </span>
      </div>
    </div>
  );
}
