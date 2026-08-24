import Link from "next/link";
import { ArrowDownRight, ArrowRight, ArrowUpRight, ChevronRight } from "lucide-react";
import type { Direction, Tone } from "@/lib/trends";
import { cn } from "@/lib/utils";

/** Tiny unlabeled trend line - a direction cue, not a readable chart. */
export function Sparkline({ values, className }: { values: number[]; className?: string }) {
  if (values.length < 2) return null;
  const w = 64;
  const h = 20;
  const pad = 2;
  const min = Math.min(...values);
  const span = Math.max(...values) - min || 1;
  const points = values
    .map((v, i) => {
      const x = pad + (i * (w - 2 * pad)) / (values.length - 1);
      const y = h - pad - ((v - min) / span) * (h - 2 * pad);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className={cn("h-5 w-16", className)} aria-hidden>
      <polyline
        points={points}
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

const DIRECTION_ICONS = {
  up: ArrowUpRight,
  down: ArrowDownRight,
  flat: ArrowRight,
} as const;

/**
 * The glanceable stat tile shared by the Today readiness card and the Trends
 * tile row: a label, a toned headline value, and optionally a direction arrow
 * and sparkline.
 */
export function StatTile({
  label,
  value,
  sub,
  tone,
  direction,
  spark,
  info,
  href,
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: Tone | null;
  direction?: Direction | null;
  spark?: number[];
  info?: React.ReactNode;
  href?: string;
}) {
  const DirectionIcon = direction ? DIRECTION_ICONS[direction] : null;
  const body = (
    <>
      <p className="flex items-center gap-1 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
        {label}
        {info}
        {href && <ChevronRight className="ml-auto h-3.5 w-3.5" />}
      </p>
      <p
        className={cn(
          "mt-0.5 flex items-center gap-1 text-lg font-semibold tabular-nums",
          tone === "success" && "text-success",
          tone === "warning" && "text-warning",
          tone === "danger" && "text-danger",
        )}
      >
        {value}
        {DirectionIcon && <DirectionIcon className="h-4 w-4 shrink-0" />}
        {sub && <span className="text-xs font-normal text-muted-foreground">{sub}</span>}
      </p>
      {spark && <Sparkline values={spark} className="mt-1 text-muted-foreground/70" />}
    </>
  );
  const className = "rounded-xl border border-border bg-background/50 px-3 py-2.5";
  if (href) {
    return (
      <Link
        href={href}
        className={cn(className, "block transition-colors hover:border-accent/50 hover:bg-muted/50")}
      >
        {body}
      </Link>
    );
  }
  return <div className={className}>{body}</div>;
}
