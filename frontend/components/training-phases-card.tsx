"use client";

// Training-phase progress: a proportional timeline of Base/Build/Peak/Taper
// with a "today" marker and the current plan week. Data comes from the
// mirrored Garmin Coach plan when one exists (its week numbering is ground
// truth), otherwise a timeline derived from the primary race date.

import * as React from "react";
import type { TrainingPhase, TrainingPlanInfo } from "@/lib/types";
import { api, safe } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { cn, formatDay } from "@/lib/utils";

const PHASE_BAR: Record<TrainingPhase, string> = {
  base: "bg-sky-500",
  build: "bg-orange-500",
  peak: "bg-rose-500",
  taper: "bg-teal-500",
  race: "bg-amber-500",
};

const PHASE_TEXT: Record<TrainingPhase, string> = {
  base: "text-sky-600 dark:text-sky-400",
  build: "text-orange-600 dark:text-orange-400",
  peak: "text-rose-600 dark:text-rose-400",
  taper: "text-teal-600 dark:text-teal-400",
  race: "text-amber-600 dark:text-amber-400",
};

const DAY_MS = 24 * 60 * 60 * 1000;

function daysBetween(a: string, b: string): number {
  return Math.round((new Date(b).getTime() - new Date(a).getTime()) / DAY_MS);
}

export function usePlanInfo(): TrainingPlanInfo | null {
  const [plan, setPlan] = React.useState<TrainingPlanInfo | null>(null);
  React.useEffect(() => {
    safe(api.trainingPlan()).then(setPlan);
  }, []);
  return plan;
}

/** "Base · Week 8 of 25" — compact chip for page headers (Week page). */
export function PhaseChip({ plan }: { plan: TrainingPlanInfo | null }) {
  if (!plan || !plan.phase) return null;
  const label = plan.phases.find((p) => p.phase === plan.phase)?.label ?? plan.phase;
  return (
    <Badge className={cn("bg-muted", PHASE_TEXT[plan.phase])}>
      {label}
      {plan.current_week != null && plan.total_weeks != null && (
        <span className="ml-1 font-normal text-muted-foreground">
          · Week {plan.current_week} of {plan.total_weeks}
        </span>
      )}
    </Badge>
  );
}

export function TrainingPhasesCard({ plan }: { plan: TrainingPlanInfo }) {
  const totalDays = Math.max(1, daysBetween(plan.start_date, plan.end_date) + 1);
  const today = new Date().toISOString().slice(0, 10);
  const elapsed = Math.min(Math.max(daysBetween(plan.start_date, today), 0), totalDays);
  const inPlan = today >= plan.start_date && today <= plan.end_date;

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <CardTitle>Training phases</CardTitle>
            <CardDescription>{plan.name}</CardDescription>
          </div>
          <div className="flex items-center gap-2">
            {plan.current_week != null && plan.total_weeks != null && (
              <span className="text-sm font-medium tabular-nums">
                Week {plan.current_week} of {plan.total_weeks}
              </span>
            )}
            <Badge variant="secondary">
              {plan.source === "garmin" ? "from Garmin Coach" : "estimated from race date"}
            </Badge>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        {/* Proportional phase bar with a today marker. */}
        <div className="relative">
          <div className="flex h-3 w-full overflow-hidden rounded-full">
            {plan.phases.map((p) => {
              const days = Math.max(1, daysBetween(p.start_date, p.end_date) + 1);
              return (
                <div
                  key={p.phase}
                  className={cn(PHASE_BAR[p.phase], "h-full", p.phase !== plan.phase && "opacity-45")}
                  style={{ width: `${(days / totalDays) * 100}%` }}
                  title={`${p.label}: ${formatDay(p.start_date)} – ${formatDay(p.end_date)}`}
                />
              );
            })}
          </div>
          {inPlan && (
            <div
              className="absolute -top-1 h-5 w-0.5 rounded-full bg-foreground"
              style={{ left: `${(elapsed / totalDays) * 100}%` }}
              aria-label="Today"
            />
          )}
        </div>
        <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1.5">
          {plan.phases.map((p) => (
            <div key={p.phase} className="flex items-center gap-1.5 text-xs">
              <span className={cn("h-2 w-2 rounded-full", PHASE_BAR[p.phase])} />
              <span className={cn("font-medium", p.phase === plan.phase && PHASE_TEXT[p.phase])}>
                {p.label}
                {p.phase === plan.phase && " (now)"}
              </span>
              <span className="tabular-nums text-muted-foreground">
                {formatDay(p.start_date)} – {formatDay(p.end_date)}
              </span>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
