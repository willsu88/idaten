"use client";

import * as React from "react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useToast } from "@/components/ui/toast";

/**
 * Home-page prompt for an ambiguous run: a run on a day with a planned workout
 * that auto-attribution didn't link. One question, folded into the Today moment:
 * "Was this your {workout}?" A Yes scores it; a No marks it a plain run forever.
 */
export function AttributionCard({
  activityId,
  workoutLabel,
  onResolved,
}: {
  activityId: number;
  workoutLabel: string;
  onResolved?: () => void;
}) {
  const [busy, setBusy] = React.useState(false);
  const [done, setDone] = React.useState(false);
  const { toast } = useToast();

  if (done) return null;

  const answer = async (attempted: boolean) => {
    setBusy(true);
    setDone(true); // optimistic — the card should vanish instantly
    try {
      const res = await api.attributeActivity(activityId, attempted);
      if (attempted) {
        toast(
          res.execution_score != null
            ? `Scored — execution ${res.execution_score}/100`
            : "Logged as your workout",
        );
      }
      onResolved?.();
    } catch {
      toast("Could not save", "error");
      setDone(false);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium">
          Was this your <span className="text-accent">{workoutLabel}</span> session?
        </CardTitle>
      </CardHeader>
      <CardContent>
        <p className="mb-3 text-xs text-muted-foreground">
          We&apos;ll score how well you executed it against the plan.
        </p>
        <div className="flex gap-2">
          <Button size="sm" onClick={() => answer(true)} disabled={busy}>
            Yes, score it
          </Button>
          <Button size="sm" variant="ghost" onClick={() => answer(false)} disabled={busy}>
            No, just a run
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
