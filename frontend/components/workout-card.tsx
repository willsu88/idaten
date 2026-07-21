"use client";

import * as React from "react";
import Link from "next/link";
import { Check, MessageSquare, Watch, X } from "lucide-react";
import type { DayIntent, PlanDay } from "@/lib/types";
import { api } from "@/lib/api";
import { WORKOUT_BADGE_CLASSES, WORKOUT_LABELS, workoutTargetLabel } from "@/lib/workout";
import { useChat } from "@/components/chat/chat-provider";
import { coachFirstName, useCoach } from "@/components/coach-provider";
import { CoachNote } from "@/components/coach-note";
import { CyclePhaseChip } from "@/components/cycle-phase-chip";
import { IntentChip, OtherSportButton } from "@/components/intent-dialog";
import { RevertButton } from "@/components/revert-button";
import { PlanSourceChip } from "@/components/plan-source-chip";
import { WorkoutSteps } from "@/components/workout-steps";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { useToast } from "@/components/ui/toast";
import { APP_LOCALE, formatDuration } from "@/lib/utils";

export function WorkoutMeta({ workout }: { workout: PlanDay }) {
  const parts: string[] = [];
  const dur = formatDuration(workout.duration_min);
  if (dur) parts.push(dur);
  if (workout.distance_km != null) parts.push(`${workout.distance_km} km`);
  const target = workoutTargetLabel(workout);
  if (target) parts.push(target);
  if (parts.length === 0) return null;
  return <p className="text-sm font-medium tabular-nums text-muted-foreground">{parts.join(" · ")}</p>;
}

function pushedTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleTimeString(APP_LOCALE, { hour: "2-digit", minute: "2-digit", hour12: false });
}

/** Stale = a (now outdated) version is still on the Garmin calendar. */
export function isStaleOnWatch(workout: PlanDay): boolean {
  return workout.garmin_workout_id != null && workout.pushed_at == null;
}

export function PushButton({
  workout,
  onPushed,
  size = "default",
}: {
  workout: PlanDay;
  onPushed?: () => void;
  size?: "default" | "sm";
}) {
  const [busy, setBusy] = React.useState(false);
  const { toast } = useToast();

  if (workout.workout_type === "rest") return null;

  const push = async () => {
    setBusy(true);
    try {
      await api.pushWorkout(workout.date);
      toast("Workout pushed to watch");
      onPushed?.();
    } catch {
      toast("Push failed — is the backend running?", "error");
    } finally {
      setBusy(false);
    }
  };

  const unpush = async () => {
    setBusy(true);
    try {
      await api.unpushWorkout(workout.date);
      toast("Workout removed from watch");
      onPushed?.();
    } catch {
      toast("Remove failed — is the backend running?", "error");
    } finally {
      setBusy(false);
    }
  };

  if (workout.pushed_at != null) {
    const time = pushedTime(workout.pushed_at);
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-success/10 py-1 pl-2.5 pr-1 text-sm font-medium text-success">
        <Watch className="h-4 w-4" />
        <Check className="h-3.5 w-3.5" />
        <span className="tabular-nums">On watch{time ? ` · ${time}` : ""}</span>
        <button
          type="button"
          onClick={unpush}
          disabled={busy}
          aria-label="Remove from watch"
          title="Remove from watch"
          className="-my-1.5 rounded-full p-2 text-success/70 transition-colors hover:bg-success/15 hover:text-success disabled:opacity-50"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </span>
    );
  }

  const stale = isStaleOnWatch(workout);

  return (
    <span className="inline-flex flex-wrap items-center justify-end gap-2">
      {stale && (
        <Badge className="bg-amber-500/15 text-amber-600 dark:text-amber-400">
          Changed — resend
        </Badge>
      )}
      <Button size={size} variant="outline" onClick={push} disabled={busy}>
        <Watch className="h-4 w-4" />
        {busy ? "Pushing…" : stale ? "Resend to watch" : "Push to watch"}
      </Button>
    </span>
  );
}

export function TodayWorkoutCard({
  workout,
  intent,
  mode,
  onChanged,
}: {
  workout: PlanDay | null;
  intent?: DayIntent | null;
  mode?: "editor" | "author" | null;
  onChanged?: () => void;
}) {
  const persona = useCoach();
  const { openWithPlaceholder, setContextDate } = useChat();
  const today = new Date();
  const dateStr = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;

  if (!workout) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Today&apos;s workout</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm text-muted-foreground">
          <p>No workout planned — run a sync or ask the coach to plan your week.</p>
          {intent && <IntentChip intent={intent} onRemoved={onChanged} />}
        </CardContent>
        <CardFooter>
          <OtherSportButton date={dateStr} intent={intent ?? null} onSaved={onChanged} />
        </CardFooter>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-3 space-y-0">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge className={WORKOUT_BADGE_CLASSES[workout.workout_type]}>
              {WORKOUT_LABELS[workout.workout_type]}
            </Badge>
            <CyclePhaseChip cycle={workout.cycle} />
            <PlanSourceChip mode={mode} revertible={workout.revertible} hasIntent={!!intent} />
            {intent && <IntentChip intent={intent} onRemoved={onChanged} />}
          </div>
          {workout.workout_type === "rest" ? (
            <>
              <CardTitle className="mt-2 text-xl">{workout.title}</CardTitle>
              <div className="mt-1">
                <WorkoutMeta workout={workout} />
              </div>
            </>
          ) : (
            <Link href={`/plan/${workout.date}`} className="group block">
              <CardTitle className="mt-2 text-xl group-hover:underline">{workout.title}</CardTitle>
              <div className="mt-1">
                <WorkoutMeta workout={workout} />
              </div>
            </Link>
          )}
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="text-sm leading-relaxed text-muted-foreground">{workout.description}</p>
        {workout.steps && workout.steps.length > 0 && (
          <div className="rounded-xl border border-border px-3.5 py-2.5">
            <WorkoutSteps steps={workout.steps} />
          </div>
        )}
        {workout.rationale && (
          <CoachNote
            note={workout.rationale}
            persona={persona}
            ask={{
              label: `Ask ${persona ? coachFirstName(persona) : "your coach"}`,
              onClick: () => {
                setContextDate(workout.date);
                openWithPlaceholder("Ask about today's workout…");
              },
            }}
          />
        )}
      </CardContent>
      <CardFooter className="flex-wrap">
        <PushButton workout={workout} onPushed={onChanged} />
        <OtherSportButton date={workout.date} intent={intent ?? null} onSaved={onChanged} />
        {workout.revertible && <RevertButton date={workout.date} onReverted={onChanged} />}
        <Link
          href={{ pathname: "/chat", query: { date: workout.date } }}
          className={buttonVariants({ variant: "ghost" })}
        >
          <MessageSquare className="h-4 w-4" />
          Ask about this workout
        </Link>
      </CardFooter>
    </Card>
  );
}
