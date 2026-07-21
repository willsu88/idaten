"use client";

import * as React from "react";
import Link from "next/link";
import { Check, ChevronDown, Footprints } from "lucide-react";
import type { GearItem, GearSuggestion } from "@/lib/types";
import { api, safe } from "@/lib/api";
import { activeShoes, brandColor, shoeName } from "@/lib/gear";
import { GearSuggestionBanner } from "@/components/gear-shoe-card";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { DropdownItem, DropdownMenu } from "@/components/ui/dropdown-menu";
import { useToast } from "@/components/ui/toast";

function ShoeDot({ name }: { name: string }) {
  return (
    <span
      className="h-2.5 w-2.5 shrink-0 rounded-full"
      style={{ backgroundColor: brandColor(name) }}
    />
  );
}

/**
 * The shoe row on an activity: current shoe + one-tap dropdown to reassign
 * (writes through to Garmin), plus the predictor's suggestion when it has one
 * for this activity. Renders only for runs.
 */
export function GearSelectorCard({
  activityId,
  gearUuid,
  onChanged,
}: {
  activityId: number;
  gearUuid: string | null;
  /** Called with the new uuid after a successful swap. */
  onChanged: (uuid: string | null) => void;
}) {
  const { toast } = useToast();
  const [gear, setGear] = React.useState<GearItem[]>([]);
  const [suggestion, setSuggestion] = React.useState<GearSuggestion | null>(null);
  const [busy, setBusy] = React.useState(false);

  const loadSuggestion = React.useCallback(() => {
    safe(api.gearSuggestions()).then((all) =>
      setSuggestion(all?.find((s) => s.activity_id === activityId) ?? null),
    );
  }, [activityId]);

  React.useEffect(() => {
    safe(api.gear()).then((g) => setGear(g ?? []));
    loadSuggestion();
  }, [loadSuggestion]);

  const shoes = activeShoes(gear);
  const currentName = shoeName(gear, gearUuid);
  // A shoe recorded on the run but absent from the mirror (retired/renamed):
  // still show something rather than "No shoe".
  const label = currentName ?? (gearUuid ? "Unknown shoe" : "No shoe");

  const setShoe = async (uuid: string | null) => {
    if (uuid === gearUuid) return;
    setBusy(true);
    try {
      await api.setActivityGear(activityId, uuid);
      onChanged(uuid);
      toast(uuid ? `Switched to ${shoeName(gear, uuid)}` : "Shoe removed");
      loadSuggestion();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Garmin update failed", "error");
    } finally {
      setBusy(false);
    }
  };

  // Nothing useful to render until the mirror has shoes (first sync pending).
  if (shoes.length === 0 && !gearUuid) return null;

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2">
          <Footprints className="h-4 w-4 text-muted-foreground" />
          Shoes
        </CardTitle>
        <CardDescription>
          Changes here update Garmin too ·{" "}
          <Link href="/gear" className="underline-offset-2 hover:underline">
            all gear
          </Link>
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <DropdownMenu
          align="start"
          trigger={
            <span
              className={
                "inline-flex min-h-10 items-center gap-2 rounded-xl border border-border bg-card px-3 py-2 text-sm font-medium hover:bg-muted " +
                (busy ? "pointer-events-none opacity-50" : "")
              }
            >
              {currentName && <ShoeDot name={currentName} />}
              {label}
              <ChevronDown className="h-4 w-4 text-muted-foreground" />
            </span>
          }
        >
          {shoes.map((s) => (
            <DropdownItem key={s.uuid} onClick={() => void setShoe(s.uuid)} disabled={busy}>
              <ShoeDot name={s.name} />
              <span className="flex-1">{s.name}</span>
              {s.uuid === gearUuid && <Check className="h-4 w-4 text-accent" />}
            </DropdownItem>
          ))}
          {gearUuid && (
            <DropdownItem onClick={() => void setShoe(null)} disabled={busy}>
              <span className="h-2.5 w-2.5 shrink-0 rounded-full border border-border" />
              No shoe
            </DropdownItem>
          )}
        </DropdownMenu>

        {suggestion && (
          <GearSuggestionBanner
            suggestion={suggestion}
            compact
            onDone={(accepted) => {
              if (accepted) onChanged(suggestion.suggested.uuid);
              loadSuggestion();
            }}
          />
        )}
      </CardContent>
    </Card>
  );
}
