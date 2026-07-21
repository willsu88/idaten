import type { Readiness } from "@/lib/types";
import { READINESS_CLASSES } from "@/lib/workout";
import { MetricInfo } from "@/components/metric-info";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

function ReadinessRing({ readiness }: { readiness: Readiness }) {
  const { score, level } = readiness;
  const r = 52;
  const c = 2 * Math.PI * r;
  const filled = c * Math.min(Math.max(score, 0), 100) / 100;
  const styles = READINESS_CLASSES[level];

  return (
    <div className="relative h-36 w-36 shrink-0">
      <svg viewBox="0 0 120 120" className="h-full w-full -rotate-90">
        <circle
          cx="60"
          cy="60"
          r={r}
          fill="none"
          strokeWidth="9"
          className="stroke-muted"
        />
        <circle
          cx="60"
          cy="60"
          r={r}
          fill="none"
          strokeWidth="9"
          strokeLinecap="round"
          stroke={styles.stroke}
          strokeDasharray={`${filled} ${c - filled}`}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className={cn("text-4xl font-bold tabular-nums", styles.text)}>{score}</span>
        <span className="text-[11px] uppercase tracking-wider text-muted-foreground">
          Readiness
        </span>
      </div>
    </div>
  );
}

function StatTile({
  label,
  value,
  sub,
  tone,
  info,
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: "success" | "warning" | "danger";
  info?: React.ReactNode;
}) {
  return (
    <div className="rounded-xl border border-border bg-background/50 px-3 py-2.5">
      <p className="flex items-center gap-1 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
        {label}
        {info}
      </p>
      <p
        className={cn(
          "mt-0.5 text-lg font-semibold tabular-nums",
          tone === "success" && "text-success",
          tone === "warning" && "text-warning",
          tone === "danger" && "text-danger",
        )}
      >
        {value}
        {sub && <span className="ml-1 text-xs font-normal text-muted-foreground">{sub}</span>}
      </p>
    </div>
  );
}

export function ReadinessCard({ readiness }: { readiness: Readiness | null }) {
  if (!readiness) {
    return (
      <Card>
        <CardContent className="p-5 text-sm text-muted-foreground">
          No readiness data yet — run a sync.
        </CardContent>
      </Card>
    );
  }

  const c = readiness.components;
  const styles = READINESS_CLASSES[readiness.level];
  const hrvTone =
    c.hrv_delta_pct == null ? undefined : c.hrv_delta_pct < -8 ? "danger" : c.hrv_delta_pct < -3 ? "warning" : "success";
  const tsbTone = c.tsb == null ? undefined : c.tsb < -15 ? "danger" : c.tsb < -5 ? "warning" : "success";

  return (
    <Card>
      <CardContent className="flex flex-col gap-5 p-5 sm:flex-row sm:items-center">
        <div className="flex items-center gap-5">
          <ReadinessRing readiness={readiness} />
          <div className="sm:hidden">
            <span className={cn("rounded-full px-3 py-1 text-sm font-medium", styles.bg, styles.text)}>
              {styles.label}
            </span>
          </div>
        </div>
        <div className="flex-1">
          <span
            className={cn(
              "hidden rounded-full px-3 py-1 text-sm font-medium sm:inline-block",
              styles.bg,
              styles.text,
            )}
          >
            {styles.label}
          </span>
          <div className="mt-0 grid grid-cols-2 gap-2 sm:mt-4 lg:grid-cols-4">
            <StatTile
              label="HRV Δ"
              value={
                c.hrv_delta_pct == null
                  ? "–"
                  : `${c.hrv_delta_pct > 0 ? "+" : ""}${c.hrv_delta_pct.toFixed(1)}%`
              }
              sub="vs 7d"
              tone={hrvTone}
            />
            <StatTile
              label="Sleep"
              value={c.sleep_hours == null ? "–" : `${c.sleep_hours.toFixed(1)}h`}
              sub={c.sleep_score == null ? undefined : `score ${Math.round(c.sleep_score)}`}
            />
            <StatTile
              label="Body battery"
              value={c.body_battery == null ? "–" : String(Math.round(c.body_battery))}
            />
            <StatTile
              label="TSB"
              value={c.tsb == null ? "–" : c.tsb.toFixed(1)}
              tone={tsbTone}
              info={<MetricInfo id="tsb" />}
            />
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
