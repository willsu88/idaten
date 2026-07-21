"use client";

import * as React from "react";
import { Map as MapIcon, Pencil, Plus, Star, Trash2 } from "lucide-react";
import type { Race } from "@/lib/types";
import { api } from "@/lib/api";
import { cn, formatDay } from "@/lib/utils";
import { RouteMap } from "@/components/activity-map";
import { CourseDialog } from "@/components/course-dialog";
import {
  countdownLabel,
  distanceLabel,
  GarminPredictionChip,
  PredictionDetail,
} from "@/components/race-chip";
import { SHOW_RACE_PREDICTION } from "@/lib/flags";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogFooter, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";

const DISTANCE_PRESETS = [
  { label: "5k", km: 5 },
  { label: "10k", km: 10 },
  { label: "Half", km: 21.1 },
  { label: "Marathon", km: 42.2 },
] as const;

// "3:45:00" (h:mm:ss) or "22:30" (m:ss)
const GOAL_TIME_RE = /^\d{1,2}:[0-5]\d(:[0-5]\d)?$/;

interface RaceForm {
  name: string;
  date: string;
  distance_km: string;
  goal_time: string;
}

const EMPTY_FORM: RaceForm = { name: "", date: "", distance_km: "", goal_time: "" };

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-sm font-medium">{label}</span>
      {children}
    </label>
  );
}

