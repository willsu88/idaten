"use client";

// Data-only Garmin sync (POST /api/sync pulls + enriches; the plan does NOT
// regenerate) — copy must never imply the plan updates. On mount the button
// checks GET /api/sync/status and, if a sync is already running server-side
// (started on another page or in another tab), resumes its spinner + polling.

import * as React from "react";
import { RefreshCw } from "lucide-react";
import type { SyncStatus } from "@/lib/types";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";
import { cn } from "@/lib/utils";

export function SyncButton({
  onSynced,
  compact = false,
}: {
  onSynced?: () => void;
  // Icon-only, for the page-header title row (beside the theme toggle).
  compact?: boolean;
}) {
  const [syncing, setSyncing] = React.useState(false);
  // Ref mirror of `syncing` so async callbacks read the current value.
  const syncingRef = React.useRef(false);
  const mountedRef = React.useRef(true);
  const { toast } = useToast();

  React.useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const begin = () => {
    syncingRef.current = true;
    setSyncing(true);
  };
  const end = () => {
    syncingRef.current = false;
    if (mountedRef.current) setSyncing(false);
  };

  // Poll GET /api/sync/status until running is false (or we give up after
  // ~2 min), then toast the outcome. Stops quietly if the button unmounted.
  const watchUntilDone = async () => {
    let status: SyncStatus | null = null;
    for (let i = 0; i < 60 && mountedRef.current; i++) {
      await new Promise((r) => setTimeout(r, 2000));
      try {
        const s = await api.syncStatus();
        if (!s.running) {
          status = s;
          break;
        }
      } catch {
        // backend hiccup while syncing; keep polling
      }
    }
    end();
    if (!mountedRef.current) return;
    if (status?.last_status === "error") {
      toast(status.last_detail ?? "Sync failed", "error");
    } else {
      toast("Data synced");
    }
    onSynced?.();
  };

  // Resume from server state: a sync started elsewhere still shows here.
  React.useEffect(() => {
    api
      .syncStatus()
      .then((status) => {
        if (status.running && !syncingRef.current && mountedRef.current) {
          begin();
          void watchUntilDone();
        }
      })
      .catch(() => {});
    // Mount-only check; watchUntilDone reads fresh state via refs.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleSync = async () => {
    if (syncingRef.current) return;
    begin();
    try {
      await api.sync();
    } catch {
      end();
      toast("Sync failed — is the backend running?", "error");
      return;
    }
    await watchUntilDone();
  };

  if (compact) {
    return (
      <Button
        variant="ghost"
        size="icon"
        onClick={handleSync}
        disabled={syncing}
        aria-label={syncing ? "Syncing…" : "Sync Garmin data"}
      >
        <RefreshCw className={cn("h-4 w-4", syncing && "animate-spin")} />
      </Button>
    );
  }
  return (
    <Button variant="outline" size="sm" onClick={handleSync} disabled={syncing}>
      <RefreshCw className={cn("h-3.5 w-3.5", syncing && "animate-spin")} />
      {syncing ? "Syncing…" : "Sync"}
    </Button>
  );
}
