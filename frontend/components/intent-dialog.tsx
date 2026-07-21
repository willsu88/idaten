"use client";

import * as React from "react";
import { Bike, X } from "lucide-react";
import type { DayIntent } from "@/lib/types";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Dialog, DialogDescription, DialogFooter, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { useToast } from "@/components/ui/toast";
import { cn, formatDay, formatDuration } from "@/lib/utils";

const SPORT_PRESETS = ["hiking", "surfing", "freediving", "cycling", "climbing"] as const;

type Effort = "" | "easy" | "moderate" | "hard";

/**
 * Chip shown on day cards when a day intent (other sport) is set.
 * Deliberately styled differently from workout-type badges: dashed emerald pill.
 */
export function IntentChip({
  intent,
  onRemoved,
}: {
  intent: DayIntent;
  onRemoved?: () => void;
}) {
  const [busy, setBusy] = React.useState(false);
  const { toast } = useToast();

  const remove = async () => {
    setBusy(true);
    try {
      await api.deleteIntent(intent.date);
      toast("Day intent removed");
      onRemoved?.();
    } catch {
      toast("Couldn't remove intent — is the backend running?", "error");
    } finally {
      setBusy(false);
    }
  };

  const duration = formatDuration(intent.duration_min);

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border border-dashed border-emerald-500/50",
        "bg-emerald-500/10 py-0.5 pl-2.5 pr-1 text-xs font-medium text-emerald-600 dark:text-emerald-400",
      )}
    >
      <span className="capitalize">{intent.sport}</span>
      {duration && <span className="font-normal opacity-80">· {duration}</span>}
      <button
        type="button"
        onClick={remove}
        disabled={busy}
        aria-label={`Remove ${intent.sport} on ${intent.date}`}
        title="Remove"
        className="rounded-full p-0.5 opacity-70 transition-colors hover:bg-emerald-500/15 hover:opacity-100 disabled:opacity-40"
      >
        <X className="h-3 w-3" />
      </button>
    </span>
  );
}

export function IntentDialog({
  date,
  intent,
  open,
  onOpenChange,
  onSaved,
}: {
  date: string;
  intent?: DayIntent | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSaved?: () => void;
}) {
  const [sport, setSport] = React.useState("");
  const [durationMin, setDurationMin] = React.useState("");
  const [effort, setEffort] = React.useState<Effort>("");
  const [saving, setSaving] = React.useState(false);
  const { toast } = useToast();

  // Re-seed the form each time the dialog opens.
  React.useEffect(() => {
    if (!open) return;
    setSport(intent?.sport ?? "");
    setDurationMin(intent?.duration_min != null ? String(intent.duration_min) : "");
    setEffort(intent?.effort ?? "");
  }, [open, intent]);

  const save = async () => {
    const trimmed = sport.trim();
    if (!trimmed) return;
    setSaving(true);
    try {
      const duration = Number(durationMin);
      await api.putIntent(date, {
        sport: trimmed,
        ...(durationMin !== "" && Number.isFinite(duration) && duration > 0
          ? { duration_min: Math.round(duration) }
          : {}),
        ...(effort ? { effort } : {}),
      });
      toast(`${trimmed} set for ${date}`);
      onOpenChange(false);
      onSaved?.();
    } catch {
      toast("Couldn't save intent — is the backend running?", "error");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogTitle>Other sport</DialogTitle>
      <DialogDescription>
        Doing something else on {formatDay(date)}? The coach will plan around it — no run will be
        scheduled that day.
      </DialogDescription>
      <div className="mt-4 space-y-4">
        <div>
          <span className="mb-1.5 block text-sm font-medium">Sport</span>
          <div className="mb-2 flex flex-wrap gap-1.5">
            {SPORT_PRESETS.map((preset) => (
              <button
                key={preset}
                type="button"
                onClick={() => setSport(preset)}
                className={cn(
                  "rounded-full border px-3 py-1 text-xs font-medium capitalize transition-colors",
                  sport === preset
                    ? "border-emerald-500/60 bg-emerald-500/15 text-emerald-600 dark:text-emerald-400"
                    : "border-border text-muted-foreground hover:bg-muted",
                )}
              >
                {preset}
              </button>
            ))}
          </div>
          <Input
            value={sport}
            placeholder="Or type any sport…"
            onChange={(e) => setSport(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                save();
              }
            }}
          />
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="block">
            <span className="mb-1.5 block text-sm font-medium">Duration (min, optional)</span>
            <Input
              type="number"
              min="0"
              step="5"
              value={durationMin}
              placeholder="90"
              onChange={(e) => setDurationMin(e.target.value)}
            />
          </label>
          <label className="block">
            <span className="mb-1.5 block text-sm font-medium">Effort (optional)</span>
            <Select value={effort} onChange={(e) => setEffort(e.target.value as Effort)}>
              <option value="">—</option>
              <option value="easy">Easy</option>
              <option value="moderate">Moderate</option>
              <option value="hard">Hard</option>
            </Select>
          </label>
        </div>
      </div>
      <DialogFooter>
        <Button variant="outline" onClick={() => onOpenChange(false)}>
          Cancel
        </Button>
        <Button onClick={save} disabled={saving || !sport.trim()}>
          {saving ? "Saving…" : intent ? "Update day" : "Set day"}
        </Button>
      </DialogFooter>
    </Dialog>
  );
}

/** Small "Other sport" quick action that opens the intent dialog. */
export function OtherSportButton({
  date,
  intent,
  onSaved,
  size = "default",
  className,
}: {
  date: string;
  intent?: DayIntent | null;
  onSaved?: () => void;
  size?: "default" | "sm";
  className?: string;
}) {
  const [open, setOpen] = React.useState(false);
  return (
    <>
      <Button variant="ghost" size={size} onClick={() => setOpen(true)} className={className}>
        <Bike className={size === "sm" ? "h-3.5 w-3.5" : "h-4 w-4"} />
        Other sport
      </Button>
      <IntentDialog
        date={date}
        intent={intent}
        open={open}
        onOpenChange={setOpen}
        onSaved={onSaved}
      />
    </>
  );
}
