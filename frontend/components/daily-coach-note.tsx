"use client";

// The daily review on Today: lazily triggers the one LLM call of the day and
// progressively renders the coach's note. Today paints the base plan instantly;
// this fills in a moment later (reads as liveness, not lag).
//
// State machine mirrors the backend's one-call-per-day contract:
//   loading      first poll of /dashboard/review (brief; render nothing)
//   waiting_data last night's data hasn't synced — NO LLM call; show honest
//                copy, and after a window offer the degraded "review anyway"
//   evaluating   data present, the review LLM call is in flight
//   done         show the coach_note (or nothing if there wasn't one)

import * as React from "react";
import type { DailyReview } from "@/lib/types";
import { api, safe } from "@/lib/api";
import { useCoach } from "@/components/coach-provider";
import { CoachNote } from "@/components/coach-note";
import { Button } from "@/components/ui/button";

const POLL_MS = 5000;
const CALM_POLL_MS = 60000; // once data is overdue, stop looking busy — check occasionally
const DEGRADED_AFTER_MS = 25000; // reveal "review anyway" once data is clearly late

type Status = "loading" | "waiting_data" | "evaluating" | "done";

const isDone = (r: DailyReview | null): boolean =>
  r != null && (r.state === "done_full" || r.state === "done_structural");

export function DailyCoachNote({ onProposal }: { onProposal?: () => void }) {
  const persona = useCoach();
  const [status, setStatus] = React.useState<Status>("loading");
  const [note, setNote] = React.useState("");
  const [review, setReview] = React.useState<DailyReview | null>(null);
  const [showDegraded, setShowDegraded] = React.useState(false);
  const [overdue, setOverdue] = React.useState(false);
  const startedEval = React.useRef(false);
  const firedProposal = React.useRef(false);

  const finish = React.useCallback(
    (review: DailyReview | null) => {
      setNote(review?.coach_note ?? "");
      setReview(review);
      setStatus("done");
      if (review?.proposal_id && !firedProposal.current) {
        firedProposal.current = true;
        onProposal?.();
      }
    },
    [onProposal],
  );

  React.useEffect(() => {
    let cancelled = false;
    let poll: ReturnType<typeof setTimeout> | undefined;

    async function loop() {
      const res = await safe(api.dashboardReview());
      if (cancelled) return;
      if (!res) {
        setStatus("done"); // give up quietly — the base plan still stands
        return;
      }
      if (isDone(res.review)) {
        finish(res.review);
        return;
      }
      if (res.data_ready) {
        // Data present → run the one review call (idempotent server-side).
        if (!startedEval.current) {
          startedEval.current = true;
          setStatus("evaluating");
          const r = await safe(api.dashboardEvaluate(false));
          if (!cancelled) finish(r);
        }
        return;
      }
      setStatus("waiting_data");
      setOverdue(res.data_overdue ?? false);
      // Overdue = the night likely isn't recorded yet (not a slow sync):
      // stop polling like something is about to happen.
      poll = setTimeout(loop, res.data_overdue ? CALM_POLL_MS : POLL_MS);
    }

    loop();
    const degrade = setTimeout(() => {
      if (!cancelled) setShowDegraded(true);
    }, DEGRADED_AFTER_MS);

    return () => {
      cancelled = true;
      if (poll) clearTimeout(poll);
      clearTimeout(degrade);
    };
  }, [finish]);

  const runStructural = async () => {
    setStatus("evaluating");
    finish(await safe(api.dashboardEvaluate(true)));
  };

  if (status === "loading") return null;
  if (status === "done")
    return note && review ? (
      <CoachNote
        note={note}
        persona={persona}
        feedback={{ surface: "coach_note", ref: review.date, state: review.my_feedback ?? null }}
      />
    ) : null;

  const coachName = persona?.name ?? "Coach";

  // Calm overdue state: data is absent (unrecorded night), not late — no pulse,
  // no "syncing…" urgency, and the structural review is promoted to a real button.
  if (status === "waiting_data" && overdue) {
    return (
      <div className="rounded-xl bg-muted/50 px-3.5 py-3">
        <p className="text-sm text-muted-foreground">
          No sleep data from Garmin yet - I&apos;ll pick it up when it lands.
        </p>
        <Button variant="secondary" size="sm" className="mt-2.5" onClick={runStructural}>
          Review with recent training instead
        </Button>
      </div>
    );
  }

  return (
    <div className="rounded-xl bg-muted/50 px-3.5 py-3">
      <div className="flex items-center gap-2">
        <div className="h-6 w-6 animate-pulse rounded-full bg-muted-foreground/20" />
        <span className="text-sm font-medium text-muted-foreground">
          {status === "evaluating"
            ? `${coachName} is reviewing today…`
            : "Getting last night's sleep & recovery from Garmin…"}
        </span>
      </div>
      {status === "waiting_data" && showDegraded && (
        <button
          type="button"
          onClick={runStructural}
          className="mt-2 text-sm font-medium text-accent hover:underline"
        >
          Review with recent training instead
        </button>
      )}
    </div>
  );
}
