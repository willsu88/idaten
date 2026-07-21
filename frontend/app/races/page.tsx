"use client";

import * as React from "react";
import type { Analytics, Race } from "@/lib/types";
import { api, safe } from "@/lib/api";
import { cn } from "@/lib/utils";
import { CoachHint } from "@/components/coach-hint";
import { PageHeader } from "@/components/page-header";
import { RacesCard } from "@/components/races-card";
import { RaceOutlookCard, RacePredictionTrendChart } from "@/components/analytics-charts";
import { TrainingPhasesCard, usePlanInfo } from "@/components/training-phases-card";
import { useChartTheme } from "@/components/charts";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

// Prediction history windows. Beyond ~90 days the trend is dominated by stale,
// flat values, so we cap there. Fetch a bit more than the max so 90D is full.
const PRED_RANGES = [7, 30, 90] as const;
const DEFAULT_PRED_RANGE = 90;

export default function RacesPage() {
  const [races, setRaces] = React.useState<Race[]>([]);
  const [analytics, setAnalytics] = React.useState<Analytics | null>(null);
  const [predRange, setPredRange] = React.useState<number>(DEFAULT_PRED_RANGE);
  const plan = usePlanInfo();
  const colors = useChartTheme();

  const loadOutlook = React.useCallback(() => {
    api
      .races()
      .then(setRaces)
      .catch(() => setRaces([]));
    safe(api.analytics(Math.max(...PRED_RANGES))).then(setAnalytics);
  }, []);

  React.useEffect(() => {
    loadOutlook();
  }, [loadOutlook]);

  const predictionSeries = React.useMemo(() => {
    const all = analytics?.race_prediction_series ?? [];
    const cutoff = new Date();
    cutoff.setDate(cutoff.getDate() - predRange);
    const cutoffISO = cutoff.toISOString().slice(0, 10);
    return all.filter((p) => p.date >= cutoffISO);
  }, [analytics, predRange]);

  return (
    <div>
      <PageHeader
        title="Races"
        subtitle="Your goal races and how your predicted times stack up"
      />
      <CoachHint page="races" />
      <div className="space-y-5">
        {plan && <TrainingPhasesCard plan={plan} />}
        <RacesCard onMutated={loadOutlook} />
        {races.length > 0 && <RaceOutlookCard races={races} />}
        {(analytics?.race_prediction_series?.length ?? 0) >= 2 && (
          <Card>
            <CardHeader className="flex-row items-start justify-between gap-3 space-y-0">
              <div className="space-y-1.5">
                <CardTitle>Predicted finish</CardTitle>
                <CardDescription>
                  Garmin&apos;s predicted time for your primary race, trending toward your goal
                </CardDescription>
              </div>
              <div className="flex shrink-0 gap-1">
                {PRED_RANGES.map((d) => (
                  <button
                    key={d}
                    type="button"
                    onClick={() => setPredRange(d)}
                    className={cn(
                      "rounded-full border px-3 py-1 text-xs font-medium transition-colors",
                      predRange === d
                        ? "border-transparent bg-foreground text-background"
                        : "border-border text-muted-foreground hover:bg-muted hover:text-foreground",
                    )}
                  >
                    {d}D
                  </button>
                ))}
              </div>
            </CardHeader>
            <CardContent>
              <div className="h-52 w-full sm:h-64">
                {predictionSeries.length >= 2 ? (
                  <RacePredictionTrendChart
                    series={predictionSeries}
                    goalS={analytics?.goal?.goal_time_s ?? null}
                    colors={colors}
                  />
                ) : (
                  <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
                    Not enough data in this window.
                  </div>
                )}
              </div>
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}
