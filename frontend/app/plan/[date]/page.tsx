"use client";

import * as React from "react";
import Link from "next/link";
import { ArrowLeft, MessageSquare } from "lucide-react";
import type { DayIntent, HrZones, PlanDay } from "@/lib/types";
import { api } from "@/lib/api";
import {
  WORKOUT_BADGE_CLASSES,
  WORKOUT_EFFORT_LABEL,
  WORKOUT_LABELS,
  WORKOUT_PURPOSE,
} from "@/lib/workout";
import { HrZoneBar } from "@/components/hr-zone-bar";
import { coachFirstName, useCoach } from "@/components/coach-provider";
import { useChat } from "@/components/chat/chat-provider";
import { CoachNote } from "@/components/coach-note";
import { CyclePhaseChip } from "@/components/cycle-phase-chip";
import { PlanSourceChip } from "@/components/plan-source-chip";
import { IntentChip, OtherSportButton } from "@/components/intent-dialog";
import { RevertButton } from "@/components/revert-button";
import { PushButton } from "@/components/workout-card";
import { WorkoutSteps } from "@/components/workout-steps";
import { WorkoutTimeline } from "@/components/workout-timeline";
import { Badge } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { formatDay, formatDuration, formatWeekday } from "@/lib/utils";

type Mode = "editor" | "author" | null;

function StatTile({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-xl border border-border bg-background/50 px-3 py-2.5">
      <p className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
        {label}
      </p>
      <p className="mt-0.5 text-lg font-semibold tabular-nums">
        {value}
        {sub && <span className="ml-1 text-xs font-normal text-muted-foreground">{sub}</span>}
      </p>
    </div>
  );
}

