"use client";

import * as React from "react";
import { Download, X } from "lucide-react";
import { api } from "@/lib/api";

const POLL_MS = 10_000;

/**
 * Shown on all logged-in pages while the 300-day Garmin backfill runs.
 * Polls GET /api/sync/status every ~10s; dismissable for the session.
 */
export function OnboardingBanner() {
  const [progress, setProgress] = React.useState<{ done: number; total: number } | null>(null);
  const [dismissed, setDismissed] = React.useState(false);

  React.useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        const status = await api.syncStatus();
        if (cancelled) return;
        setProgress(
          status.backfill?.running
            ? { done: status.backfill.done_days, total: status.backfill.total_days }
            : null,
        );
      } catch {
        // backend hiccup or logged out (the 401 handler redirects) — keep quiet
      }
    };
    poll();
    const interval = setInterval(poll, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  if (!progress || dismissed) return null;

  return (
    <div className="mb-5 flex items-start gap-3 rounded-xl border border-accent/40 bg-accent/10 px-4 py-3">
      <Download className="mt-0.5 h-4 w-4 shrink-0 text-accent" />
      <div className="flex-1 text-sm">
        <p className="font-medium">
          Loading your Garmin history —{" "}
          <span className="tabular-nums">
            {progress.done}/{progress.total}
          </span>{" "}
          days synced
        </p>
        <p className="text-xs text-muted-foreground">
          Charts fill in as data arrives; check back later.
        </p>
      </div>
      <button
        type="button"
        aria-label="Dismiss"
        onClick={() => setDismissed(true)}
        className="rounded-lg p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
      >
        <X className="h-4 w-4" />
      </button>
    </div>
  );
}
