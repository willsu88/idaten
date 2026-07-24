"use client";

import * as React from "react";
import type { Settings, UserInfo } from "@/lib/types";
import { api, safe } from "@/lib/api";
import { AccountCard } from "@/components/account-card";
import { ConnectGarminCard } from "@/components/connect-garmin-card";
import { CycleTrackingCard } from "@/components/cycle-tracking-card";
import { MetricInfo } from "@/components/metric-info";
import { NigglesSettingsCard } from "@/components/niggle-card";
import { PageHeader } from "@/components/page-header";
import { PERSONAS, PersonaCard } from "@/components/persona-card";
import { StrengthTrainingCard } from "@/components/strength-training-card";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/components/ui/toast";

function Field({
  label,
  info,
  children,
}: {
  label: string;
  info?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="mb-1.5 flex items-center gap-0.5 text-sm font-medium">
        {label}
        {info}
      </span>
      {children}
    </label>
  );
}

/** Read-only athlete profile rows synced from Garmin; null fields are hidden. */
function autoProfileRows(auto: Settings["athlete_auto"]): Array<{ label: string; value: string }> {
  const rows: Array<{ label: string; value: string }> = [];
  if (auto.age != null) rows.push({ label: "Age", value: String(auto.age) });
  if (auto.gender) {
    rows.push({ label: "Gender", value: auto.gender.charAt(0).toUpperCase() + auto.gender.slice(1) });
  }
  if (auto.weight_kg != null) rows.push({ label: "Weight", value: `${auto.weight_kg.toFixed(1)} kg` });
  if (auto.height_cm != null) rows.push({ label: "Height", value: `${Math.round(auto.height_cm)} cm` });
  if (auto.lthr != null) rows.push({ label: "LTHR", value: `${Math.round(auto.lthr)} bpm` });
  if (auto.vo2max_running != null)
    rows.push({ label: "VO2max (running)", value: auto.vo2max_running.toFixed(1) });
  if (auto.weekly_km_4wk != null)
    rows.push({ label: "Weekly volume (4-wk avg)", value: `${auto.weekly_km_4wk.toFixed(1)} km` });
  return rows;
}

