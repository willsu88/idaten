"use client";

import * as React from "react";
import Link from "next/link";
import { ChevronRight } from "lucide-react";
import type { Settings } from "@/lib/types";
import { APP_LOCALE } from "@/lib/utils";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";

/** "Next period ~Jul 24 · day 13 of 28" from the read-only cycle_status. */
function summaryLine(settings: Settings): string | null {
  const cs = settings.cycle_status;
  if (!cs) return null;
  const d = new Date(cs.next_period_date + "T00:00:00");
  const nice = Number.isNaN(d.getTime())
    ? cs.next_period_date
    : d.toLocaleDateString(APP_LOCALE, { month: "short", day: "numeric" });
  return `Next period ~${nice} · day ${cs.day_of_cycle} of ${cs.cycle_length_days}`;
}

/**
 * The front door in Settings: a quiet, off-by-default toggle. When on, it shows
 * the prediction summary and links to the dedicated Manage-cycle page — the room
 * where the anchor is set. We deliberately do NOT inline the anchor fields here.
 */
export function CycleTrackingCard({
  settings,
  onToggle,
}: {
  settings: Settings;
  onToggle: (enabled: boolean) => void;
}) {
  const enabled = settings.cycle.enabled;
  const summary = summaryLine(settings);
  return (
    <Card>
      <CardHeader>
        <CardTitle>Cycle tracking</CardTitle>
        <CardDescription>
          Optional — let your coach ease intensity before and during your period
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex items-center justify-between rounded-xl border border-border px-4 py-3">
          <div>
            <p className="text-sm font-medium">Track menstrual cycle</p>
            <p className="text-xs text-muted-foreground">
              Set your cycle once — the coach predicts it and adjusts.
            </p>
          </div>
          <Switch checked={enabled} onCheckedChange={onToggle} />
        </div>
        {enabled && (
          <>
            {summary ? (
              <p className="text-sm tabular-nums text-muted-foreground">{summary}</p>
            ) : (
              <p className="text-sm text-muted-foreground">
                Add your last period start date so the coach can predict your cycle.
              </p>
            )}
            <Link
              href="/settings/cycle"
              className="inline-flex items-center gap-1 text-sm font-medium text-accent hover:underline"
            >
              Manage cycle
              <ChevronRight className="h-4 w-4" />
            </Link>
          </>
        )}
      </CardContent>
    </Card>
  );
}
