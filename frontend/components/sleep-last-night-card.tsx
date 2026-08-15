"use client";

import Link from "next/link";
import { ChevronRight, Moon } from "lucide-react";
import type { SleepNight } from "@/lib/types";
import { STAGE_LABELS, fmtDuration, stageShares } from "@/lib/sleep";
import { useChartTheme } from "@/components/charts";
import { Card, CardContent } from "@/components/ui/card";
import { APP_LOCALE, cn } from "@/lib/utils";

const QUALIFIER_CLASSES: Record<string, string> = {
  EXCELLENT: "text-success",
  GOOD: "text-success",
  FAIR: "text-warning",
  POOR: "text-danger",
};

/** Compact "last night" strip for Today: duration, score, a proportional stage
 * bar, and need/naps context. Renders nothing until the morning sync has
 * archived the night (same gate as the coach note). */
export function SleepLastNightCard({ night }: { night: SleepNight | null }) {
  const colors = useChartTheme();
  if (!night?.available || !night.stages) return null;

  const shares = stageShares(night.stages);
  const totalS = shares.reduce((s, x) => s + x.seconds, 0);
  const asleepS = totalS - (night.stages.awake_s ?? 0);
  if (totalS <= 0) return null;
  const stageColor = { deep: colors.indigo, light: colors.blue, rem: colors.teal, awake: colors.amber };

  const needS = night.need?.actual_min != null ? night.need.actual_min * 60 : null;
  const needPct = needS ? Math.min(Math.round((asleepS / needS) * 100), 100) : null;
  const napCount = night.naps?.length ?? 0;
  const qualifier = night.score?.qualifier ?? null;

  return (
    <Card>
      <CardContent className="p-4">
        <Link href="/sleep" className="group block">
          <div className="flex items-center justify-between">
            <p className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
              <Moon className="h-3.5 w-3.5" />
              Last night
            </p>
            <ChevronRight className="h-4 w-4 text-muted-foreground transition-transform group-hover:translate-x-0.5" />
          </div>
          <div className="mt-1.5 flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <span className="text-lg font-semibold tabular-nums">{fmtDuration(asleepS)}</span>
            {night.score?.overall != null && (
              <span className="text-sm text-muted-foreground">
                score{" "}
                <span className={cn("font-semibold", qualifier ? QUALIFIER_CLASSES[qualifier] : "text-foreground")}>
                  {night.score.overall}
                </span>
              </span>
            )}
            {night.bedtime_ms != null && night.wake_ms != null && (
              <span className="text-xs text-muted-foreground tabular-nums">
                {new Date(night.bedtime_ms).toLocaleTimeString(APP_LOCALE, { hour: "numeric", minute: "2-digit" })}
                {" – "}
                {new Date(night.wake_ms).toLocaleTimeString(APP_LOCALE, { hour: "numeric", minute: "2-digit" })}
              </span>
            )}
          </div>
          <div className="mt-2 flex h-2 w-full gap-px overflow-hidden rounded-full">
            {shares.filter((s) => s.seconds > 0).map((s) => (
              <div
                key={s.key}
                title={`${STAGE_LABELS[s.key]} ${fmtDuration(s.seconds)}`}
                style={{ width: `${(s.seconds / totalS) * 100}%`, background: stageColor[s.key] }}
              />
            ))}
          </div>
          <p className="mt-1.5 text-xs text-muted-foreground">
            {[
              needPct != null && `${needPct}% of your ${fmtDuration(needS)} need`,
              napCount > 0 && `${napCount} ${napCount === 1 ? "nap" : "naps"}`,
            ]
              .filter(Boolean)
              .join(" · ")}
          </p>
        </Link>
      </CardContent>
    </Card>
  );
}
