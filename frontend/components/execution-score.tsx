"use client";

import * as React from "react";
import { Check } from "lucide-react";
import type { Activity, ExecutionSegment } from "@/lib/types";
import { CoachNote } from "@/components/coach-note";
import { personaForStyle } from "@/components/coach-provider";
import { cn } from "@/lib/utils";

function scoreTone(score: number): string {
  if (score >= 80) return "text-success";
  if (score >= 50) return "text-warning";
  return "text-danger";
}

function scoreRingTone(score: number): string {
  if (score >= 80) return "border-success/50 bg-success/10";
  if (score >= 50) return "border-warning/50 bg-warning/10";
  return "border-danger/50 bg-danger/10";
}

/** Compact chip coloring for a score shown inline in lists/strips. */
export function scoreChipTone(score: number): string {
  if (score >= 80) return "border-success/40 bg-success/15 text-success";
  if (score >= 50) return "border-warning/40 bg-warning/15 text-warning";
  return "border-danger/40 bg-danger/15 text-danger";
}

/** m/s → "M:SS" min/km (for pace-target segments). */
function paceStr(mps: number): string {
  if (!mps) return "—";
  const s = 1000 / mps;
  return `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, "0")}`;
}

function fmtTarget(seg: ExecutionSegment): string {
  const [lo, hi] = seg.target;
  return seg.axis === "hr"
    ? `${Math.round(lo)}–${Math.round(hi)} bpm`
    : `${paceStr(hi)}–${paceStr(lo)} /km`; // higher speed = faster pace
}

function fmtActual(seg: ExecutionSegment): string {
  if (seg.avg_actual == null) return "—";
  return seg.axis === "hr" ? `${Math.round(seg.avg_actual)} bpm` : `${paceStr(seg.avg_actual)} /km`;
}

const RING_SIZE = {
  sm: "h-9 w-9 text-[13px]",
  md: "h-12 w-12 text-lg",
  lg: "h-16 w-16 text-2xl",
} as const;

/** The score in a colored ring (green/amber/red). `check` overlays a small
 * "done" tick — the completed-day medallion on the Week page. */
export function ScoreRing({
  score,
  size = "md",
  check = false,
}: {
  score: number;
  size?: keyof typeof RING_SIZE;
  check?: boolean;
}) {
  return (
    <span className="relative inline-flex shrink-0">
      <span
        className={cn(
          "flex items-center justify-center rounded-full border-2 font-bold tabular-nums",
          scoreRingTone(score),
          scoreTone(score),
          RING_SIZE[size],
        )}
      >
        {score}
      </span>
      {check && (
        <span className="absolute -bottom-0.5 -right-0.5 flex h-4 w-4 items-center justify-center rounded-full border border-card bg-success text-white">
          <Check className="h-2.5 w-2.5" strokeWidth={3} />
        </span>
      )}
    </span>
  );
}

/** The score ring with its source label ("scored by your watch"/"by Idaten"). */
export function ScoreBadge({
  score,
  source,
  size = "md",
}: {
  score: number;
  source: "garmin" | "idaten" | null;
  size?: "md" | "lg";
}) {
  return (
    <div className="flex items-center gap-2.5">
      <ScoreRing score={score} size={size} />
      <div className="text-xs text-muted-foreground">
        <div className="font-medium text-foreground">Execution</div>
        <div>{source === "garmin" ? "scored by your watch" : "scored by Idaten"}</div>
      </div>
    </div>
  );
}

/** Per-segment "receipts": target vs actual, one row per prescribed step. */
export function ExecutionBreakdown({ segments }: { segments: ExecutionSegment[] }) {
  return (
    <div className="space-y-1.5">
      {segments.map((seg, i) => (
        <div key={i} className="flex items-center gap-3 text-xs">
          <span className="w-20 shrink-0 truncate capitalize text-muted-foreground">
            {(seg.label ?? "segment").toLowerCase()}
          </span>
          <span className="flex-1 tabular-nums text-muted-foreground">
            <span className="text-foreground">{fmtActual(seg)}</span>
            <span className="mx-1 opacity-50">vs</span>
            {fmtTarget(seg)}
          </span>
          {seg.score != null && (
            <span className={cn("w-8 shrink-0 text-right font-semibold tabular-nums", scoreTone(seg.score))}>
              {seg.score}
            </span>
          )}
        </div>
      ))}
    </div>
  );
}

/** Full block: score + breakdown + (optional) analysis narrative. Renders
 * nothing if the run has no execution score. */
export function ExecutionScore({
  activity,
  analysis,
  analysisPending = false,
}: {
  activity: Activity;
  analysis?: string | null;
  analysisPending?: boolean;
}) {
  if (activity.execution_score == null) return null;
  const text = analysis ?? activity.execution_analysis;

  return (
    <div className="space-y-3">
      <ScoreBadge score={activity.execution_score} source={activity.execution_score_source} size="lg" />
      {text ? (
        // The score is scored by the watch/Idaten, but the ANALYSIS is the coach's
        // voice — attributed to the persona that actually wrote it. A missing stamp
        // falls through to the current coach (never a hard default to Sam).
        <CoachNote
          note={text}
          persona={
            activity.execution_analysis_coach
              ? personaForStyle(activity.execution_analysis_coach)
              : undefined
          }
          feedback={{
            surface: "execution_analysis",
            ref: String(activity.id),
            state: activity.analysis_feedback ?? null,
          }}
        />
      ) : analysisPending ? (
        <p className="text-sm italic text-muted-foreground">Coach is reviewing how you executed it…</p>
      ) : null}
      {activity.execution_breakdown && activity.execution_breakdown.length > 0 && (
        <ExecutionBreakdown segments={activity.execution_breakdown} />
      )}
    </div>
  );
}
