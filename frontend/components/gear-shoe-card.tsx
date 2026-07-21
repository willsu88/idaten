"use client";

import * as React from "react";
import { ArrowRight, Camera, Footprints, MoreHorizontal, Trash2, X } from "lucide-react";
import type { GearItem, GearSuggestion } from "@/lib/types";
import { api } from "@/lib/api";
import { brandColor, brandInitials, bucketLabel } from "@/lib/gear";
import { cn } from "@/lib/utils";
import { Card, CardContent } from "@/components/ui/card";
import { DropdownItem, DropdownMenu } from "@/components/ui/dropdown-menu";
import { useToast } from "@/components/ui/toast";

/**
 * The shoe's face: the uploaded photo when there is one, otherwise a generated
 * card (brand accent + wordmark initials + model name). The generated card is
 * the open-source default — the repo ships no imagery.
 */
export function ShoeVisual({ shoe, className }: { shoe: GearItem; className?: string }) {
  // Cache-bust on upload/remove so <img> reflects the change immediately.
  const [version, setVersion] = React.useState(0);
  React.useEffect(() => setVersion((v) => v + 1), [shoe.has_image]);

  if (shoe.has_image) {
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src={`/api/gear/${shoe.uuid}/image?v=${version}`}
        alt={shoe.name}
        className={cn("h-full w-full object-cover", className)}
      />
    );
  }
  const color = brandColor(shoe.name);
  return (
    <div
      className={cn("relative flex h-full w-full items-center justify-center", className)}
      style={{ background: `linear-gradient(135deg, ${color}, ${color}c0)` }}
    >
      <span className="select-none text-5xl font-black tracking-tight text-white/25">
        {brandInitials(shoe.name)}
      </span>
      <Footprints className="absolute bottom-2.5 right-3 h-4 w-4 text-white/40" />
    </div>
  );
}

function kmLabel(km: number): string {
  return km >= 100 ? String(Math.round(km)) : km.toFixed(1);
}

export function GearShoeCard({
  shoe,
  onMutated,
}: {
  shoe: GearItem;
  onMutated: () => void;
}) {
  const { toast } = useToast();
  const fileRef = React.useRef<HTMLInputElement>(null);
  const [busy, setBusy] = React.useState(false);

  const upload = async (file: File) => {
    setBusy(true);
    try {
      await api.uploadGearImage(shoe.uuid, file);
      onMutated();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Upload failed", "error");
    } finally {
      setBusy(false);
    }
  };

  const removeImage = async () => {
    try {
      await api.deleteGearImage(shoe.uuid);
      onMutated();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Couldn't remove the photo", "error");
    }
  };

  const wornPct =
    shoe.limit_km != null && shoe.limit_km > 0
      ? Math.min(100, (shoe.distance_km / shoe.limit_km) * 100)
      : null;
  const retired = shoe.status !== "active";

  return (
    <Card className={cn("overflow-hidden", retired && "opacity-60")}>
      <div className="relative aspect-[5/2]">
        <ShoeVisual shoe={shoe} />
        <div className="absolute right-2 top-2">
          <DropdownMenu
            trigger={
              <span className="flex h-8 w-8 items-center justify-center rounded-full bg-black/35 text-white backdrop-blur-sm hover:bg-black/50">
                <MoreHorizontal className="h-4 w-4" />
              </span>
            }
          >
            <DropdownItem onClick={() => fileRef.current?.click()} disabled={busy}>
              <Camera className="h-4 w-4" />
              {shoe.has_image ? "Replace photo" : "Add photo"}
            </DropdownItem>
            {shoe.has_image && (
              <DropdownItem onClick={removeImage}>
                <Trash2 className="h-4 w-4" />
                Remove photo
              </DropdownItem>
            )}
          </DropdownMenu>
        </div>
        <input
          ref={fileRef}
          type="file"
          accept="image/jpeg,image/png,image/webp"
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) void upload(f);
            e.target.value = "";
          }}
        />
      </div>
      <CardContent className="space-y-2.5 p-4">
        <div className="flex items-start justify-between gap-2">
          <p className="text-sm font-semibold leading-tight">{shoe.name}</p>
          {retired && (
            <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] font-medium text-muted-foreground">
              retired
            </span>
          )}
        </div>
        <p className="text-xs text-muted-foreground">
          <span className="font-semibold text-foreground">{kmLabel(shoe.distance_km)} km</span>
          {shoe.limit_km != null && ` of ${shoe.limit_km}`}
          {" · "}
          {shoe.total_activities} {shoe.total_activities === 1 ? "run" : "runs"}
          {shoe.date_begin && ` · since ${shoe.date_begin.slice(0, 7)}`}
        </p>
        {wornPct != null && (
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
            <div
              className={cn(
                "h-full rounded-full",
                wornPct >= 90 ? "bg-red-500" : wornPct >= 70 ? "bg-amber-500" : "bg-accent",
              )}
              style={{ width: `${wornPct}%` }}
            />
          </div>
        )}
      </CardContent>
    </Card>
  );
}

/**
 * One-tap suggestion: "you usually wear X for this kind of run — switch?".
 * Never auto-applied; Dismiss is permanent for that activity.
 */
export function GearSuggestionBanner({
  suggestion,
  onDone,
  compact = false,
}: {
  suggestion: GearSuggestion;
  /** Called after accept (true) or dismiss (false) so the parent can refresh. */
  onDone: (accepted: boolean) => void;
  compact?: boolean;
}) {
  const { toast } = useToast();
  const [busy, setBusy] = React.useState(false);

  const accept = async () => {
    setBusy(true);
    try {
      await api.setActivityGear(suggestion.activity_id, suggestion.suggested.uuid);
      toast(`Switched to ${suggestion.suggested.name}`);
      onDone(true);
    } catch (e) {
      toast(e instanceof Error ? e.message : "Garmin update failed", "error");
      setBusy(false);
    }
  };

  const dismiss = async () => {
    setBusy(true);
    try {
      await api.dismissGearSuggestion(suggestion.activity_id);
      onDone(false);
    } catch {
      setBusy(false);
    }
  };

  const pct = Math.round(suggestion.confidence * 100);
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-2xl border border-accent/30 bg-accent/5 px-4 py-3">
      <div className="min-w-0 flex-1 text-sm">
        {!compact && (
          <span className="text-muted-foreground">
            {suggestion.date} · {suggestion.activity_name}:{" "}
          </span>
        )}
        You wear the <span className="font-medium">{suggestion.suggested.name}</span> for{" "}
        {pct}% of {bucketLabel(suggestion)}, but this one is tagged{" "}
        <span className="font-medium">{suggestion.current.name ?? "no shoe"}</span>.
      </div>
      <div className="flex shrink-0 items-center gap-1.5">
        <button
          type="button"
          onClick={accept}
          disabled={busy}
          className="inline-flex min-h-8 items-center gap-1 rounded-lg bg-accent px-2.5 py-1 text-xs font-semibold text-accent-foreground hover:bg-accent/90 disabled:opacity-50"
        >
          <ArrowRight className="h-3.5 w-3.5" />
          Switch to {suggestion.suggested.name}
        </button>
        <button
          type="button"
          onClick={dismiss}
          disabled={busy}
          aria-label="Dismiss suggestion"
          className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-50"
        >
          <X className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}
