"use client";

import * as React from "react";
import { Send } from "lucide-react";
import type { PlanDay, ShareMember } from "@/lib/types";
import { api, safe } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { DropdownItem, DropdownMenu } from "@/components/ui/dropdown-menu";
import { useToast } from "@/components/ui/toast";

/** "Send to..." on a run workout: picks another household member and shares
 * the day as a snapshot (ADR 0022). Renders nothing when there is no one to
 * send to or the day is not a run. */
export function ShareWorkoutButton({
  workout,
  size = "default",
}: {
  workout: PlanDay;
  size?: "default" | "sm";
}) {
  const [members, setMembers] = React.useState<ShareMember[]>([]);
  const [busy, setBusy] = React.useState(false);
  const { toast } = useToast();

  React.useEffect(() => {
    let cancelled = false;
    void safe(api.shareMembers()).then((m) => {
      if (!cancelled && m) setMembers(m);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const shareable = !["rest", "cross_train"].includes(workout.workout_type);
  if (!shareable || members.length === 0) return null;

  const send = async (member: ShareMember) => {
    setBusy(true);
    try {
      await api.shareWorkout(member.id, workout.date);
      toast(`Sent to ${member.display_name} — they'll see it on their Today page`);
    } catch {
      toast("Send failed — is the backend running?", "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <DropdownMenu
      trigger={
        <Button size={size} variant="ghost" disabled={busy}>
          <Send className="h-4 w-4" />
          {busy ? "Sending…" : "Send to…"}
        </Button>
      }
    >
      {members.map((m) => (
        <DropdownItem key={m.id} onClick={() => send(m)}>
          {m.display_name}
        </DropdownItem>
      ))}
    </DropdownMenu>
  );
}
