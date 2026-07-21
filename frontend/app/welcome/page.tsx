"use client";

// Setup wizard (/welcome): a full-screen 5-step flow where the user DOES the
// setup — each step embeds the real form and saves via the real API call.
// Replay mode (?replay=1) is the same wizard, prefilled, all steps skippable,
// and never re-writes tutorial_done. ?step=N (1-based) deep-links a step.

import * as React from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  CalendarDays,
  Check,
  ChevronLeft,
  ChevronRight,
  Loader2,
  MessageSquare,
  MoreHorizontal,
  Sun,
  TrendingUp,
  X,
  type LucideIcon,
} from "lucide-react";
import type { Race, Settings, UserInfo } from "@/lib/types";
import { api, ApiError, safe } from "@/lib/api";
import { cn, formatDay } from "@/lib/utils";
import { countdownLabel, distanceLabel } from "@/components/race-chip";
import { ConnectGarminCard } from "@/components/connect-garmin-card";
import { OnboardingBanner } from "@/components/onboarding-banner";
import { PERSONAS, PersonaCard } from "@/components/persona-card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";

const STEP_COUNT = 5;

function StepHeading({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <div className="mb-5">
      <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
      {subtitle && <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">{subtitle}</p>}
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-sm font-medium">{label}</span>
      {children}
    </label>
  );
}

// --- Step 4: minimal add-race form ---

const DISTANCE_PRESETS = [
  { label: "5k", km: 5 },
  { label: "10k", km: 10 },
  { label: "Half", km: 21.1 },
  { label: "Marathon", km: 42.2 },
] as const;

const GOAL_TIME_RE = /^\d{1,2}:[0-5]\d(:[0-5]\d)?$/;

function RaceStep({
  races,
  onAdded,
}: {
  races: Race[] | null;
  onAdded: (race: Race) => void;
}) {
  const [name, setName] = React.useState("");
  const [date, setDate] = React.useState("");
  const [distance, setDistance] = React.useState("");
  const [goalTime, setGoalTime] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  if (races && races.length > 0) {
    return (
      <div className="space-y-3">
        <p className="text-sm text-muted-foreground">
          You already have {races.length === 1 ? "a race" : "races"} on the calendar — the starred
          one drives your plan.
        </p>
        <div className="divide-y divide-border rounded-2xl border border-border">
          {races.map((race) => (
            <div key={race.id} className="flex items-center justify-between gap-3 px-4 py-3">
              <div className="min-w-0">
                <p className="truncate text-sm font-semibold">{race.name}</p>
                <p className="text-xs text-muted-foreground">
                  {formatDay(race.date)} ({countdownLabel(race.days_to_race)}) ·{" "}
                  {distanceLabel(race.distance_km)}
                </p>
              </div>
              {race.is_primary && (
                <span className="shrink-0 text-xs font-medium text-accent">Primary</span>
              )}
            </div>
          ))}
        </div>
        <p className="text-xs text-muted-foreground">
          Races on your Garmin calendar import automatically on sync.
        </p>
      </div>
    );
  }

  const distanceKm = Number(distance);
  const validDistance = distance !== "" && Number.isFinite(distanceKm) && distanceKm > 0;
  const validGoal = goalTime.trim() === "" || GOAL_TIME_RE.test(goalTime.trim());
  const valid = name.trim() !== "" && date !== "" && validDistance && validGoal;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!valid || busy) return;
    setBusy(true);
    setError(null);
    try {
      const race = await api.createRace({
        name: name.trim(),
        date,
        distance_km: distanceKm,
        ...(goalTime.trim() ? { goal_time: goalTime.trim() } : {}),
      });
      onAdded(race);
    } catch {
      setError("Couldn't save the race — try again in a moment.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="space-y-4">
      <Field label="Race name">
        <Input value={name} placeholder="Berlin Marathon" onChange={(e) => setName(e.target.value)} />
      </Field>
      <Field label="Date">
        <Input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
      </Field>
      <div>
        <span className="mb-1.5 block text-sm font-medium">Distance</span>
        <div className="flex flex-wrap items-center gap-2">
          {DISTANCE_PRESETS.map((p) => (
            <Button
              key={p.label}
              type="button"
              size="sm"
              variant={validDistance && Math.abs(distanceKm - p.km) < 0.001 ? "default" : "outline"}
              onClick={() => setDistance(String(p.km))}
            >
              {p.label}
            </Button>
          ))}
          <div className="flex items-center gap-1.5">
            <Input
              type="number"
              step="0.1"
              min="0"
              className="w-24"
              value={distance}
              placeholder="km"
              onChange={(e) => setDistance(e.target.value)}
            />
            <span className="text-sm text-muted-foreground">km</span>
          </div>
        </div>
      </div>
      <Field label="Goal time (optional)">
        <Input
          value={goalTime}
          placeholder="3:45:00"
          className={cn("tabular-nums", !validGoal && "border-danger focus-visible:ring-danger")}
          onChange={(e) => setGoalTime(e.target.value)}
        />
        {!validGoal && (
          <p className="mt-1 text-xs text-danger">Use h:mm:ss (e.g. 3:45:00) or m:ss (e.g. 22:30)</p>
        )}
      </Field>
      {error && <p className="text-sm text-danger">{error}</p>}
      <Button type="submit" disabled={!valid || busy}>
        {busy ? "Saving…" : "Add race"}
      </Button>
      <p className="text-xs text-muted-foreground">
        Races on your Garmin calendar import automatically on sync.
      </p>
    </form>
  );
}

// --- Step 5: interactive mini-map ---

interface MapSpot {
  id: string;
  label: string;
  icon: LucideIcon;
  line: string;
}

const MAP_SPOTS: MapSpot[] = [
  { id: "today", label: "Today", icon: Sun, line: "Your readiness score, today's run — and the why behind it." },
  { id: "week", label: "Week", icon: CalendarDays, line: "The rolling 7-day plan; push any run to your watch." },
  { id: "trends", label: "Trends", icon: TrendingUp, line: "Your fitness over time — recovery, load, and progress." },
  { id: "more", label: "More", icon: MoreHorizontal, line: "Races, activities, and settings live here." },
  { id: "chat", label: "Chat bubble", icon: MessageSquare, line: "Your coach, anywhere in the app. Plan changes always wait for your approval." },
];

function MiniMap() {
  const [active, setActive] = React.useState("today");
  const spot = MAP_SPOTS.find((s) => s.id === active)!;

  const tabSpots = MAP_SPOTS.slice(0, 4);

  return (
    <div>
      <div className="mx-auto w-full max-w-[240px] rounded-[1.75rem] border-2 border-border bg-card p-2 shadow-sm">
        <div className="relative overflow-hidden rounded-[1.25rem] bg-muted/50">
          {/* stylized page content */}
          <div className="space-y-2 p-3 pb-16">
            <div className="h-2 w-16 rounded-full bg-muted-foreground/25" />
            <div className="flex items-center gap-2 rounded-xl bg-background p-2.5">
              <div className="h-8 w-8 rounded-full border-[3px] border-accent/60" />
              <div className="flex-1 space-y-1.5">
                <div className="h-1.5 w-3/4 rounded-full bg-muted-foreground/25" />
                <div className="h-1.5 w-1/2 rounded-full bg-muted-foreground/15" />
              </div>
            </div>
            <div className="space-y-1.5 rounded-xl bg-background p-2.5">
              <div className="h-1.5 w-2/3 rounded-full bg-muted-foreground/25" />
              <div className="h-1.5 w-5/6 rounded-full bg-muted-foreground/15" />
              <div className="h-1.5 w-1/3 rounded-full bg-muted-foreground/15" />
            </div>
          </div>

          {/* chat bubble */}
          <button
            type="button"
            aria-label="Chat bubble"
            onClick={() => setActive("chat")}
            onMouseEnter={() => setActive("chat")}
            className={cn(
              "absolute bottom-12 right-2.5 flex h-9 w-9 items-center justify-center rounded-full bg-accent text-accent-foreground shadow-md transition-transform",
              active === "chat" && "scale-110 ring-2 ring-accent/50 ring-offset-2 ring-offset-muted",
            )}
          >
            <MessageSquare className="h-4 w-4" />
          </button>

          {/* tab bar */}
          <div className="absolute inset-x-0 bottom-0 flex border-t border-border bg-card/90 backdrop-blur">
            {tabSpots.map(({ id, label, icon: Icon }) => (
              <button
                key={id}
                type="button"
                aria-label={label}
                onClick={() => setActive(id)}
                onMouseEnter={() => setActive(id)}
                className={cn(
                  "flex flex-1 flex-col items-center gap-0.5 py-2 text-[9px] font-medium transition-colors",
                  active === id ? "rounded-lg bg-accent/10 text-accent" : "text-muted-foreground",
                )}
              >
                <Icon className="h-3.5 w-3.5" fill={active === id ? "currentColor" : "none"} />
                {label.split(" ")[0]}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="mx-auto mt-4 min-h-[4.5rem] max-w-sm rounded-xl bg-accent/10 px-4 py-3 text-center">
        <p className="text-sm font-semibold text-accent">{spot.label}</p>
        <p className="mt-0.5 text-sm leading-relaxed">{spot.line}</p>
      </div>
    </div>
  );
}

// --- The wizard ---

function WelcomeWizard() {
  const router = useRouter();
  const params = useSearchParams();
  const replay = params.get("replay") === "1";
  const deepStep = Number(params.get("step"));
  const initialStep =
    Number.isInteger(deepStep) && deepStep >= 1 && deepStep <= STEP_COUNT ? deepStep - 1 : 0;

  const [step, setStep] = React.useState(initialStep);
  const [loading, setLoading] = React.useState(true);
  const [me, setMe] = React.useState<UserInfo | null>(null);
  const [settings, setSettings] = React.useState<Settings | null>(null);
  const [races, setRaces] = React.useState<Race[] | null>(null);

  // step 1
  const [name, setName] = React.useState("");
  const [nameError, setNameError] = React.useState<string | null>(null);
  const [savingName, setSavingName] = React.useState(false);
  // step 3
  const [styleError, setStyleError] = React.useState<string | null>(null);
  // Guards out-of-order PUT responses when the user re-picks quickly.
  const styleSeqRef = React.useRef(0);
  // step 5
  const [finishing, setFinishing] = React.useState(false);

  React.useEffect(() => {
    let cancelled = false;
    (async () => {
      const [user, s, r] = await Promise.all([
        safe(api.authMe()),
        safe(api.getSettings()),
        safe(api.races()),
      ]);
      if (cancelled) return;
      setMe(user);
      setSettings(s);
      setRaces(r);
      if (user) setName(user.display_name);
      setLoading(false);
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const next = () => setStep((s) => Math.min(STEP_COUNT - 1, s + 1));
  const back = () => setStep((s) => Math.max(0, s - 1));

  const saveName = async () => {
    const trimmed = name.trim();
    if (trimmed.length < 1 || trimmed.length > 40) {
      setNameError("Pick a name between 1 and 40 characters.");
      return;
    }
    setSavingName(true);
    setNameError(null);
    try {
      const user = await api.updateProfile(trimmed);
      setMe(user);
      next();
    } catch (err) {
      setNameError(
        err instanceof ApiError && err.status === 422
          ? "Pick a name between 1 and 40 characters."
          : "Couldn't save your name — try again in a moment.",
      );
    } finally {
      setSavingName(false);
    }
  };

  // Optimistic: the card highlights instantly and the PUT runs in the
  // background; on failure the selection reverts with an inline error.
  // Cards are never disabled while saving.
  const pickStyle = async (style: Settings["coach_style"]) => {
    if (!settings || settings.coach_style === style) return;
    const previous = settings.coach_style;
    const seq = ++styleSeqRef.current;
    setSettings({ ...settings, coach_style: style });
    setStyleError(null);
    try {
      const saved = await api.putSettings({ ...settings, coach_style: style });
      // PUT returns the same shape as GET; merge defensively, latest pick wins.
      if (seq === styleSeqRef.current && saved) {
        setSettings((s) => (s ? { ...s, ...saved } : saved));
      }
    } catch {
      if (seq === styleSeqRef.current) {
        setSettings((s) => (s ? { ...s, coach_style: previous } : s));
        setStyleError("Couldn't save your coach choice — try again in a moment.");
      }
    }
  };

  const finish = async () => {
    setFinishing(true);
    if (!replay) {
      try {
        // Refetch at write time so a concurrent settings edit isn't clobbered.
        const current = await api.getSettings();
        if (!current.tutorial_done) {
          await api.putSettings({ ...current, tutorial_done: true });
        }
      } catch {
        // Non-fatal: the "/" redirect will simply bring the wizard back.
      }
    }
    router.replace("/");
  };

  const stepContent = () => {
    if (loading) {
      return (
        <div className="space-y-4">
          <Skeleton className="h-8 w-2/3 rounded-lg" />
          <Skeleton className="h-40 rounded-2xl" />
        </div>
      );
    }

    switch (step) {
      case 0:
        return (
          <div>
            <StepHeading
              title="Welcome to Idaten"
              subtitle="This app syncs your Garmin nightly and keeps a rolling 7-day plan pointed at your race. First things first — what should your coach call you?"
            />
            <form
              onSubmit={(e) => {
                e.preventDefault();
                void saveName();
              }}
              className="space-y-2"
            >
              <Field label="Your name">
                <Input
                  autoFocus
                  value={name}
                  maxLength={40}
                  onChange={(e) => setName(e.target.value)}
                />
              </Field>
              {nameError && <p className="text-sm text-danger">{nameError}</p>}
            </form>
          </div>
        );
      case 1:
        return (
          <div>
            <StepHeading
              title="Connect Garmin"
              subtitle="Your runs, sleep, and recovery power everything the coach does."
            />
            <div className="space-y-4">
              {me ? (
                <ConnectGarminCard
                  me={me}
                  onConnected={() =>
                    setMe((u) => (u ? { ...u, garmin_connected: true } : u))
                  }
                />
              ) : (
                <Skeleton className="h-48 rounded-2xl" />
              )}
              {me?.garmin_connected && <OnboardingBanner />}
            </div>
          </div>
        );
      case 2:
        return (
          <div>
            <StepHeading
              title="Choose your coach"
              subtitle="Personas change tone and workout flavor — never safety judgment."
            />
            <div className="flex flex-col gap-3 sm:flex-row sm:items-stretch">
              {PERSONAS.map((persona) => (
                <PersonaCard
                  key={persona.style}
                  persona={persona}
                  variant="full"
                  selected={settings?.coach_style === persona.style}
                  disabled={!settings}
                  onSelect={() => void pickStyle(persona.style)}
                />
              ))}
            </div>
            {styleError && <p className="mt-3 text-sm text-danger">{styleError}</p>}
          </div>
        );
      case 3:
        return (
          <div>
            <StepHeading
              title="Your race"
              subtitle="Give the plan a target — you can always add or change races later."
            />
            <RaceStep races={races} onAdded={(race) => setRaces([...(races ?? []), race])} />
          </div>
        );
      default:
        return (
          <div>
            <StepHeading
              title="Find your way around"
              subtitle="Tap anything on the mini-map to see what lives there."
            />
            <MiniMap />
          </div>
        );
    }
  };

  // Footer controls per step: 2 (Garmin) and 4 (race) are skippable — but the
  // Skip button is pointless once the step is already satisfied.
  const skippable =
    (step === 1 && !me?.garmin_connected) ||
    (step === 3 && !(races && races.length > 0));
  const last = step === STEP_COUNT - 1;

  return (
    <div className="flex min-h-dvh flex-col bg-background">
      <header className="mx-auto flex w-full max-w-lg items-center justify-between px-5 pb-2 pt-[max(1.25rem,env(safe-area-inset-top))]">
        <div
          className="flex items-center gap-1.5"
          aria-label={`Step ${step + 1} of ${STEP_COUNT}`}
        >
          {Array.from({ length: STEP_COUNT }).map((_, i) => (
            <span
              key={i}
              className={cn(
                "h-1.5 rounded-full transition-all",
                i === step ? "w-5 bg-accent" : "w-1.5 bg-muted-foreground/30",
              )}
            />
          ))}
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs tabular-nums text-muted-foreground">
            {step + 1} / {STEP_COUNT}
          </span>
          {replay && (
            <button
              type="button"
              aria-label="Close tutorial"
              onClick={() => router.push("/")}
              className="rounded-lg p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground"
            >
              <X className="h-4 w-4" />
            </button>
          )}
        </div>
      </header>

      <main className="mx-auto w-full max-w-lg flex-1 px-5 py-4">{stepContent()}</main>

      <footer className="sticky bottom-0 border-t border-border bg-background/95 pb-[max(1rem,env(safe-area-inset-bottom))] backdrop-blur">
        <div className="mx-auto flex w-full max-w-lg items-center justify-between gap-2 px-5 pt-4">
          <Button
            variant="ghost"
            onClick={back}
            disabled={step === 0 || loading}
            className={cn(step === 0 && "invisible")}
          >
            <ChevronLeft className="h-4 w-4" />
            Back
          </Button>
          <div className="flex items-center gap-2">
            {(skippable || (replay && !last)) && (
              <Button variant="ghost" onClick={next} disabled={loading} className="text-muted-foreground">
                {step === 1 ? "I'll do this later" : "Skip"}
              </Button>
            )}
            {last ? (
              <Button onClick={() => void finish()} disabled={loading || finishing}>
                {finishing ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <>
                    <Check className="h-4 w-4" />
                    Go to Today
                  </>
                )}
              </Button>
            ) : step === 0 ? (
              <Button onClick={() => void saveName()} disabled={loading || savingName}>
                {savingName ? "Saving…" : "Next"}
                <ChevronRight className="h-4 w-4" />
              </Button>
            ) : (
              <Button onClick={next} disabled={loading}>
                Next
                <ChevronRight className="h-4 w-4" />
              </Button>
            )}
          </div>
        </div>
      </footer>
    </div>
  );
}

export default function WelcomePage() {
  return (
    // useSearchParams requires a Suspense boundary during prerender.
    <React.Suspense fallback={null}>
      <WelcomeWizard />
    </React.Suspense>
  );
}
