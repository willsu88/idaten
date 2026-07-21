"use client";

import * as React from "react";
import { ArrowRight, Check, GitBranch, History, X } from "lucide-react";
import type { PendingEdit, PlanDay } from "@/lib/types";
import { api, ApiError, safe } from "@/lib/api";
import { compactStepsSummary, WORKOUT_BADGE_CLASSES, WORKOUT_LABELS, workoutTargetLabel } from "@/lib/workout";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { useToast } from "@/components/ui/toast";
import { cn, formatDay, formatDuration } from "@/lib/utils";

function DaySummary({ day, muted }: { day: PlanDay | null; muted?: boolean }) {
  if (!day) {
    return <p className="text-sm italic text-muted-foreground">—</p>;
  }
  const meta: string[] = [];
  const dur = formatDuration(day.duration_min);
  if (dur) meta.push(dur);
  if (day.distance_km != null) meta.push(`${day.distance_km} km`);
  const target = workoutTargetLabel(day);
  if (target) meta.push(target);
  return (
    <div className={cn(muted && "opacity-60")}>
      <Badge className={cn("mb-1", WORKOUT_BADGE_CLASSES[day.workout_type])}>
        {WORKOUT_LABELS[day.workout_type]}
      </Badge>
      <p className={cn("text-sm font-medium", muted && "line-through decoration-muted-foreground/60")}>
        {day.title}
      </p>
      {meta.length > 0 && (
        <p className="text-xs tabular-nums text-muted-foreground">{meta.join(" · ")}</p>
      )}
      {day.steps && day.steps.length > 0 && (
        // Structured days diff via the compact one-line summary (old vs new).
        <p className="mt-0.5 text-xs tabular-nums text-muted-foreground">
          {compactStepsSummary(day.steps)}
        </p>
      )}
    </div>
  );
}

function EditDiff({ edit }: { edit: PendingEdit }) {
  const currentByDate = new Map(edit.current.map((d) => [d.date, d]));
  return (
    <div className="space-y-2">
      {edit.changes.map((proposed) => {
        const current = currentByDate.get(proposed.date) ?? null;
        return (
          <div
            key={proposed.date}
            className="rounded-xl border border-border bg-background/50 p-3"
          >
            <p className="mb-2 text-xs font-medium uppercase tracking-wider text-muted-foreground">
              {formatDay(proposed.date)}
            </p>
            <div className="grid items-start gap-3 sm:grid-cols-[1fr_auto_1fr]">
              <DaySummary day={current} muted />
              <ArrowRight className="mt-1 hidden h-4 w-4 text-muted-foreground sm:block" />
              <DaySummary day={proposed} />
            </div>
          </div>
        );
      })}
    </div>
  );
}

type Resolution = "accepted" | "dismissed" | "superseded";

// Optional one-tap dismiss reasons (quality signal, COACH_QUALITY.md). Purely
// after the fact — never a step in front of the dismiss itself.
const DISMISS_REASONS: Array<{ tag: string; label: string }> = [
  { tag: "didnt_want_change", label: "Didn't want the change" },
  { tag: "reasoning_wrong", label: "The reasoning was wrong" },
];

/** Shown in the confirmation state after a dismiss in this session. Tapping a
 * chip posts the reason (rating null); just leaving it is fine and quiet. */
function DismissReasonChips({ editId }: { editId: number }) {
  const [sent, setSent] = React.useState(false);

  const send = (tag: string) => {
    setSent(true); // optimistic — a lost reason is not worth an error state
    void safe(
      api.postFeedback({ surface: "edit_proposal", ref: String(editId), rating: null, tags: [tag] }),
    );
  };

  if (sent) {
    return <p className="text-xs text-muted-foreground">Noted - thanks.</p>;
  }
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className="text-xs text-muted-foreground">Why? (optional)</span>
      {DISMISS_REASONS.map(({ tag, label }) => (
        <button
          key={tag}
          type="button"
          onClick={() => send(tag)}
          className="rounded-full border border-border px-2.5 py-1 text-xs font-medium text-muted-foreground transition-colors hover:text-foreground"
        >
          {label}
        </button>
      ))}
    </div>
  );
}

