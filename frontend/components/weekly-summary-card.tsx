"use client";

// The weekly summary — the coach's retrospective on a closed Mon-Sun week
// (ADR 0002: its own artifact, independent of the daily review). Permanent
// home: the Week page, for any week that has one. Delivery moment: Mondays
// on Today, right below the daily review, linking to the Week page.
//
// Lazy fallback mirrors the daily review's: when the summary is missing but
// still generatable (only the most recently closed week), `evaluate` fires
// the one idempotent LLM call; older weeks render what exists or nothing.

import * as React from "react";
import Link from "next/link";
import type { WeeklyCoachSummary } from "@/lib/types";
import { api, safe } from "@/lib/api";
import { personaForStyle, useCoach } from "@/components/coach-provider";
import { CoachNote } from "@/components/coach-note";

export function WeeklySummaryCard({
  weekStart,
  evaluate = false,
  linkToWeek = false,
}: {
  /** Monday of the summary week to show (any date in the week is normalized server-side). */
  weekStart: string;
  /** Generate lazily when missing-but-generatable (Today's Monday card, last closed week on /week). */
  evaluate?: boolean;
  /** Point at the artifact's permanent home (used on Today). */
  linkToWeek?: boolean;
}) {
  const persona = useCoach();
  const [summary, setSummary] = React.useState<WeeklyCoachSummary | null>(null);
  const [evaluating, setEvaluating] = React.useState(false);
  const [settled, setSettled] = React.useState(false);
  const startedEval = React.useRef(false);

  React.useEffect(() => {
    let cancelled = false;
    (async () => {
      const res = await safe(api.weekSummary(weekStart));
      if (cancelled) return;
      if (res?.summary) {
        setSummary(res.summary);
      } else if (res?.generatable && evaluate && !startedEval.current) {
        startedEval.current = true;
        setEvaluating(true);
        const generated = await safe(api.weekSummaryEvaluate(weekStart));
        if (!cancelled) {
          setSummary(generated?.summary ?? null);
          setEvaluating(false);
        }
      }
      if (!cancelled) setSettled(true);
    })();
    return () => {
      cancelled = true;
    };
  }, [weekStart, evaluate]);

  if (evaluating) {
    return (
      <div className="rounded-xl bg-muted/50 px-3.5 py-3">
        <div className="flex items-center gap-2">
          <div className="h-6 w-6 animate-pulse rounded-full bg-muted-foreground/20" />
          <span className="text-sm font-medium text-muted-foreground">
            {`${persona?.name ?? "Coach"} is looking back at your week…`}
          </span>
        </div>
      </div>
    );
  }
  if (!settled || !summary?.coach_note) return null;

  // Attribution frozen at generation time, same contract as the daily review.
  const author = summary.coach ? personaForStyle(summary.coach) : persona;
  return (
    <div className="space-y-1.5">
      <div className="flex items-baseline justify-between">
        <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Week in review
        </p>
        {linkToWeek && (
          <Link
            href={`/week?start=${summary.week_start}`}
            className="text-xs font-medium text-accent hover:underline"
          >
            See the full week
          </Link>
        )}
      </div>
      <CoachNote
        note={summary.coach_note}
        persona={author}
        feedback={{
          surface: "weekly_summary",
          ref: summary.week_start,
          state: summary.my_feedback ?? null,
        }}
      />
    </div>
  );
}
