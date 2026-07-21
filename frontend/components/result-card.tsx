"use client";

import * as React from "react";
import Link from "next/link";
import { ChevronRight } from "lucide-react";
import type { Activity, GearSuggestion } from "@/lib/types";
import { api, safe } from "@/lib/api";
import { GearSuggestionBanner } from "@/components/gear-shoe-card";
import { Card, CardContent } from "@/components/ui/card";
import { ScoreBadge } from "@/components/execution-score";
import { CoachNote } from "@/components/coach-note";
import { personaForStyle } from "@/components/coach-provider";
import { ActivityTypeIcon } from "@/components/activity-icon";

/**
 * Today's result card: after a plan-attributed run is scored, this replaces the
 * plan card. It shows the score at a glance and lazily generates the LLM analysis
 * on mount (once) — the score paints instantly; the narrative streams in a beat
 * later. Tapping opens the full breakdown on the activity detail page.
 */
export function ResultCard({ activity }: { activity: Activity }) {
  const [analysis, setAnalysis] = React.useState<string | null>(activity.execution_analysis);
  const [coach, setCoach] = React.useState<string | null>(activity.execution_analysis_coach);
  const [pending, setPending] = React.useState(false);
  // Shoe-mistag catch at the moment it matters: this run just synced and the
  // athlete is already here. Same suggestion state as /gear and the detail
  // page — acting on it in any surface clears it everywhere.
  const [gearSuggestion, setGearSuggestion] = React.useState<GearSuggestion | null>(null);

  React.useEffect(() => {
    safe(api.gearSuggestions()).then((all) =>
      setGearSuggestion(all?.find((s) => s.activity_id === activity.id) ?? null),
    );
  }, [activity.id]);

  // Lazy, once: the Today load is the ONLY trigger for the analysis LLM call.
  React.useEffect(() => {
    if (activity.execution_score == null || analysis) return;
    let alive = true;
    setPending(true);
    safe(api.activityAnalysis(activity.id)).then((res) => {
      if (alive && res) {
        setAnalysis(res.analysis);
        setCoach(res.coach);
      }
      if (alive) setPending(false);
    });
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activity.id]);

  const meta: string[] = [];
  if (activity.distance_km != null) meta.push(`${activity.distance_km.toFixed(1)} km`);
  if (activity.duration_min != null) meta.push(`${Math.round(activity.duration_min)} min`);
  if (activity.avg_pace) meta.push(`${activity.avg_pace} /km`);

  return (
    <Card>
      <CardContent className="pt-5">
        <Link href={`/activities/${activity.id}`} className="group flex items-start gap-3">
          <ActivityTypeIcon type={activity.type} className="mt-0.5 h-9 w-9 shrink-0" />
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-1.5">
              <p className="truncate text-sm font-semibold group-hover:text-accent">
                {activity.name}
              </p>
              <span className="rounded-full bg-success/15 px-1.5 py-0.5 text-[10px] font-medium text-success">
                done
              </span>
            </div>
            {meta.length > 0 && (
              <p className="mt-0.5 text-xs text-muted-foreground">{meta.join(" · ")}</p>
            )}
          </div>
          <ChevronRight className="mt-1 h-4 w-4 shrink-0 text-muted-foreground group-hover:text-accent" />
        </Link>

        {gearSuggestion && (
          <div className="mt-4">
            <GearSuggestionBanner
              suggestion={gearSuggestion}
              compact
              onDone={() => setGearSuggestion(null)}
            />
          </div>
        )}

        {activity.execution_score != null && (
          <div className="mt-4 border-t border-border pt-4">
            <ScoreBadge score={activity.execution_score} source={activity.execution_score_source} />
            {analysis ? (
              <div className="mt-3">
                <CoachNote
                  note={analysis}
                  persona={coach ? personaForStyle(coach) : undefined}
                  feedback={{
                    surface: "execution_analysis",
                    ref: String(activity.id),
                    state: activity.analysis_feedback ?? null,
                  }}
                />
              </div>
            ) : pending ? (
              <p className="mt-3 text-sm italic text-muted-foreground">
                Coach is reviewing how you executed it…
              </p>
            ) : null}
            <Link
              href={`/activities/${activity.id}`}
              className="mt-2 inline-block text-xs font-medium text-accent hover:underline"
            >
              See the breakdown →
            </Link>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