export function EditProposalCard({
  edit,
  onResolved,
  compact,
}: {
  edit: PendingEdit;
  onResolved?: (status: Resolution) => void;
  compact?: boolean;
}) {
  const [busy, setBusy] = React.useState<"accept" | "dismiss" | null>(null);
  // Local override for actions taken in this card; the prop stays the server
  // truth (it flips when a newer proposal supersedes this one mid-thread).
  const [localResolved, setLocalResolved] = React.useState<Resolution | null>(null);
  const resolved: Resolution | null =
    localResolved ?? (edit.status === "pending" ? null : edit.status);
  const { toast } = useToast();

  const act = async (action: "accept" | "dismiss") => {
    setBusy(action);
    try {
      if (action === "accept") await api.acceptEdit(edit.id);
      else await api.dismissEdit(edit.id);
      const status = action === "accept" ? "accepted" : "dismissed";
      setLocalResolved(status);
      toast(action === "accept" ? "Plan updated" : "Proposal dismissed");
      onResolved?.(status);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        // Resolved elsewhere (newer proposal, another tab): the backend says
        // what happened — show it and retire the buttons.
        toast(err.message, "error");
        const msg = err.message.toLowerCase();
        const status: Resolution = msg.includes("superseded")
          ? "superseded"
          : msg.includes("accepted")
            ? "accepted"
            : "dismissed";
        setLocalResolved(status);
        onResolved?.(status);
      } else {
        toast("Action failed — is the backend running?", "error");
      }
    } finally {
      setBusy(null);
    }
  };

  return (
    <Card className={cn("border-accent/40", compact && "shadow-none")}>
      <CardHeader>
        <div className="flex items-center gap-2 text-accent">
          <GitBranch className="h-4 w-4" />
          <span className="text-xs font-semibold uppercase tracking-wider">
            Proposed plan change
          </span>
        </div>
        <CardTitle className="text-base">{edit.summary}</CardTitle>
        {edit.rationale && <CardDescription>{edit.rationale}</CardDescription>}
      </CardHeader>
      <CardContent>
        <EditDiff edit={edit} />
        {!resolved && (
          <p className="mt-3 text-xs text-muted-foreground">
            Nothing changes until you accept - this is only a proposal.
          </p>
        )}
      </CardContent>
      <CardFooter>
        {resolved ? (
          <div className="flex flex-col gap-2">
            <span
              className={cn(
                "inline-flex items-center gap-1.5 text-sm font-medium",
                resolved === "accepted" ? "text-success" : "text-muted-foreground",
              )}
            >
              {resolved === "accepted" ? (
                <Check className="h-4 w-4" />
              ) : resolved === "superseded" ? (
                <History className="h-4 w-4" />
              ) : (
                <X className="h-4 w-4" />
              )}
              {resolved === "accepted"
                ? "Accepted"
                : resolved === "superseded"
                  ? "Superseded by a newer proposal"
                  : "Dismissed"}
            </span>
            {/* Only after a dismiss taken here — a proposal resolved elsewhere
                (server truth, another tab) never asks in retrospect. */}
            {localResolved === "dismissed" && <DismissReasonChips editId={edit.id} />}
          </div>
        ) : (
          <>
            <Button size="sm" onClick={() => act("accept")} disabled={busy !== null}>
              <Check className="h-4 w-4" />
              {busy === "accept" ? "Applying…" : "Accept"}
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => act("dismiss")}
              disabled={busy !== null}
            >
              <X className="h-4 w-4" />
              Dismiss
            </Button>
          </>
        )}
      </CardFooter>
    </Card>
  );
}
