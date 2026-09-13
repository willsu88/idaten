"use client";

import * as React from "react";
import { Link2 } from "lucide-react";
import type { PlanDay } from "@/lib/types";
import { api, ApiError, safe } from "@/lib/api";
import { WORKOUT_BADGE_CLASSES, WORKOUT_LABELS, isSelfPacedDay } from "@/lib/workout";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useToast } from "@/components/ui/toast";
import { formatDay } from "@/lib/utils";

/**
 * Manual run-to-plan link (ADR 0026), on a run's detail page when the run
 * isn't linked: the automatic match is exact-date, so a workout run a day
 * early/late - or a mis-tapped "just a run" - lands here. Candidates are the
 * athlete's own plan days within ±3 days, non-rest, not already completed.
 */
export function LinkWorkoutCard({
  activityId,
  onLinked,
}: {
  activityId: number;
  onLinked: () => void;
}) {
  const [candidates, setCandidates] = React.useState<PlanDay[]>([]);
  const [busy, setBusy] = React.useState<string | null>(null);
  const { toast } = useToast();

  React.useEffect(() => {
    safe(api.linkCandidates(activityId)).then((r) => {
      setCandidates(r && !r.linked ? r.candidates : []);
    });
  }, [activityId]);

  if (candidates.length === 0) return null;

  const link = async (day: PlanDay) => {
    setBusy(day.date);
    try {
      const res = await api.linkActivity(activityId, day.date);
      toast(
        res.execution_score != null
          ? `Linked - scored ${res.execution_score}`
          : "Linked - workout completed",
      );
      onLinked();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Linking failed", "error");
      setBusy(null);
    }
  };

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-sm font-medium">
          <Link2 className="h-4 w-4 text-muted-foreground" />
          Link to a planned workout
        </CardTitle>
        <CardDescription>
          This run isn&apos;t counted toward your plan. If it was one of these
          workouts, link it - it&apos;ll be scored against that day&apos;s targets
          and the day marked done.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        {candidates.map((day) => (
          <div
            key={day.date}
            className="flex items-center gap-3 rounded-xl border border-border bg-background/50 p-3"
          >
            <div className="min-w-0 flex-1">
              <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
                {formatDay(day.date)}
              </p>
              <div className="mt-0.5 flex flex-wrap items-center gap-1.5">
                <Badge className={WORKOUT_BADGE_CLASSES[day.workout_type]}>
                  {WORKOUT_LABELS[day.workout_type]}
                </Badge>
                <span className="truncate text-sm font-medium">{day.title}</span>
              </div>
              {isSelfPacedDay(day) && (
                <p className="mt-0.5 text-xs text-muted-foreground">
                  Self-paced - completes the day, no score.
                </p>
              )}
            </div>
            <Button
              size="sm"
              variant="outline"
              onClick={() => link(day)}
              disabled={busy !== null}
            >
              {busy === day.date ? "Linking…" : "Link"}
            </Button>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
