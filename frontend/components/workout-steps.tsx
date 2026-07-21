import type { StepBlock, StepKind, WorkoutStep } from "@/lib/types";
import { STEP_KIND_LABELS, stepEndLabel, stepTargetLabel } from "@/lib/workout";
import { formatDuration } from "@/lib/utils";
import { cn } from "@/lib/utils";

/** Left-accent color per step kind (matches the effort-profile timeline). */
const STEP_BAR_CLASSES: Record<StepKind, string> = {
  warmup: "bg-sky-500",
  work: "bg-rose-500",
  recovery: "bg-teal-500",
  cooldown: "bg-indigo-500",
  rest: "bg-slate-400",
};

/** Total minutes of a repeat block, or null if any step isn't time-based. */
function blockMinutes(block: StepBlock): number | null {
  let sum = 0;
  for (const s of block.steps) {
    if (s.duration_min == null) return null;
    sum += s.duration_min;
  }
  return sum * Math.max(1, block.repeat);
}

function StepRow({ step }: { step: WorkoutStep }) {
  const target = stepTargetLabel(step);
  const end = stepEndLabel(step);
  return (
    <div className="flex items-stretch gap-3">
      <span className={cn("w-1 shrink-0 rounded-full", STEP_BAR_CLASSES[step.kind])} />
      <div className="min-w-0 flex-1 py-0.5">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-semibold">{STEP_KIND_LABELS[step.kind]}</span>
          {end && (
            <span className="rounded-md bg-muted px-2 py-0.5 text-xs font-semibold tabular-nums">
              {end}
            </span>
          )}
          {target && (
            <span className="rounded-md bg-muted px-2 py-0.5 text-xs font-medium tabular-nums text-foreground/70">
              {target}
            </span>
          )}
        </div>
        {step.note && <p className="mt-0.5 text-xs text-muted-foreground">{step.note}</p>}
      </div>
    </div>
  );
}

/**
 * Structured workout steps: each step is a row with a color-coded left accent;
 * repeat blocks are grouped in a card with an "N×" badge and the set total.
 */
export function WorkoutSteps({ steps }: { steps: StepBlock[] }) {
  return (
    <div className="space-y-2.5">
      {steps.map((block, i) => {
        if (block.repeat > 1) {
          const total = blockMinutes(block);
          const totalLabel = total != null ? formatDuration(Math.round(total)) : null;
          return (
            <div key={i} className="rounded-xl border border-border bg-muted/30 p-2.5">
              <div className="mb-2 flex items-center gap-2">
                <span className="inline-flex items-center rounded-md bg-accent/15 px-1.5 py-0.5 text-xs font-bold tabular-nums text-accent">
                  {block.repeat}×
                </span>
                <span className="text-xs font-medium text-muted-foreground">
                  repeat{totalLabel ? ` · ${totalLabel} total` : ""}
                </span>
              </div>
              <div className="space-y-2">
                {block.steps.map((step, j) => (
                  <StepRow key={j} step={step} />
                ))}
              </div>
            </div>
          );
        }
        return (
          <div key={i} className="space-y-2">
            {block.steps.map((step, j) => (
              <StepRow key={j} step={step} />
            ))}
          </div>
        );
      })}
    </div>
  );
}
