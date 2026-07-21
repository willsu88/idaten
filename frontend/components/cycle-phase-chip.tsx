import * as React from "react";
import type { CyclePhase } from "@/lib/types";
import { Badge } from "@/components/ui/badge";

// We surface a chip only where phase carries a coaching meaning: the ease window
// (period + premenstrual lead-up) and the follicular "strong" window where the
// coach may green-light harder work. The luteal "normal" stretch stays unmarked
// so a chip always means something rather than decorating every row.
const VISIBLE: Record<string, boolean> = {
  menstrual: true,
  premenstrual: true,
  follicular: true,
};

const STYLES: Record<string, string> = {
  // rose = active period; amber = pre-period ease; emerald = strong follicular window
  menstrual: "bg-rose-500/15 text-rose-600 dark:text-rose-400",
  premenstrual: "bg-amber-500/15 text-amber-600 dark:text-amber-400",
  follicular: "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400",
};

function label(cycle: CyclePhase): string {
  if (cycle.phase === "menstrual") return `Menstrual · day ${cycle.day_of_cycle}`;
  if (cycle.phase === "follicular") return "Follicular · strong";
  return "Premenstrual";
}

function title(cycle: CyclePhase): string {
  if (cycle.phase === "menstrual") {
    return `Day ${cycle.day_of_cycle} of your period${
      cycle.ease_recommended ? " — kept lighter" : ""
    }`;
  }
  if (cycle.phase === "follicular") {
    return "Follicular phase — often your strongest window; a good day to attack quality work";
  }
  const d = cycle.days_to_next_period;
  return `Period likely in ${d} day${d === 1 ? "" : "s"} — kept lighter`;
}

/** Small phase tag shown on a workout during the ease window; null otherwise. */
export function CyclePhaseChip({
  cycle,
  className,
}: {
  cycle: CyclePhase | null | undefined;
  className?: string;
}) {
  if (!cycle || !VISIBLE[cycle.phase]) return null;
  return (
    <Badge className={`${STYLES[cycle.phase]} ${className ?? ""}`} title={title(cycle)}>
      <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-current opacity-70" />
      {label(cycle)}
    </Badge>
  );
}
