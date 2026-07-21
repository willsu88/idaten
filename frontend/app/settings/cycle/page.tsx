"use client";

import * as React from "react";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import type { Settings } from "@/lib/types";
import { api } from "@/lib/api";
import { PageHeader } from "@/components/page-header";
import { CycleMonthStrip } from "@/components/cycle-month-strip";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { useToast } from "@/components/ui/toast";

const PHASE_LABEL: Record<string, string> = {
  menstrual: "Period",
  premenstrual: "Premenstrual",
  follicular: "Follicular",
  luteal: "Luteal",
};

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-sm font-medium">{label}</span>
      {children}
      {hint && <span className="mt-1.5 block text-xs text-muted-foreground">{hint}</span>}
    </label>
  );
}

export default function ManageCyclePage() {
  const [settings, setSettings] = React.useState<Settings | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState(false);
  const [saving, setSaving] = React.useState(false);
  const [stripKey, setStripKey] = React.useState(0); // bump to refetch the projection
  const { toast } = useToast();

  React.useEffect(() => {
    api
      .getSettings()
      .then(setSettings)
      .catch(() => setError(true))
      .finally(() => setLoading(false));
  }, []);

  const cycle = settings?.cycle;
  const status = settings?.cycle_status;

  const patchCycle = (patch: Partial<Settings["cycle"]>) =>
    setSettings((s) => (s ? { ...s, cycle: { ...s.cycle, ...patch } } : s));

  const save = async () => {
    if (!settings) return;
    setSaving(true);
    try {
      const saved = await api.putSettings({ cycle: settings.cycle });
      // PUT recomputes cycle_status; merge so the prediction line refreshes.
      setSettings((s) => (s ? { ...s, ...saved } : saved));
      setStripKey((k) => k + 1); // re-project the month strip
      toast("Cycle saved");
    } catch {
      toast("Save failed — is the backend running?", "error");
    } finally {
      setSaving(false);
    }
  };

  const back = (
    <Link
      href="/settings"
      className="inline-flex items-center gap-1 text-sm font-medium text-muted-foreground hover:text-foreground"
    >
      <ArrowLeft className="h-4 w-4" />
      Settings
    </Link>
  );

  if (loading) {
    return (
      <div>
        <PageHeader title="Manage cycle" />
        <Skeleton className="h-72 rounded-2xl" />
      </div>
    );
  }

  if (error || !settings || !cycle) {
    return (
      <div>
        <PageHeader title="Manage cycle" actions={back} />
        <Card>
          <CardContent className="p-6 text-sm text-muted-foreground">
            Couldn&apos;t load your cycle settings — is the backend running?
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div>
      <PageHeader title="Manage cycle" subtitle="Set it once — the coach predicts it" actions={back} />
      <div className="mx-auto max-w-xl space-y-5">
        <Card>
          <CardHeader>
            <CardTitle>Cycle tracking</CardTitle>
            <CardDescription>
              Your coach eases intensity in the 2-3 days before your period and the first days of
              flow. This stays private to you.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center justify-between rounded-xl border border-border px-4 py-3">
              <div>
                <p className="text-sm font-medium">Track menstrual cycle</p>
                <p className="text-xs text-muted-foreground">Turn off any time to stop.</p>
              </div>
              <Switch
                checked={cycle.enabled}
                onCheckedChange={(v) => patchCycle({ enabled: v })}
              />
            </div>

            {cycle.enabled && (
              <>
                <Field
                  label="Last period start date"
                  hint="The first day of your most recent period. Update it here whenever it starts early or late."
                >
                  <Input
                    type="date"
                    className="w-48"
                    value={cycle.last_start_date ?? ""}
                    onChange={(e) =>
                      patchCycle({ last_start_date: e.target.value || null })
                    }
                  />
                </Field>
                <div className="grid gap-4 sm:grid-cols-2">
                  <Field label="Cycle length" hint="Days from one period to the next (typically ~28).">
                    <div className="flex items-center gap-2">
                      <Input
                        type="number"
                        min="15"
                        max="60"
                        className="w-24"
                        value={cycle.cycle_length_days}
                        onChange={(e) =>
                          patchCycle({ cycle_length_days: Number(e.target.value) })
                        }
                      />
                      <span className="text-sm text-muted-foreground">days</span>
                    </div>
                  </Field>
                  <Field label="Period length" hint="How many days your period usually lasts.">
                    <div className="flex items-center gap-2">
                      <Input
                        type="number"
                        min="1"
                        max="14"
                        className="w-24"
                        value={cycle.period_length_days}
                        onChange={(e) =>
                          patchCycle({ period_length_days: Number(e.target.value) })
                        }
                      />
                      <span className="text-sm text-muted-foreground">days</span>
                    </div>
                  </Field>
                </div>

                {status && (
                  <div className="rounded-xl border border-border bg-muted/40 px-4 py-3">
                    <p className="text-sm">
                      <span className="font-medium">{PHASE_LABEL[status.phase] ?? status.phase}</span>
                      <span className="text-muted-foreground">
                        {" "}
                        · day {status.day_of_cycle} of {status.cycle_length_days} today
                      </span>
                    </p>
                    <p className="mt-0.5 text-sm tabular-nums text-muted-foreground">
                      Next period in {status.days_to_next_period}{" "}
                      {status.days_to_next_period === 1 ? "day" : "days"} (~
                      {status.next_period_date})
                    </p>
                  </div>
                )}
              </>
            )}
          </CardContent>
        </Card>

        {cycle.enabled && cycle.last_start_date && (
          <Card>
            <CardHeader>
              <CardTitle>Projection</CardTitle>
              <CardDescription>Your predicted cycle over the next few months</CardDescription>
            </CardHeader>
            <CardContent>
              <CycleMonthStrip refreshKey={stripKey} />
            </CardContent>
          </Card>
        )}

        <div className="flex justify-end">
          <Button onClick={save} disabled={saving}>
            {saving ? "Saving…" : "Save cycle"}
          </Button>
        </div>
      </div>
    </div>
  );
}
