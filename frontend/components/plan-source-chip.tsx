"use client";

// Per-workout provenance in editor mode: who set this day. Untouched Garmin
// base -> "Garmin Coach"; a day the coach adjusted (revertible override) ->
// "Coach <persona>". Self-made days (a committed other-sport intent) get no
// chip — they're the athlete's own, not from either plan. Author mode shows
// nothing (every day is the coach's, so the header badge already says so).

import * as React from "react";
import { Watch } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { useCoach } from "@/components/coach-provider";

export function PlanSourceChip({
  mode,
  revertible,
  hasIntent,
}: {
  mode: "editor" | "author" | null | undefined;
  revertible: boolean | undefined;
  hasIntent: boolean;
}) {
  const persona = useCoach();
  if (mode !== "editor" || hasIntent) return null;

  if (revertible) {
    return <Badge variant="default">{persona?.name ?? "Coach"}</Badge>;
  }
  return (
    <Badge variant="secondary">
      <Watch className="h-3 w-3" />
      Garmin Coach
    </Badge>
  );
}
