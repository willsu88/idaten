"use client";

import * as React from "react";
import { Info } from "lucide-react";
import { cn } from "@/lib/utils";

export type MetricId =
  | "ctl"
  | "atl"
  | "tsb"
  | "acwr"
  | "ramp"
  | "ef"
  | "hr_drift"
  | "vo2max"
  | "easy_pct";

/**
 * Coaching copy per metric — this exact wording is part of the product
 * (API_CONTRACT.md "Metric explanations"), do not paraphrase.
 */
const METRIC_COPY: Record<MetricId, { title: string; body: string }> = {
  ctl: {
    title: "Fitness (CTL)",
    body: "Your 42-day weighted average training load — think engine size. It rises slowly with consistent training and falls when you stop. How to use it: build gradually and let it climb over months; going into your race taper with a higher CTL is what actually makes you faster on race day.",
  },
  atl: {
    title: "Fatigue (ATL)",
    body: "Your 7-day weighted average training load — the stress you're carrying right now. It spikes after big days and fades within a week. How to use it: high ATL is fine and normal in hard weeks, but several high-ATL weeks without recovery days is how overtraining starts.",
  },
  tsb: {
    title: "Form (TSB)",
    body: "Fitness minus Fatigue (CTL − ATL). Positive = fresh, negative = fatigued. How to use it: productive training usually happens slightly negative (−10 to −20). Below about −25, injury and illness risk climbs — back off. You want to arrive at race day slightly positive (+5 to +15), which is what the taper is for.",
  },
  acwr: {
    title: "ACWR",
    body: "Acute:chronic workload ratio — this week's load divided by your ~monthly norm. How to use it: 0.8–1.3 (the shaded band) is the safe ramp zone. Above ~1.5 you're increasing load faster than your body has adapted to — classic injury territory. Persistently below 0.8 means you're detraining.",
  },
  ramp: {
    title: "Load ramp",
    body: "Compares your last 7 days of training load to your last 28. A ratio over ~1.3 held for several days means you're ramping faster than your body can adapt to - the classic overuse-injury setup. One easy week never trips it; your baseline absorbs it.",
  },
  ef: {
    title: "Aerobic efficiency (EF)",
    body: "Speed per heartbeat on easy runs: meters-per-minute ÷ average HR. How to use it: if EF trends up at the same easy effort over weeks, your aerobic base is genuinely improving — you run faster at the same HR. Compare fairly: heat, hills, and fatigue all depress EF, which is why points are colored by temperature.",
  },
  hr_drift: {
    title: "HR drift",
    body: "How much your heart rate rose in the second half of a run relative to pace (aerobic decoupling). How to use it: under 5% means the run was truly aerobic — your endurance held. Repeatedly above 8–10% on easy runs means the pace is too fast for your current base, or heat/dehydration is interfering. A shrinking drift on long runs is one of the clearest signs your base is building.",
  },
  easy_pct: {
    title: "Easy share (80/20)",
    body: "The share of this week's training time spent in heart-rate zones 1–2 — the easy zones. Endurance training works best polarized: roughly 80% easy, 20% hard. Early in the week one easy run reads 100%; judge the number by Sunday. Persistently under ~70% usually means your easy runs are creeping too hard, which blunts both recovery and the quality sessions.",
  },
  vo2max: {
    title: "VO2max",
    body: "Garmin's estimate of your maximal oxygen uptake — the broadest single fitness number. How to use it: it moves slowly, so judge the 3-month trend and ignore daily wiggles. VO2max rising together with EF is strong evidence the training is working; a sustained drop during heavy training can be an early overtraining flag.",
  },
};

/**
 * Small ⓘ trigger with an explanation popover.
 * Desktop: opens on hover. Touch: tap to toggle, tap outside (or Esc) to dismiss.
 */
export function MetricInfo({
  id,
  label,
  className,
}: {
  id: MetricId;
  label?: string;
  className?: string;
}) {
  const [open, setOpen] = React.useState(false);
  const [align, setAlign] = React.useState<"left" | "center" | "right">("center");
  const rootRef = React.useRef<HTMLSpanElement>(null);
  const copy = METRIC_COPY[id];

  React.useEffect(() => {
    if (!open) return;
    const onPointerDown = (e: PointerEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const show = () => {
    // Keep the ~18rem popover on screen: align it away from nearby viewport edges.
    const rect = rootRef.current?.getBoundingClientRect();
    if (rect) {
      const popHalf = 144; // half of w-72
      const center = rect.left + rect.width / 2;
      if (center - popHalf < 12) setAlign("left");
      else if (center + popHalf > window.innerWidth - 12) setAlign("right");
      else setAlign("center");
    }
    setOpen(true);
  };

  return (
    <span ref={rootRef} className={cn("relative inline-flex", className)}>
      <button
        type="button"
        aria-label={`What is ${copy.title}?`}
        aria-expanded={open}
        onClick={() => (open ? setOpen(false) : show())}
        onPointerEnter={(e) => {
          if (e.pointerType === "mouse") show();
        }}
        onPointerLeave={(e) => {
          if (e.pointerType === "mouse") setOpen(false);
        }}
        className={cn(
          // negative margin keeps layout tight while the ≥40px hit area stays finger-friendly
          "-m-2 inline-flex min-h-10 min-w-10 items-center justify-center gap-1 rounded-md p-2 text-muted-foreground transition-colors hover:text-foreground",
          open && "text-foreground",
        )}
      >
        {label && <span className="text-xs font-medium">{label}</span>}
        <Info className="h-3.5 w-3.5" />
      </button>
      {open && (
        <span
          role="tooltip"
          className={cn(
            // whitespace-normal: the trigger may sit inside a nowrap line (e.g.
            // the week summary); the popover body must still wrap.
            "absolute top-full z-50 mt-1.5 block w-72 max-w-[calc(100vw-2rem)] whitespace-normal rounded-xl border border-border bg-card p-3 text-left shadow-lg",
            align === "center" && "left-1/2 -translate-x-1/2",
            align === "left" && "left-0",
            align === "right" && "right-0",
          )}
        >
          <span className="mb-1 block text-xs font-bold text-foreground">{copy.title}</span>
          <span className="block text-xs font-normal leading-relaxed text-muted-foreground">
            {copy.body}
          </span>
        </span>
      )}
    </span>
  );
}
