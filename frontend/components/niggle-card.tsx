"use client";

import * as React from "react";
import { Bandage } from "lucide-react";
import type { Niggle } from "@/lib/types";
import { api } from "@/lib/api";
import { MetricInfo } from "@/components/metric-info";
import { NiggleLogDialog } from "@/components/niggle-log-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";

const capitalize = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

/** Severity tag: 1 = amber (minor), 2-3 = rose (protect it / injury). */
function SeverityChip({ niggle }: { niggle: Niggle }) {
  const tone =
    niggle.severity === 1
      ? "bg-amber-500/15 text-amber-600 dark:text-amber-400"
      : "bg-rose-500/15 text-rose-600 dark:text-rose-400";
  return (
    <Badge className={tone}>
      <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-current opacity-70" />
      {niggle.severity_label}
    </Badge>
  );
}

/**
 * One open niggle. Normally a quiet status row with a Resolved button; after a
 * quiet window (show_checkin) it becomes a gentle "still bothered?" question -
 * the same interaction shape as the cycle drift prompt. Optimistic on both
 * paths; the server flag is the source of truth after onChanged reloads.
 */
function NiggleRow({
  niggle,
  showCheckin = true,
  onChanged,
}: {
  niggle: Niggle;
  showCheckin?: boolean;
  onChanged?: () => void;
}) {
  const [busy, setBusy] = React.useState(false);
  const [hidden, setHidden] = React.useState(false);
  const [checkedIn, setCheckedIn] = React.useState(false);
  const { toast } = useToast();

  if (hidden) return null;

  const resolve = async () => {
    setBusy(true);
    setHidden(true);
    try {
      await api.resolveNiggle(niggle.id);
      toast("Glad it's better");
      onChanged?.();
    } catch {
      setHidden(false);
      toast("Couldn't update - try again in a moment.", "error");
    } finally {
      setBusy(false);
    }
  };

  const stillSore = async () => {
    setBusy(true);
    setCheckedIn(true);
    try {
      await api.checkinNiggle(niggle.id);
      onChanged?.();
    } catch {
      setCheckedIn(false);
      toast("Couldn't update - try again in a moment.", "error");
    } finally {
      setBusy(false);
    }
  };

  if (showCheckin && niggle.show_checkin && !checkedIn) {
    return (
      <div className="flex flex-wrap items-center justify-between gap-2 py-2.5">
        <p className="text-sm">Still bothered by your {niggle.body_part}?</p>
        <div className="flex items-center gap-2">
          <Button size="sm" onClick={resolve} disabled={busy}>
            Better now
          </Button>
          <Button size="sm" variant="ghost" onClick={stillSore} disabled={busy}>
            Still sore
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex items-center justify-between gap-2 py-1.5">
      <div className="flex min-w-0 flex-wrap items-center gap-2">
        <span className="truncate text-sm font-medium" title={niggle.note || undefined}>
          {capitalize(niggle.body_part)}
        </span>
        <SeverityChip niggle={niggle} />
        <span className="text-xs tabular-nums text-muted-foreground">
          day {niggle.days_open}
        </span>
      </div>
      <Button
        size="sm"
        variant="ghost"
        className="shrink-0 text-muted-foreground"
        onClick={resolve}
        disabled={busy}
      >
        Resolved
      </Button>
    </div>
  );
}

/**
 * Open niggles on Today - rendered only while something hurts, so it never
 * becomes a permanent widget. Reporting is athlete-initiated (chat first, the
 * log dialog as the UI fallback); the only prompt we ever show is the gentle
 * check-in row after a quiet window.
 */
export function NiggleCard({
  niggles,
  onChanged,
}: {
  niggles: Niggle[] | null | undefined;
  onChanged?: () => void;
}) {
  const [logOpen, setLogOpen] = React.useState(false);
  if (!niggles || niggles.length === 0) return null;

  return (
    <Card className="border-amber-500/30 bg-amber-500/[0.04]">
      <CardContent className="p-4">
        <div className="flex items-start gap-3">
          <span className="mt-0.5 rounded-full bg-amber-500/15 p-2 text-amber-600 dark:text-amber-400">
            <Bandage className="h-4 w-4" />
          </span>
          <div className="min-w-0 flex-1">
            <p className="flex items-center gap-0.5 text-sm font-semibold">
              Niggles
              <MetricInfo id="niggle" />
            </p>
            <p className="mt-0.5 text-sm text-muted-foreground">
              Your coach is easing the plan around{" "}
              {niggles.length === 1 ? "it until it clears" : "these until they clear"}.
            </p>
            <div className="mt-1.5 divide-y divide-border/60">
              {niggles.map((n) => (
                <NiggleRow key={n.id} niggle={n} onChanged={onChanged} />
              ))}
            </div>
            <button
              type="button"
              onClick={() => setLogOpen(true)}
              className="mt-1.5 text-sm font-medium text-accent hover:underline"
            >
              Log a niggle
            </button>
          </div>
        </div>
      </CardContent>
      <NiggleLogDialog open={logOpen} onOpenChange={setLogOpen} onSaved={onChanged} />
    </Card>
  );
}

/**
 * The standing entry point in Settings (the Today card hides itself when
 * nothing is open). Same rows and dialog; no check-in variant here - that
 * prompt belongs on Today.
 */
export function NigglesSettingsCard() {
  const [niggles, setNiggles] = React.useState<Niggle[] | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [logOpen, setLogOpen] = React.useState(false);

  const load = React.useCallback(() => {
    api
      .niggles()
      .then((res) => setNiggles(res.niggles))
      .catch(() => setNiggles(null))
      .finally(() => setLoading(false));
  }, []);

  React.useEffect(() => {
    load();
  }, [load]);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-0.5">
          Niggles &amp; injuries
          <MetricInfo id="niggle" />
        </CardTitle>
        <CardDescription>
          Tell your coach when something hurts - in chat or here - and the plan eases around it
          until it clears
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {loading ? (
          <Skeleton className="h-10 rounded-xl" />
        ) : niggles && niggles.length > 0 ? (
          <div className="divide-y divide-border rounded-xl border border-border px-4 py-1">
            {niggles.map((n) => (
              <NiggleRow key={n.id} niggle={n} showCheckin={false} onChanged={load} />
            ))}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">Nothing hurting right now.</p>
        )}
        <Button variant="outline" onClick={() => setLogOpen(true)}>
          Log a niggle
        </Button>
      </CardContent>
      <NiggleLogDialog open={logOpen} onOpenChange={setLogOpen} onSaved={load} />
    </Card>
  );
}
