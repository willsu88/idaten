"use client";

import * as React from "react";
import { Droplets } from "lucide-react";
import type { CyclePhase } from "@/lib/types";
import { api } from "@/lib/api";
import { APP_LOCALE } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useToast } from "@/components/ui/toast";

function niceDate(iso: string): string {
  const d = new Date(iso + "T00:00:00");
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleDateString(APP_LOCALE, { month: "short", day: "numeric" });
}

function statusLine(cycle: CyclePhase): { title: string; sub: string } {
  if (cycle.phase === "menstrual") {
    return {
      title: `Your period · day ${cycle.day_of_cycle}`,
      sub: cycle.ease_recommended
        ? "Your coach is keeping today lighter — listen to your body."
        : "Tracked so your coach can plan around it.",
    };
  }
  if (cycle.phase === "premenstrual") {
    const d = cycle.days_to_next_period;
    return {
      title: `Period expected in ${d} ${d === 1 ? "day" : "days"}`,
      sub: "Your coach is easing intensity as your period approaches.",
    };
  }
  return {
    title: `Period expected around ${niceDate(cycle.next_period_date)}`,
    sub: "Tracked so your coach can plan around it.",
  };
}

const todayIso = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(
    d.getDate(),
  ).padStart(2, "0")}`;
};

/**
 * Today's cycle status — shown during the period, the premenstrual lead-up, or
 * the tight drift window. In that window it also offers a ONE-TAP "did your
 * period start today?" confirmation that re-anchors the projection (the
 * non-nagging self-correction). Renders nothing on ordinary follicular/luteal
 * days, so it never becomes a permanent widget.
 */
export function CycleTodayCard({
  cycle,
  onChanged,
}: {
  cycle: CyclePhase | null | undefined;
  onChanged?: () => void;
}) {
  const [busy, setBusy] = React.useState(false);
  const [pickingDate, setPickingDate] = React.useState(false);
  // Optimistic hide so the buttons feel instant; the server flag
  // (show_started_prompt) is the source of truth after onChanged reloads.
  const [hidden, setHidden] = React.useState(false);
  const { toast } = useToast();

  const visible =
    !!cycle &&
    (cycle.phase === "menstrual" ||
      cycle.phase === "premenstrual" ||
      cycle.in_drift_window);
  if (!cycle || !visible) return null;

  const { title, sub } = statusLine(cycle);
  const showConfirm = !!cycle.show_started_prompt && !hidden;

  const confirm = async (date?: string) => {
    setBusy(true);
    setHidden(true);
    try {
      await api.cycleStarted(date);
      toast("Cycle updated");
      onChanged?.();
    } catch {
      setHidden(false);
      toast("Couldn't update — try again in a moment.", "error");
    } finally {
      setBusy(false);
      setPickingDate(false);
    }
  };

  const snooze = async () => {
    setBusy(true);
    setHidden(true);
    try {
      await api.cycleSnooze();
      onChanged?.();
    } catch {
      setHidden(false);
      toast("Couldn't update — try again in a moment.", "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card className="border-rose-500/30 bg-rose-500/[0.04]">
      <CardContent className="flex flex-col gap-3 p-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex items-start gap-3">
          <span className="mt-0.5 rounded-full bg-rose-500/15 p-2 text-rose-600 dark:text-rose-400">
            <Droplets className="h-4 w-4" />
          </span>
          <div>
            <p className="text-sm font-semibold">{title}</p>
            <p className="mt-0.5 text-sm text-muted-foreground">{sub}</p>
          </div>
        </div>

        {showConfirm && (
          <div className="shrink-0 sm:text-right">
            <p className="text-xs text-muted-foreground">Did your period start today?</p>
            <div className="mt-1.5 flex flex-wrap items-center gap-2 sm:justify-end">
              <Button size="sm" onClick={() => confirm()} disabled={busy}>
                {busy ? "Saving…" : "Yes, today"}
              </Button>
              {pickingDate ? (
                <Input
                  type="date"
                  max={todayIso()}
                  className="h-9 w-40"
                  autoFocus
                  disabled={busy}
                  onChange={(e) => e.target.value && confirm(e.target.value)}
                />
              ) : (
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => setPickingDate(true)}
                  disabled={busy}
                >
                  Another day
                </Button>
              )}
              <Button size="sm" variant="ghost" onClick={snooze} disabled={busy}>
                Not yet
              </Button>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
