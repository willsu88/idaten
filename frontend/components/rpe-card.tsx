"use client";

import * as React from "react";
import type { Activity } from "@/lib/types";
import { api } from "@/lib/api";
import { MetricInfo } from "@/components/metric-info";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/components/ui/toast";
import { cn } from "@/lib/utils";

function rpeTone(n: number) {
  if (n <= 3) return "hover:bg-success/15 hover:text-success hover:border-success/50";
  if (n <= 6) return "hover:bg-warning/15 hover:text-warning hover:border-warning/50";
  return "hover:bg-danger/15 hover:text-danger hover:border-danger/50";
}

/**
 * Shared 1–10 RPE tap scale with an optional note.
 * Used by the home-page prompt and the activity detail page; supports re-rating —
 * tapping a number submits it (with the note, if any) right away.
 */
export function RpeScale({
  activityId,
  currentRpe = null,
  currentNote = null,
  onRated,
}: {
  activityId: number;
  currentRpe?: number | null;
  currentNote?: string | null;
  onRated?: (rating: number) => void;
}) {
  const [selected, setSelected] = React.useState<number | null>(currentRpe);
  const [note, setNote] = React.useState(currentNote ?? "");
  const [submitting, setSubmitting] = React.useState<number | null>(null);
  const { toast } = useToast();

  React.useEffect(() => setSelected(currentRpe), [currentRpe]);
  React.useEffect(() => setNote(currentNote ?? ""), [currentNote]);

  const rate = async (rating: number) => {
    setSubmitting(rating);
    try {
      await api.rateActivity(activityId, rating, note.trim() || undefined);
      setSelected(rating);
      toast("Effort logged — thanks!");
      onRated?.(rating);
    } catch {
      toast("Could not save rating", "error");
    } finally {
      setSubmitting(null);
    }
  };

  return (
    <div>
      <div className="mb-2 flex justify-end">
        <MetricInfo id="rpe" label="What's RPE?" />
      </div>
      <div className="flex flex-wrap gap-1.5">
        {Array.from({ length: 10 }, (_, i) => i + 1).map((n) => (
          <button
            key={n}
            type="button"
            disabled={submitting !== null}
            onClick={() => rate(n)}
            aria-pressed={selected === n}
            className={cn(
              "h-11 w-11 rounded-xl border border-border text-sm font-semibold tabular-nums transition-colors disabled:opacity-50 sm:h-10 sm:w-10",
              rpeTone(n),
              (submitting === n || (submitting === null && selected === n)) &&
                "border-accent bg-accent text-accent-foreground hover:bg-accent hover:text-accent-foreground",
            )}
          >
            {n}
          </button>
        ))}
      </div>
      <p className="mt-2 flex justify-between text-[11px] text-muted-foreground">
        <span>Easy</span>
        <span>Max effort</span>
      </p>
      <Textarea
        value={note}
        rows={2}
        placeholder="Optional note — how did it feel?"
        className="mt-2"
        onChange={(e) => setNote(e.target.value)}
      />
      <p className="mt-1.5 text-[11px] text-muted-foreground">
        Tap a number to save{note.trim() ? " (your note is included)" : ""}.
      </p>
    </div>
  );
}

/** Home-page prompt: asks about the latest unrated run and disappears once rated. */
export function RpeCard({
  activity,
  onRated,
}: {
  activity: Activity;
  onRated?: () => void;
}) {
  const [done, setDone] = React.useState(false);

  if (done) return null;

  const meta: string[] = [];
  if (activity.distance_km != null) meta.push(`${activity.distance_km.toFixed(1)} km`);
  if (activity.duration_min != null) meta.push(`${Math.round(activity.duration_min)} min`);
  if (activity.avg_pace) meta.push(`${activity.avg_pace} /km`);

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium">
          How hard was <span className="text-accent">{activity.name}</span>?
        </CardTitle>
        {meta.length > 0 && <CardDescription className="text-xs">{meta.join(" · ")}</CardDescription>}
      </CardHeader>
      <CardContent>
        <RpeScale
          activityId={activity.id}
          onRated={() => {
            setDone(true);
            onRated?.();
          }}
        />
      </CardContent>
    </Card>
  );
}
