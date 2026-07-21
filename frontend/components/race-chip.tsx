import type { RacePrediction } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { formatSeconds } from "@/lib/utils";

/** "+7:10" / "-3:05" — signed h:mm:ss delta vs goal. */
export function formatSignedSeconds(deltaS: number): string {
  return `${deltaS <= 0 ? "-" : "+"}${formatSeconds(Math.abs(deltaS))}`;
}

/** Human label for common race distances. */
export function distanceLabel(km: number): string {
  const near = (target: number) => Math.abs(km - target) < 0.15;
  if (near(5)) return "5k";
  if (near(10)) return "10k";
  if (near(21.1)) return "Half";
  if (near(42.2)) return "Marathon";
  return `${km} km`;
}

/** "in 42 days" / "today" / "past" countdown text. */
export function countdownLabel(daysToRace: number): string {
  if (daysToRace === 0) return "today";
  if (daysToRace < 0) return `${-daysToRace} day${daysToRace === -1 ? "" : "s"} ago`;
  return `in ${daysToRace} day${daysToRace === 1 ? "" : "s"}`;
}

/** Goal-relative tail: "on track for 2:28:00" when ahead, "+7:10 vs goal" behind. */
function goalTail(delta: number | null, goalS: number | null): string | null {
  if (goalS == null) return null;
  if (delta != null && delta <= 0) return `on track for ${formatSeconds(goalS)}`;
  if (delta != null) return `${formatSignedSeconds(delta)} vs goal`;
  return `goal ${formatSeconds(goalS)}`;
}

/**
 * Garmin's predicted finish as a plain chip — the number the athlete also sees in
 * the Garmin app, surfaced here. This is the DEFAULT prediction shown across the
 * app (Idaten's own calibrated prediction stays behind SHOW_RACE_PREDICTION).
 * "Predicted 2:01:31 · +9:31 vs goal": green when at/ahead of goal, amber behind.
 */
export function GarminPredictionChip({ prediction }: { prediction: RacePrediction | null }) {
  const predicted = prediction?.garmin_time_s ?? null;
  const goalS = prediction?.goal_time_s ?? null;
  if (predicted == null) {
    return <Badge variant="secondary">Prediction —</Badge>;
  }
  const delta = goalS != null ? predicted - goalS : null;
  const variant = delta == null ? "secondary" : delta <= 0 ? "success" : "warning";
  return (
    <span className="inline-flex flex-wrap items-center gap-1.5">
      <Badge variant="outline" className="text-muted-foreground">
        Garmin
      </Badge>
      <Badge variant={variant} className="tabular-nums">
        Predicted {formatSeconds(predicted)}
        {delta != null && <> · {formatSignedSeconds(delta)} vs goal</>}
      </Badge>
    </span>
  );
}

/**
 * Idaten's authoritative prediction as a compact chip — for the small surfaces
 * (Today countdown, Trends outlook). Shows the range + goal relation, NO Garmin
 * number and NO reconciliation line (see PredictionDetail for those). Low
 * confidence softens to a single "~" estimate so it doesn't overclaim.
 */
export function PredictionChip({ prediction }: { prediction: RacePrediction | null }) {
  const likely = prediction?.likely_s ?? null;
  if (likely == null) {
    return <Badge variant="secondary">Prediction —</Badge>;
  }
  const { low_s, high_s, delta_s, goal_time_s, confidence } = prediction!;
  const tail = goalTail(delta_s, goal_time_s);

  if (confidence === "low") {
    return (
      <Badge variant="secondary" className="tabular-nums text-muted-foreground">
        ~{formatSeconds(likely)}
        {goal_time_s != null && <> · goal {formatSeconds(goal_time_s)}</>}
      </Badge>
    );
  }
  const range =
    low_s != null && high_s != null
      ? `${formatSeconds(low_s)}–${formatSeconds(high_s)}`
      : formatSeconds(likely);
  const variant = delta_s == null ? "secondary" : delta_s <= 0 ? "success" : "warning";
  return (
    <Badge variant={variant} className="tabular-nums">
      Likely {range}
      {tail && <> · {tail}</>}
    </Badge>
  );
}

const CONFIDENCE_LABEL: Record<string, string> = {
  high: "high confidence",
  medium: "moderate confidence",
  low: "low confidence",
};

/** Should the Garmin reconciliation line show? Only when ours is authoritative
 * and Garmin's differs meaningfully (≥ 60s) from ours. */
export function showReconciliation(p: RacePrediction): boolean {
  return (
    p.source === "idaten" &&
    p.garmin_time_s != null &&
    p.likely_s != null &&
    Math.abs(p.garmin_time_s - p.likely_s) >= 60
  );
}

/**
 * Full prediction block for the races card / race detail: Idaten's range as the
 * headline, a confidence label, and — only when it differs — Garmin's number as
 * a subordinate reference with the one-line "why". Idaten leads; Garmin rides
 * along. `onAddEffort` powers the low-confidence "sharpen this" nudge.
 */
export function PredictionDetail({
  prediction,
  onAddEffort,
}: {
  prediction: RacePrediction | null;
  onAddEffort?: () => void;
}) {
  if (!prediction || prediction.likely_s == null) {
    return <Badge variant="secondary">Prediction —</Badge>;
  }
  return (
    <div className="flex flex-col gap-1">
      <div className="flex flex-wrap items-center gap-2">
        <PredictionChip prediction={prediction} />
        {prediction.confidence && (
          <span className="text-xs text-muted-foreground">
            {CONFIDENCE_LABEL[prediction.confidence]}
          </span>
        )}
      </div>
      {showReconciliation(prediction) && (
        <p className="text-xs text-muted-foreground">
          Garmin predicts{" "}
          <span className="tabular-nums">{formatSeconds(prediction.garmin_time_s!)}</span> — ours
          corrects that for how you&apos;ve actually raced.
        </p>
      )}
      {prediction.confidence === "low" && onAddEffort && (
        <button
          type="button"
          onClick={onAddEffort}
          className="w-fit text-xs text-primary underline-offset-2 hover:underline"
        >
          Add a recent race or time-trial to sharpen this
        </button>
      )}
    </div>
  );
}
