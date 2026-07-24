"use client";

import * as React from "react";
import Link from "next/link";
import { Check } from "lucide-react";
import { ActivityTypeIcon } from "@/components/activity-icon";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import type { StrengthSession, SupportActivity } from "@/lib/types";
import { cn, formatDuration, prettyType } from "@/lib/utils";

/** One-line label: "Strength · 32 min", RPE appended when logged. */
function sessionMeta(s: SupportActivity): string {
  const parts: string[] = [];
  const dur = formatDuration(s.duration_min);
  if (dur) parts.push(dur);
  if (s.rpe != null) parts.push(`RPE ${s.rpe}`);
  return parts.join(" · ");
}

/**
 * Today's completed non-run sessions (strength, yoga, rides…). Support work
 * alongside the run plan — rendered only when something was done, so it is
 * never a permanent widget.
 */
export function SupportSessionCard({ sessions }: { sessions: SupportActivity[] }) {
  if (!sessions.length) return null;
  return (
    <Card>
      <CardContent className="space-y-1 p-3">
        {sessions.map((s) => (
          <Link
            key={s.id}
            href={`/activities/${s.id}`}
            className="group flex items-center gap-2.5 rounded-md p-1.5 transition-colors hover:bg-muted/60"
          >
            <ActivityTypeIcon type={s.type} />
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium leading-tight group-hover:underline">
                {s.name || prettyType(s.type)}
              </p>
              <p className="truncate text-xs leading-tight text-muted-foreground">
                {[prettyType(s.type), sessionMeta(s)].filter(Boolean).join(" · ")}
              </p>
            </div>
          </Link>
        ))}
      </CardContent>
    </Card>
  );
}

/**
 * Today's planned strength session (the coach's placement or a manual one).
 * Auto-completed sessions vanish from here — the synced activity already shows
 * in SupportSessionCard; a manual complete shows a quiet done state.
 */
export function StrengthTodayCard({
  session,
  onChanged,
}: {
  session: StrengthSession | null;
  onChanged: () => void;
}) {
  const [busy, setBusy] = React.useState(false);
  const { toast } = useToast();
  if (!session || session.status === "skipped") return null;
  if (session.status === "completed" && session.activity_id != null) return null;

  const done = session.status === "completed";
  const meta = [formatDuration(session.duration_min), session.focus]
    .filter(Boolean)
    .join(" · ");

  const complete = async () => {
    setBusy(true);
    try {
      await api.completeStrength(session.id);
      toast("Strength session done - nice work");
      onChanged();
    } catch {
      toast("Couldn't save — is the backend running?", "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card className={cn(done && "border-success/30 bg-success/5")}>
      <CardContent className="flex items-center gap-2.5 p-3">
        <ActivityTypeIcon type="strength_training" />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium leading-tight">
            Strength{meta ? ` · ${meta}` : ""}
          </p>
          {session.rationale && (
            <p className="text-xs leading-tight text-muted-foreground">{session.rationale}</p>
          )}
        </div>
        {done ? (
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full border-2 border-success/50 bg-success/10 text-success">
            <Check className="h-4 w-4" strokeWidth={3} />
          </span>
        ) : (
          <Button size="sm" variant="secondary" disabled={busy} onClick={complete}>
            Mark done
          </Button>
        )}
      </CardContent>
    </Card>
  );
}

/** Week-row chip for a strength-lane session: dashed while planned, solid green
 * once manually completed. Auto-completed ones are omitted by the caller — the
 * synced activity's own SupportChip covers them. */
export function StrengthChip({ session }: { session: StrengthSession }) {
  const done = session.status === "completed";
  const dur = formatDuration(session.duration_min);
  return (
    <span
      className={cn(
        "flex items-center gap-1 rounded-full py-0.5 pl-0.5 pr-2 text-[11px] font-medium",
        done
          ? "bg-success/10 text-success"
          : "border border-dashed border-accent/50 bg-transparent text-accent",
      )}
      title={["Strength", dur, session.focus].filter(Boolean).join(" · ")}
    >
      <ActivityTypeIcon
        type="strength_training"
        className={cn("h-5 w-5 [&>svg]:h-3 [&>svg]:w-3", done && "bg-success/10 text-success")}
      />
      {dur && <span>{dur}</span>}
      {done && <Check className="h-3 w-3" strokeWidth={3} />}
    </span>
  );
}

/** Compact chip for a Week day row: icon + duration, linking to the session. */
export function SupportChip({ session }: { session: SupportActivity }) {
  const Meta = formatDuration(session.duration_min);
  return (
    <Link
      href={`/activities/${session.id}`}
      className="flex items-center gap-1 rounded-full bg-accent/10 py-0.5 pl-0.5 pr-2 text-[11px] font-medium text-accent transition-colors hover:bg-accent/20"
      aria-label={`${prettyType(session.type)}${Meta ? `, ${Meta}` : ""}`}
      title={session.name || prettyType(session.type)}
    >
      <ActivityTypeIcon type={session.type} className="h-5 w-5 [&>svg]:h-3 [&>svg]:w-3" />
      {Meta && <span>{Meta}</span>}
    </Link>
  );
}