export default function PlanDayPage({ params }: { params: { date: string } }) {
  const date = params.date;
  const persona = useCoach();
  const { openWithPlaceholder, setContextDate } = useChat();
  const [day, setDay] = React.useState<PlanDay | null>(null);
  const [mode, setMode] = React.useState<Mode>(null);
  const [intent, setIntent] = React.useState<DayIntent | null>(null);
  const [zones, setZones] = React.useState<HrZones | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState(false);

  const load = React.useCallback(() => {
    setLoading(true);
    api
      .planDay(date)
      .then((res) => {
        setDay(res.day);
        setMode(res.mode);
        setIntent(res.intent);
        setZones(res.hr_zones);
        setError(false);
      })
      .catch(() => setError(true))
      .finally(() => setLoading(false));
  }, [date]);

  React.useEffect(() => {
    load();
  }, [load]);

  const back = (
    <Link
      href="/week"
      className="mb-4 inline-flex min-h-9 items-center gap-1.5 text-sm font-medium text-muted-foreground hover:text-foreground"
    >
      <ArrowLeft className="h-4 w-4" />
      Back to week
    </Link>
  );

  const heading = (
    <div className="mb-4">
      <p className="text-sm font-semibold">{formatWeekday(date)}</p>
      <p className="text-sm text-muted-foreground">{formatDay(date)}</p>
    </div>
  );

  if (loading) {
    return (
      <div>
        {back}
        <div className="space-y-4">
          <Skeleton className="h-20 rounded-2xl" />
          <Skeleton className="h-56 rounded-2xl" />
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div>
        {back}
        <Card>
          <CardContent className="p-6 text-sm text-muted-foreground">
            Couldn&apos;t load this day — is the backend running?
          </CardContent>
        </Card>
      </div>
    );
  }

  // Nothing materialized, or a rest day — both render a calm, non-error state.
  const isRest = day?.workout_type === "rest";
  if (!day || isRest) {
    return (
      <div>
        {back}
        {heading}
        <Card className="border-dashed">
          <CardContent className="space-y-4 p-6">
            <div>
              <Badge className={WORKOUT_BADGE_CLASSES.rest}>{WORKOUT_LABELS.rest}</Badge>
              <p className="mt-3 text-sm text-muted-foreground">
                {day
                  ? "A rest day — no run planned. Recovery is part of the plan."
                  : "Nothing planned for this day yet."}
              </p>
            </div>
            {intent && <IntentChip intent={intent} onRemoved={load} />}
            <OtherSportButton date={date} intent={intent} onSaved={load} />
          </CardContent>
        </Card>
      </div>
    );
  }

  const hasSteps = !!day.steps && day.steps.length > 0;
  const tiles: Array<{ label: string; value: string; sub?: string }> = [];
  const dur = formatDuration(day.duration_min);
  if (dur) tiles.push({ label: "Duration", value: dur });
  if (day.distance_km != null)
    tiles.push({ label: "Distance", value: String(day.distance_km), sub: "km" });
  if (day.target_pace) {
    tiles.push({ label: "Target", value: day.target_pace, sub: "/km" });
  } else if (day.target_hr_low != null && day.target_hr_high != null) {
    const hr =
      day.target_hr_low === day.target_hr_high
        ? String(day.target_hr_low)
        : `${day.target_hr_low}–${day.target_hr_high}`;
    tiles.push({ label: "Target HR", value: hr, sub: "bpm" });
  }
  tiles.push({ label: "Effort", value: WORKOUT_EFFORT_LABEL[day.workout_type] });

  return (
    <div>
      {back}
      <Card>
        <CardHeader className="space-y-0">
          <div className="flex flex-wrap items-center gap-2">
            <Badge className={WORKOUT_BADGE_CLASSES[day.workout_type]}>
              {WORKOUT_LABELS[day.workout_type]}
            </Badge>
            <CyclePhaseChip cycle={day.cycle} />
            <PlanSourceChip mode={mode} revertible={day.revertible} hasIntent={!!intent} />
            {intent && <IntentChip intent={intent} onRemoved={load} />}
            {day.status !== "planned" && (
              <Badge variant={day.status === "completed" ? "success" : "secondary"}>
                {day.status}
              </Badge>
            )}
          </div>
          <div className="pt-2">
            <p className="text-xs text-muted-foreground">
              {formatWeekday(date)} · {formatDay(date)}
            </p>
            <CardTitle className="mt-1 text-2xl">{day.title}</CardTitle>
          </div>
        </CardHeader>

        <CardContent className="space-y-5">
          {/* At-a-glance targets — works for every run, structured or not. */}
          {tiles.length > 0 && (
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              {tiles.map((t) => (
                <StatTile key={t.label} label={t.label} value={t.value} sub={t.sub} />
              ))}
            </div>
          )}

          {/* What kind of run this is. */}
          <p className="text-sm leading-relaxed text-foreground/80">
            {WORKOUT_PURPOSE[day.workout_type]}
          </p>

          {day.description && (
            <p className="text-sm leading-relaxed text-muted-foreground">{day.description}</p>
          )}

          {/* Structured workout → steps first, then the effort profile. */}
          {hasSteps && (
            <div className="rounded-xl border border-border px-4 py-3.5">
              <p className="mb-3 text-sm font-semibold">Steps</p>
              <WorkoutSteps steps={day.steps!} />
            </div>
          )}

          {hasSteps && (
            <div className="rounded-xl border border-border p-4">
              <WorkoutTimeline steps={day.steps!} workoutPace={day.target_pace} />
            </div>
          )}

          {/* HR-targeted day → locate it on the zone scale (last). */}
          {zones && day.target_hr_low != null && day.target_hr_high != null && (
            <div className="rounded-xl border border-border p-4">
              <HrZoneBar zones={zones} low={day.target_hr_low} high={day.target_hr_high} />
            </div>
          )}

          {day.rationale && (
            <CoachNote
              note={day.rationale}
              persona={persona}
              ask={{
                label: `Ask ${persona ? coachFirstName(persona) : "your coach"}`,
                onClick: () => {
                  setContextDate(date);
                  openWithPlaceholder("Ask about this workout…");
                },
              }}
            />
          )}
        </CardContent>

        <CardFooter className="flex-wrap">
          <PushButton workout={day} onPushed={load} />
          <OtherSportButton date={date} intent={intent} onSaved={load} />
          {day.revertible && <RevertButton date={date} onReverted={load} />}
          <Link
            href={{ pathname: "/chat", query: { date } }}
            className={buttonVariants({ variant: "ghost" })}
          >
            <MessageSquare className="h-4 w-4" />
            Ask about this workout
          </Link>
        </CardFooter>
      </Card>
    </div>
  );
}
