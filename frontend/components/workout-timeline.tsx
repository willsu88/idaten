import type { StepBlock, StepKind } from "@/lib/types";
import { formatDuration } from "@/lib/utils";
import { STEP_KIND_LABELS, workoutBreakdown } from "@/lib/workout";
import { cn } from "@/lib/utils";

/** Bar fill per step kind — matches the WorkoutSteps dot palette. */
const STEP_FILL_CLASSES: Record<StepKind, string> = {
  warmup: "bg-sky-500",
  work: "bg-rose-500",
  recovery: "bg-teal-500",
  cooldown: "bg-indigo-500",
  rest: "bg-muted-foreground/30",
};

function roundMin(min: number): string {
  return formatDuration(Math.round(min)) ?? `${Math.round(min)} min`;
}

/**
 * Effort-profile timeline for a structured workout: a horizontal proportional
 * bar (one segment per step, repeats expanded, width ∝ derived time, colored by
 * kind) above a per-kind time breakdown. Time is derived client-side from the
 * step end conditions + pace; see `workoutBreakdown`. Renders nothing for a
 * workout with no usable duration.
 */
export function WorkoutTimeline({
  steps,
  workoutPace = null,
}: {
  steps: StepBlock[];
  workoutPace?: string | null;
}) {
  const bd = workoutBreakdown(steps, workoutPace);
  if (bd.totalMin <= 0 || bd.segments.length === 0) return null;

  const totals = (
    [
      { kind: "warmup", label: STEP_KIND_LABELS.warmup, min: bd.warmupMin },
      { kind: "work", label: STEP_KIND_LABELS.work, min: bd.workMin },
      { kind: "recovery", label: "Recovery", min: bd.recoveryMin },
      { kind: "cooldown", label: STEP_KIND_LABELS.cooldown, min: bd.cooldownMin },
    ] as Array<{ kind: StepKind; label: string; min: number }>
  ).filter((t) => t.min > 0);

  const approximate = bd.segments.some((s) => s.approximate);

  return (
    <div>
      <div className="flex items-center justify-between">
        <p className="text-sm font-semibold">Effort profile</p>
        <p className="text-sm font-medium tabular-nums text-muted-foreground">
          {roundMin(bd.totalMin)} total
        </p>
      </div>

      <div className="mt-2 flex h-4 overflow-hidden rounded-full">
        {bd.segments.map((seg, i) => (
          <div
            key={i}
            className={cn("h-full min-w-[2px]", STEP_FILL_CLASSES[seg.kind])}
            style={{ width: `${(seg.min / bd.totalMin) * 100}%` }}
            title={`${STEP_KIND_LABELS[seg.kind]} · ${roundMin(seg.min)}${
              seg.approximate ? " (approx)" : ""
            }`}
          />
        ))}
      </div>

      <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1.5">
        {totals.map((t) => (
          <span key={t.kind} className="inline-flex items-center gap-1.5 text-xs tabular-nums">
            <span className={cn("h-2 w-2 rounded-full", STEP_FILL_CLASSES[t.kind])} />
            <span className="font-medium">{t.label}</span>
            <span className="text-muted-foreground">{roundMin(t.min)}</span>
          </span>
        ))}
      </div>

      {approximate && (
        <p className="mt-2 text-xs text-muted-foreground">
          Times for distance-based steps are estimated from target pace.
        </p>
      )}
    </div>
  );
}
