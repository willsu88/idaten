"use client";

import * as React from "react";
import { RefreshCw } from "lucide-react";
import type { GearItem, GearSuggestion } from "@/lib/types";
import { api, safe } from "@/lib/api";
import { cn } from "@/lib/utils";
import { GearShoeCard, GearSuggestionBanner } from "@/components/gear-shoe-card";
import { PageHeader } from "@/components/page-header";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";

export default function GearPage() {
  const { toast } = useToast();
  const [gear, setGear] = React.useState<GearItem[] | null>(null);
  const [suggestions, setSuggestions] = React.useState<GearSuggestion[]>([]);
  const [refreshing, setRefreshing] = React.useState(false);

  const load = React.useCallback(() => {
    safe(api.gear()).then(setGear);
    safe(api.gearSuggestions()).then((s) => setSuggestions(s ?? []));
  }, []);

  React.useEffect(() => {
    load();
  }, [load]);

  // First visit before any sync: the mirror is empty — fill it from Garmin.
  const emptyMirror = gear !== null && gear.length === 0;
  React.useEffect(() => {
    if (emptyMirror && !refreshing) void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [emptyMirror]);

  const refresh = async () => {
    setRefreshing(true);
    try {
      setGear(await api.gearRefresh());
      safe(api.gearSuggestions()).then((s) => setSuggestions(s ?? []));
    } catch (e) {
      toast(e instanceof Error ? e.message : "Garmin refresh failed", "error");
    } finally {
      setRefreshing(false);
    }
  };

  const shoes = (gear ?? []).filter((g) => g.gear_type === "Shoes");
  const active = shoes.filter((g) => g.status === "active");
  const retired = shoes.filter((g) => g.status !== "active");
  const loading = gear === null || (emptyMirror && refreshing);

  return (
    <div>
      <PageHeader
        title="Gear"
        subtitle="Your shoes, their mileage, and which runs they carry"
        titleActions={
          <button
            type="button"
            onClick={() => void refresh()}
            disabled={refreshing}
            aria-label="Refresh from Garmin"
            title="Refresh from Garmin"
            className="flex h-9 w-9 items-center justify-center rounded-xl text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:opacity-50"
          >
            <RefreshCw className={cn("h-4 w-4", refreshing && "animate-spin")} />
          </button>
        }
      />

      <div className="space-y-5">
        {suggestions.length > 0 && (
          <div className="space-y-2">
            {suggestions.map((s) => (
              <GearSuggestionBanner key={s.activity_id} suggestion={s} onDone={load} />
            ))}
          </div>
        )}

        {loading ? (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-56 rounded-2xl" />
            ))}
          </div>
        ) : shoes.length === 0 ? (
          <Card>
            <CardContent className="p-6 text-sm text-muted-foreground">
              No shoes found on your Garmin account. Add your shoes in Garmin
              Connect (Gear) and refresh — mileage and per-run tracking pick up
              from there.
            </CardContent>
          </Card>
        ) : (
          <>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {active.map((g) => (
                <GearShoeCard key={g.uuid} shoe={g} onMutated={load} />
              ))}
            </div>
            {retired.length > 0 && (
              <>
                <p className="pt-2 text-xs font-medium uppercase tracking-wider text-muted-foreground">
                  Retired
                </p>
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
                  {retired.map((g) => (
                    <GearShoeCard key={g.uuid} shoe={g} onMutated={load} />
                  ))}
                </div>
              </>
            )}
          </>
        )}
      </div>
    </div>
  );
}