function RaceDialog({
  open,
  onOpenChange,
  race,
  onSaved,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  race: Race | null; // null = create
  onSaved: () => void;
}) {
  const [form, setForm] = React.useState<RaceForm>(EMPTY_FORM);
  const [saving, setSaving] = React.useState(false);
  const { toast } = useToast();

  React.useEffect(() => {
    if (!open) return;
    setForm(
      race
        ? {
            name: race.name,
            date: race.date,
            distance_km: String(race.distance_km),
            goal_time: race.goal_time,
          }
        : EMPTY_FORM,
    );
  }, [open, race]);

  const distanceKm = Number(form.distance_km);
  const validDistance = form.distance_km !== "" && Number.isFinite(distanceKm) && distanceKm > 0;
  const validGoalTime = GOAL_TIME_RE.test(form.goal_time.trim());
  const valid = form.name.trim() !== "" && form.date !== "" && validDistance && validGoalTime;

  const save = async () => {
    if (!valid) return;
    setSaving(true);
    const body = {
      name: form.name.trim(),
      date: form.date,
      distance_km: distanceKm,
      goal_time: form.goal_time.trim(),
    };
    try {
      if (race) {
        await api.updateRace(race.id, body);
        toast("Race updated");
      } else {
        await api.createRace(body);
        toast("Race added");
      }
      onOpenChange(false);
      onSaved();
    } catch {
      toast("Save failed — is the backend running?", "error");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogTitle>{race ? "Edit race" : "Add race"}</DialogTitle>
      <div className="mt-4 space-y-4">
        <Field label="Race name">
          <Input
            value={form.name}
            placeholder="Berlin Marathon"
            onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
          />
        </Field>
        <Field label="Date">
          <Input
            type="date"
            value={form.date}
            onChange={(e) => setForm((f) => ({ ...f, date: e.target.value }))}
          />
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
                onClick={() => setForm((f) => ({ ...f, distance_km: String(p.km) }))}
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
                value={form.distance_km}
                placeholder="km"
                onChange={(e) => setForm((f) => ({ ...f, distance_km: e.target.value }))}
              />
              <span className="text-sm text-muted-foreground">km</span>
            </div>
          </div>
        </div>
        <Field label="Goal time">
          <Input
            value={form.goal_time}
            placeholder="3:45:00"
            className={cn(
              "tabular-nums",
              form.goal_time !== "" && !validGoalTime && "border-danger focus-visible:ring-danger",
            )}
            onChange={(e) => setForm((f) => ({ ...f, goal_time: e.target.value }))}
          />
          {form.goal_time !== "" && !validGoalTime && (
            <p className="mt-1 text-xs text-danger">Use h:mm:ss (e.g. 3:45:00) or m:ss (e.g. 22:30)</p>
          )}
        </Field>
      </div>
      <DialogFooter>
        <Button variant="outline" onClick={() => onOpenChange(false)}>
          Cancel
        </Button>
        <Button onClick={save} disabled={!valid || saving}>
          {saving ? "Saving…" : race ? "Save race" : "Add race"}
        </Button>
      </DialogFooter>
    </Dialog>
  );
}

function RaceRow({
  race,
  onEdit,
  onAddEffort,
  onCourse,
  onChanged,
}: {
  race: Race;
  onEdit: () => void;
  onAddEffort: () => void;
  onCourse: () => void;
  onChanged: () => void;
}) {
  const [busy, setBusy] = React.useState(false);
  const { toast } = useToast();

  const act = async (fn: () => Promise<unknown>, okMessage: string) => {
    setBusy(true);
    try {
      await fn();
      toast(okMessage);
      onChanged();
    } catch {
      toast("Action failed — is the backend running?", "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    // Stacked on phones (name/date block full-width, prediction + actions on
    // their own row); `sm:contents` dissolves the groups into the old single-row
    // flex layout from sm up.
    <div className="flex flex-col gap-2 rounded-xl border border-border px-4 py-3 sm:flex-row sm:flex-wrap sm:items-center sm:gap-x-4 sm:gap-y-2">
      <div className="flex w-full items-center gap-3 sm:contents">
        <button
          type="button"
          title={race.is_primary ? "Primary race" : "Make primary"}
          aria-label={race.is_primary ? "Primary race" : "Make primary"}
          disabled={busy || race.is_primary}
          onClick={() => act(() => api.setPrimaryRace(race.id), `${race.name} is now your primary race`)}
          className={cn(
            "shrink-0 rounded-md p-1 transition-colors disabled:pointer-events-none",
            race.is_primary ? "text-warning" : "text-muted-foreground hover:bg-muted hover:text-foreground",
          )}
        >
          <Star className="h-4 w-4" fill={race.is_primary ? "currentColor" : "none"} />
        </button>

        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <p className="truncate text-sm font-semibold">{race.name}</p>
            {race.source === "garmin" && (
              <Badge variant="secondary" className="shrink-0">
                from Garmin
              </Badge>
            )}
          </div>
          <p className="text-xs text-muted-foreground">
            {formatDay(race.date)} ({countdownLabel(race.days_to_race)}) · {distanceLabel(race.distance_km)} ·
            goal <span className="tabular-nums">{race.goal_time}</span>
          </p>
        </div>
      </div>

      <div className="flex w-full items-start justify-between gap-3 sm:contents">
        {SHOW_RACE_PREDICTION ? (
          <PredictionDetail prediction={race.prediction} onAddEffort={onAddEffort} />
        ) : (
          <GarminPredictionChip prediction={race.prediction} />
        )}

        <div className="flex shrink-0 items-center gap-1">
          <Button
            variant="ghost"
            size="icon"
            aria-label={race.course ? "Edit course map" : "Add course map"}
            title={race.course ? "Edit course map" : "Add course map"}
            disabled={busy}
            className={cn(race.course && "text-accent hover:text-accent")}
            onClick={onCourse}
          >
            <MapIcon className="h-4 w-4" />
          </Button>
          <Button variant="ghost" size="icon" aria-label="Edit race" disabled={busy} onClick={onEdit}>
            <Pencil className="h-4 w-4" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            aria-label="Delete race"
            disabled={busy}
            className="text-muted-foreground hover:text-danger"
            onClick={() => act(() => api.deleteRace(race.id), "Race deleted")}
          >
            <Trash2 className="h-4 w-4" />
          </Button>
        </div>
      </div>

      {race.course && race.course.length >= 2 && (
        <RouteMap route={race.course} className="mt-1 h-44 w-full rounded-lg sm:h-56" />
      )}
    </div>
  );
}

export function RacesCard({ onMutated }: { onMutated?: () => void }) {
  const [races, setRaces] = React.useState<Race[] | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState(false);
  const [dialogOpen, setDialogOpen] = React.useState(false);
  const [editing, setEditing] = React.useState<Race | null>(null);
  const [courseRace, setCourseRace] = React.useState<Race | null>(null);

  const load = React.useCallback(async () => {
    try {
      setRaces(await api.races());
      setError(false);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, []);

  // Reload + notify the parent (e.g. the /races outlook) after any change.
  const changed = React.useCallback(() => {
    load();
    onMutated?.();
  }, [load, onMutated]);

  React.useEffect(() => {
    load();
  }, [load]);

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <div>
          <CardTitle>Races</CardTitle>
          <CardDescription>
            Upcoming races — the starred one is primary and drives your plan
          </CardDescription>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => {
            setEditing(null);
            setDialogOpen(true);
          }}
        >
          <Plus className="h-3.5 w-3.5" />
          Add race
        </Button>
      </CardHeader>
      <CardContent className="space-y-3">
        {loading ? (
          <>
            <Skeleton className="h-16 rounded-xl" />
            <Skeleton className="h-16 rounded-xl" />
          </>
        ) : error ? (
          <p className="text-sm text-muted-foreground">
            Couldn&apos;t load races — is the backend running?
          </p>
        ) : races == null || races.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No upcoming races yet — add one to give your plan a target.
          </p>
        ) : (
          races.map((race) => (
            <RaceRow
              key={race.id}
              race={race}
              onChanged={changed}
              onEdit={() => {
                setEditing(race);
                setDialogOpen(true);
              }}
              onAddEffort={() => {
                setEditing(null);
                setDialogOpen(true);
              }}
              onCourse={() => setCourseRace(race)}
            />
          ))
        )}
        <p className="pt-1 text-xs text-muted-foreground">
          Races you create in Garmin Connect appear here automatically; races created here are not
          sent back to Garmin.
        </p>
      </CardContent>

      <RaceDialog open={dialogOpen} onOpenChange={setDialogOpen} race={editing} onSaved={changed} />
      {courseRace && (
        <CourseDialog
          open
          onOpenChange={(o) => {
            if (!o) setCourseRace(null);
          }}
          race={courseRace}
          onSaved={changed}
        />
      )}
    </Card>
  );
}
