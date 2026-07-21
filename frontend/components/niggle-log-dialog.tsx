"use client";

import * as React from "react";
import { api } from "@/lib/api";
import { isoDate } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Dialog, DialogDescription, DialogFooter, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/components/ui/toast";

type Severity = "1" | "2" | "3";

/**
 * The UI fallback for reporting pain (chat is the primary door). Logging an
 * already-open body part updates that entry server-side, so re-submitting
 * never creates duplicates.
 */
export function NiggleLogDialog({
  open,
  onOpenChange,
  onSaved,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSaved?: () => void;
}) {
  const [bodyPart, setBodyPart] = React.useState("");
  const [severity, setSeverity] = React.useState<Severity>("1");
  const [note, setNote] = React.useState("");
  const [onsetDate, setOnsetDate] = React.useState("");
  const [saving, setSaving] = React.useState(false);
  const { toast } = useToast();

  // Re-seed the form each time the dialog opens.
  React.useEffect(() => {
    if (!open) return;
    setBodyPart("");
    setSeverity("1");
    setNote("");
    setOnsetDate("");
  }, [open]);

  const save = async () => {
    const trimmed = bodyPart.trim();
    if (!trimmed) return;
    setSaving(true);
    try {
      await api.createNiggle({
        body_part: trimmed,
        severity: Number(severity) as 1 | 2 | 3,
        ...(note.trim() ? { note: note.trim() } : {}),
        ...(onsetDate ? { onset_date: onsetDate } : {}),
      });
      toast("Logged - your coach will ease the plan around it");
      onOpenChange(false);
      onSaved?.();
    } catch {
      toast("Couldn't log it - try again in a moment.", "error");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogTitle>Log a niggle</DialogTitle>
      <DialogDescription>
        Something hurting? Your coach eases the plan around it until it clears.
      </DialogDescription>
      <div className="mt-4 space-y-4">
        <label className="block">
          <span className="mb-1.5 block text-sm font-medium">Where does it hurt?</span>
          <Input
            value={bodyPart}
            placeholder="left knee"
            autoFocus
            onChange={(e) => setBodyPart(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                save();
              }
            }}
          />
        </label>
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="block">
            <span className="mb-1.5 block text-sm font-medium">How bad?</span>
            <Select value={severity} onChange={(e) => setSeverity(e.target.value as Severity)}>
              <option value="1">Niggle - minor</option>
              <option value="2">Pain - protect it</option>
              <option value="3">Injury - can&apos;t train normally</option>
            </Select>
          </label>
          <label className="block">
            <span className="mb-1.5 block text-sm font-medium">When did it start? (optional)</span>
            <Input
              type="date"
              max={isoDate()}
              value={onsetDate}
              onChange={(e) => setOnsetDate(e.target.value)}
            />
          </label>
        </div>
        <label className="block">
          <span className="mb-1.5 block text-sm font-medium">Note (optional)</span>
          <Textarea
            value={note}
            placeholder="Only hurts on downhills…"
            onChange={(e) => setNote(e.target.value)}
          />
        </label>
      </div>
      <DialogFooter>
        <Button variant="outline" onClick={() => onOpenChange(false)}>
          Cancel
        </Button>
        <Button onClick={save} disabled={saving || !bodyPart.trim()}>
          {saving ? "Saving…" : "Log it"}
        </Button>
      </DialogFooter>
    </Dialog>
  );
}
