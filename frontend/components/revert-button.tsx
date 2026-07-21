"use client";

// Editor mode: replace one day's Idaten edit with the original Garmin Coach
// workout. Clears Idaten's pushed watch workout so the native Garmin workout
// stands (no re-push). Only render when the day is `revertible`.

import * as React from "react";
import { RotateCcw } from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";

export function RevertButton({
  date,
  onReverted,
  size = "default",
  className,
}: {
  date: string;
  onReverted?: () => void;
  size?: "default" | "sm";
  className?: string;
}) {
  const [busy, setBusy] = React.useState(false);
  const { toast } = useToast();

  const revert = async () => {
    setBusy(true);
    try {
      const res = await api.revertToGarmin({ date });
      toast(
        res.reverted.length > 0
          ? "Restored the original Garmin Coach workout"
          : "No Garmin Coach workout to restore for this day",
      );
      onReverted?.();
    } catch {
      toast("Revert failed — is the backend running?", "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Button variant="ghost" size={size} onClick={revert} disabled={busy} className={className}>
      <RotateCcw className="h-3.5 w-3.5" />
      {busy ? "Restoring…" : "Replace with Garmin Coach"}
    </Button>
  );
}
