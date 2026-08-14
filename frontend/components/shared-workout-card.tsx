"use client";

import * as React from "react";
import { Check, Gift, X } from "lucide-react";
import type { SharedWorkoutCore, SharedWorkoutItem } from "@/lib/types";
import { api, ApiError } from "@/lib/api";
import {
  compactStepsSummary,
  WORKOUT_BADGE_CLASSES,
  WORKOUT_LABELS,
  workoutTargetLabel,
} from "@/lib/workout";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useToast } from "@/components/ui/toast";
import { cn, formatDay, formatDuration, isoDate } from "@/lib/utils";

function WorkoutSummary({ label, workout }: { label: string; workout: SharedWorkoutCore }) {
  const meta: string[] = [];
  const dur = formatDuration(workout.duration_min);
  if (dur) meta.push(dur);
  if (workout.distance_km != null) meta.push(`${workout.distance_km} km`);
  const target = workoutTargetLabel(workout);
  if (target) meta.push(target);
  return (
    <div>
      <p className="mb-1 text-xs font-medium uppercase tracking-wider text-muted-foreground">
        {label}
      </p>
      {meta.length > 0 && (
        <p className="text-sm font-medium tabular-nums">{meta.join(" · ")}</p>
      )}
      {workout.steps && workout.steps.length > 0 && (
        <p className="mt-0.5 text-xs tabular-nums text-muted-foreground">
          {compactStepsSummary(workout.steps)}
        </p>
      )}
      {meta.length === 0 && (!workout.steps || workout.steps.length === 0) && (
        <p className="text-sm italic text-muted-foreground">No targets</p>
      )}
    </div>
  );
}

/** A workout another member sent me (ADR 0022): accept verbatim, accept with
 * my own zones/paces (side-by-side preview), or decline. */
export function SharedWorkoutCard({
  share,
  onResolved,
}: {
  share: SharedWorkoutItem;
  onResolved?: () => void;
}) {
  const [busy, setBusy] = React.useState<"as_is" | "adapted" | "decline" | null>(null);
  const [date, setDate] = React.useState(share.date);
  const { toast } = useToast();

  const act = async (action: "as_is" | "adapted" | "decline") => {
    setBusy(action);
    try {
      if (action === "decline") {
        await api.declineShare(share.id);
        toast("Declined");
      } else {
        await api.acceptShare(share.id, action, date !== share.date ? date : undefined);
        toast(
          action === "adapted"
            ? "Added to your plan with your zones"
            : "Added to your plan",
        );
      }
      onResolved?.();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Action failed", "error");
    } finally {
      setBusy(null);
    }
  };

  const w = share.workout;
  return (
    <Card className="border-accent/40">
      <CardHeader>
        <div className="flex items-center gap-2 text-accent">
          <Gift className="h-4 w-4" />
          <span className="text-xs font-semibold uppercase tracking-wider">
            {share.from} sent you a workout
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Badge className={WORKOUT_BADGE_CLASSES[w.workout_type]}>
            {WORKOUT_LABELS[w.workout_type]}
          </Badge>
          <CardTitle className="text-base">{w.title}</CardTitle>
        </div>
        {w.description && (
          <p className="text-sm text-muted-foreground">{w.description}</p>
        )}
      </CardHeader>
      <CardContent className="space-y-3">
        {/* Their numbers vs mine, when a translation exists. */}
        <div
          className={cn(
            "grid gap-3 rounded-xl border border-border bg-background/50 p-3",
            share.adapted && "sm:grid-cols-2",
          )}
        >
          <WorkoutSummary
            label={share.adapted ? `${share.from}'s targets` : "Targets"}
            workout={w}
          />
          {share.adapted && <WorkoutSummary label="With your zones" workout={share.adapted} />}
        </div>

        {share.adapt_unavailable_reason && (
          <p className="text-xs text-muted-foreground">
            Can&apos;t translate to your zones: {share.adapt_unavailable_reason}.
          </p>
        )}

        {share.conflict && (
          <p className="text-xs font-medium text-amber-600 dark:text-amber-400">
            Accepting replaces your planned {WORKOUT_LABELS[share.conflict.workout_type]} (
            {share.conflict.title}) on {formatDay(date)}.
          </p>
        )}

        <label className="flex items-center gap-2 text-xs text-muted-foreground">
          For
          <Input
            type="date"
            value={date}
            min={isoDate()}
            onChange={(e) => setDate(e.target.value)}
            className="h-8 w-auto"
          />
        </label>
      </CardContent>
      <CardFooter className="flex-wrap">
        <Button size="sm" onClick={() => act("as_is")} disabled={busy !== null}>
          <Check className="h-4 w-4" />
          {busy === "as_is" ? "Adding…" : "Accept their targets"}
        </Button>
        <Button
          size="sm"
          variant="outline"
          onClick={() => act("adapted")}
          disabled={busy !== null || share.adapted == null}
        >
          <Check className="h-4 w-4" />
          {busy === "adapted" ? "Adding…" : "Accept with my zones"}
        </Button>
        <Button
          size="sm"
          variant="ghost"
          onClick={() => act("decline")}
          disabled={busy !== null}
        >
          <X className="h-4 w-4" />
          Decline
        </Button>
      </CardFooter>
    </Card>
  );
}