// The API endpoint stays /api/backfill; only user-visible copy says
// "load older history" (v1.11 §2).
function BackfillCard() {
  const [days, setDays] = React.useState("300");
  const [starting, setStarting] = React.useState(false);
  const [progress, setProgress] = React.useState<{ done: number; total: number } | null>(null);
  const [running, setRunning] = React.useState(false);
  const pollRef = React.useRef<ReturnType<typeof setInterval> | null>(null);
  const { toast } = useToast();

  const stopPolling = React.useCallback(() => {
    if (pollRef.current != null) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const poll = React.useCallback(async () => {
    try {
      const status = await api.syncStatus();
      const backfill = status.backfill;
      if (backfill?.running) {
        setRunning(true);
        setProgress({ done: backfill.done_days, total: backfill.total_days });
      } else {
        if (backfill) setProgress({ done: backfill.done_days, total: backfill.total_days });
        setRunning(false);
        stopPolling();
      }
    } catch {
      // backend hiccup — keep polling
    }
  }, [stopPolling]);

  const startPolling = React.useCallback(() => {
    stopPolling();
    pollRef.current = setInterval(poll, 2000);
    poll();
  }, [poll, stopPolling]);

  // Pick up a history load that is already in flight (e.g. after a page reload).
  React.useEffect(() => {
    api
      .syncStatus()
      .then((status) => {
        if (status.backfill?.running) startPolling();
      })
      .catch(() => {});
    return stopPolling;
  }, [startPolling, stopPolling]);

  const startBackfill = async () => {
    const n = Number(days);
    if (!Number.isFinite(n) || n <= 0) {
      toast("Enter a positive number of days", "error");
      return;
    }
    setStarting(true);
    try {
      await api.backfill(Math.round(n));
      setRunning(true);
      setProgress({ done: 0, total: Math.round(n) });
      toast("Loading older history…");
      startPolling();
    } catch {
      toast("Couldn't start loading history — is the backend running?", "error");
    } finally {
      setStarting(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Data</CardTitle>
        <CardDescription>Pull older Garmin history into the coach&apos;s database</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex flex-wrap items-end gap-3">
          <Field label="Days of history">
            <Input
              type="number"
              min="1"
              className="w-32"
              value={days}
              onChange={(e) => setDays(e.target.value)}
              disabled={running}
            />
          </Field>
          <Button variant="outline" onClick={startBackfill} disabled={starting || running}>
            {starting ? "Starting…" : running ? "Loading…" : "Load older history"}
          </Button>
        </div>
        {(running || progress) && (
          <div className="space-y-1.5">
            <p className="text-sm tabular-nums text-muted-foreground">
              {running
                ? `Loading older history — ${progress?.done ?? 0}/${progress?.total ?? days} days`
                : `History loaded: ${progress?.done ?? 0}/${progress?.total ?? 0} days`}
            </p>
            {progress && progress.total > 0 && (
              <div className="h-1.5 w-full max-w-sm overflow-hidden rounded-full bg-muted">
                <div
                  className="h-full rounded-full bg-accent transition-all duration-500"
                  style={{ width: `${Math.min(100, (progress.done / progress.total) * 100)}%` }}
                />
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export default function SettingsPage() {
  const [settings, setSettings] = React.useState<Settings | null>(null);
  const [me, setMe] = React.useState<UserInfo | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState(false);
  const [personaError, setPersonaError] = React.useState<string | null>(null);
  const { toast } = useToast();
  // Last-persisted athlete blob, so blur/debounce saves only fire on real edits.
  const savedAthleteRef = React.useRef<string | null>(null);

  React.useEffect(() => {
    Promise.all([api.getSettings(), safe(api.authMe())])
      .then(([s, user]) => {
        setSettings(s);
        savedAthleteRef.current = JSON.stringify(s.athlete);
        setMe(user);
      })
      .catch(() => setError(true))
      .finally(() => setLoading(false));
  }, []);

  const update = (patch: Partial<Settings>) =>
    setSettings((s) => (s ? { ...s, ...patch } : s));

  const updateAthlete = (patch: Partial<Settings["athlete"]>) =>
    setSettings((s) => (s ? { ...s, athlete: { ...s.athlete, ...patch } } : s));

  // Every control saves the moment it changes (touching a setting IS saving
  // it): apply instantly, PUT just the changed key (the API merges per-key),
  // revert with a toast if the write fails. Same posture as the persona pick.
  const saveField = (patch: Partial<Settings>) => {
    if (!settings) return;
    const previous = settings;
    setSettings({ ...settings, ...patch });
    api
      .putSettings(patch)
      .then((saved) => setSettings((s) => (s ? { ...s, ...saved } : saved)))
      .catch(() => {
        setSettings(previous);
        toast("Couldn't save that setting — try again in a moment.", "error");
      });
  };

  // Free-text/number athlete fields save on a short debounce after typing
  // stops (also covers navigating away without blurring), never per keystroke.
  const athleteJson = settings ? JSON.stringify(settings.athlete) : null;
  React.useEffect(() => {
    if (athleteJson == null || savedAthleteRef.current == null) return;
    if (athleteJson === savedAthleteRef.current) return;
    const t = setTimeout(() => {
      const before = savedAthleteRef.current;
      savedAthleteRef.current = athleteJson;
      api
        .putSettings({ athlete: JSON.parse(athleteJson) })
        .then((saved) => {
          // Track the server's normalized shape so the merge below can't
          // re-trigger this effect into a second, redundant PUT.
          savedAthleteRef.current = JSON.stringify(saved.athlete);
          setSettings((s) => (s ? { ...s, ...saved } : saved));
        })
        .catch(() => {
          savedAthleteRef.current = before; // retry on the next edit
          toast("Couldn't save your notes — try again in a moment.", "error");
        });
    }, 800);
    return () => clearTimeout(t);
  }, [athleteJson, toast]);

  // Optimistic persona pick: highlight instantly, PUT in the background, and
  // revert with an inline error if the save fails. Cards are never disabled.
  const pickPersona = (style: Settings["coach_style"]) => {
    if (!settings || settings.coach_style === style) return;
    const previous = settings.coach_style;
    setPersonaError(null);
    update({ coach_style: style });
    api.putSettings({ coach_style: style }).catch(() => {
      setSettings((s) => (s ? { ...s, coach_style: previous } : s));
      setPersonaError("Couldn't save your coach choice — try again in a moment.");
    });
  };

  // Optimistic toggle: flip instantly, persist in the background, revert on
  // failure — same pattern as the persona pick. cycle_status is recomputed by
  // the PUT response so the summary line stays honest.
  const toggleCycle = (enabled: boolean) => {
    if (!settings) return;
    const previous = settings.cycle;
    const nextCycle = { ...settings.cycle, enabled };
    update({ cycle: nextCycle });
    api.putSettings({ cycle: nextCycle })
      .then((saved) => setSettings((s) => (s ? { ...s, ...saved } : saved)))
      .catch(() => {
        setSettings((s) => (s ? { ...s, cycle: previous } : s));
        toast("Couldn't save your cycle setting — try again in a moment.", "error");
      });
  };

  // Optimistic strength-target save — same pattern as the cycle toggle.
  const changeStrength = (strength: Settings["strength"]) => {
    if (!settings) return;
    const previous = settings.strength;
    update({ strength });
    api.putSettings({ strength })
      .then((saved) => setSettings((s) => (s ? { ...s, ...saved } : saved)))
      .catch(() => {
        setSettings((s) => (s ? { ...s, strength: previous } : s));
        toast("Couldn't save your strength setting - try again in a moment.", "error");
      });
  };

  if (loading) {
    return (
      <div>
        <PageHeader title="Settings" />
        <div className="space-y-5">
          <Skeleton className="h-64 rounded-2xl" />
          <Skeleton className="h-48 rounded-2xl" />
        </div>
      </div>
    );
  }

  if (error || !settings) {
    return (
      <div>
        <PageHeader title="Settings" />
        <Card>
          <CardContent className="p-6 text-sm text-muted-foreground">
            Couldn&apos;t load settings — is the backend running?
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div>
      <PageHeader title="Settings" subtitle="Your coach, athlete profile, data, and account" />
      <div className="space-y-5">
        {/* scroll-mt keeps the anchored card clear of sticky chrome on /settings#coach */}
        <Card id="coach" className="scroll-mt-20">
          <CardHeader>
            <CardTitle>Your coach</CardTitle>
            <CardDescription>Who coaches you, how they target workouts, and what they should know</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div>
              <div className="flex flex-col gap-3 sm:flex-row sm:items-stretch">
                {PERSONAS.map((persona) => (
                  <PersonaCard
                    key={persona.style}
                    persona={persona}
                    selected={settings.coach_style === persona.style}
                    onSelect={() => pickPersona(persona.style)}
                  />
                ))}
              </div>
              <p className="mt-1.5 text-xs text-muted-foreground">
                Personas change tone and workout flavor — never safety judgment.
              </p>
              {personaError && <p className="mt-1.5 text-xs text-danger">{personaError}</p>}
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <Field label="Training mode" info={<MetricInfo id="training_mode" />}>
                  <Select
                    value={settings.training_mode}
                    onChange={(e) =>
                      saveField({ training_mode: e.target.value as Settings["training_mode"] })
                    }
                  >
                    <option value="pace">Pace (pace targets)</option>
                    <option value="hr">Heart rate (HR-band targets)</option>
                    <option value="hybrid">Hybrid (recommended)</option>
                  </Select>
                </Field>
                <p className="mt-1.5 text-xs text-muted-foreground">
                  Hybrid uses HR bands for easy and long runs, pace for quality sessions.
                </p>
              </div>
              <div>
                <Field label="Plan source" info={<MetricInfo id="plan_source" />}>
                  <Select
                    value={settings.plan_authoring}
                    onChange={(e) =>
                      saveField({ plan_authoring: e.target.value as Settings["plan_authoring"] })
                    }
                  >
                    <option value="auto">Follow my Garmin Coach plan (recommended)</option>
                    <option value="author">Let Idaten write my whole plan</option>
                  </Select>
                </Field>
                <p className="mt-1.5 text-xs text-muted-foreground">
                  With a Garmin Coach plan, Idaten reviews it and suggests tweaks rather than
                  writing its own. Switch to have Idaten author the whole plan instead.
                </p>
              </div>
            </div>
            <Field label="Notes for the coach">
              <Textarea
                value={settings.athlete.notes}
                placeholder="Injury history, schedule constraints, preferences…"
                onChange={(e) => updateAthlete({ notes: e.target.value })}
              />
            </Field>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Athlete</CardTitle>
            <CardDescription>Helps the coach calibrate your plan</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {(() => {
              const rows = autoProfileRows(settings.athlete_auto);
              if (rows.length === 0) {
                return (
                  <>
                    <p className="text-sm text-muted-foreground">
                      Your profile (age, weight, LTHR, VO2max, weekly volume) fills in
                      automatically after the next Garmin sync.
                    </p>
                    <div className="grid gap-4 sm:grid-cols-2">
                      <Field label="Age">
                        <Input
                          type="number"
                          min="0"
                          value={settings.athlete.age ?? ""}
                          onChange={(e) =>
                            updateAthlete({
                              age: e.target.value === "" ? null : Number(e.target.value),
                            })
                          }
                        />
                      </Field>
                    </div>
                  </>
                );
              }
              return (
                <div>
                  <div className="divide-y divide-border rounded-xl border border-border">
                    {rows.map((row) => (
                      <div
                        key={row.label}
                        className="flex items-center justify-between gap-4 px-4 py-2.5"
                      >
                        <span className="text-sm text-muted-foreground">{row.label}</span>
                        <span className="text-sm font-medium tabular-nums">{row.value}</span>
                      </div>
                    ))}
                  </div>
                  <p className="mt-2 text-xs text-muted-foreground">
                    From Garmin
                    {settings.athlete_auto.updated
                      ? ` · last synced ${settings.athlete_auto.updated}`
                      : ""}
                  </p>
                </div>
              );
            })()}
          </CardContent>
        </Card>

        <StrengthTrainingCard settings={settings} onChange={changeStrength} />

        <CycleTrackingCard settings={settings} onToggle={toggleCycle} />

        <NigglesSettingsCard />

        {me && (
          <ConnectGarminCard
            me={me}
            onConnected={() => setMe((u) => (u ? { ...u, garmin_connected: true } : u))}
          />
        )}

        <BackfillCard />

        {me && (
          <AccountCard me={me}>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Daily plan hour (local)">
                <Select
                  value={settings.plan_hour}
                  onChange={(e) => saveField({ plan_hour: Number(e.target.value) })}
                >
                  {Array.from({ length: 24 }, (_, h) => (
                    <option key={h} value={h}>
                      {String(h).padStart(2, "0")}:00
                    </option>
                  ))}
                </Select>
              </Field>
            </div>
            <div className="flex items-center justify-between rounded-xl border border-border px-4 py-3">
              <div>
                <p className="text-sm font-medium">Auto-push workouts</p>
                <p className="text-xs text-muted-foreground">
                  Send accepted plan changes straight to the watch
                </p>
              </div>
              <Switch
                checked={settings.auto_push_workouts}
                onCheckedChange={(v) => saveField({ auto_push_workouts: v })}
              />
            </div>
            {/* LLM provider moved to the admin-only /admin page (alongside usage). */}
          </AccountCard>
        )}

        {/* No save button: every setting persists the moment it changes
            (selects/toggles instantly, text fields on a short debounce). */}
      </div>
    </div>
  );
}
