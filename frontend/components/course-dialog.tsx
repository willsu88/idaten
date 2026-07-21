"use client";

import * as React from "react";
import { Upload } from "lucide-react";
import type { CourseTrack, Race } from "@/lib/types";
import { api, ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import { RouteMap } from "@/components/activity-map";
import { Button } from "@/components/ui/button";
import { Dialog, DialogDescription, DialogFooter, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { useToast } from "@/components/ui/toast";

// btoa chokes on raw bytes above 0x7f unless fed char-by-char, and call stacks
// cap String.fromCharCode(...spread) - chunk it.
function toBase64(buf: ArrayBuffer): string {
  const bytes = new Uint8Array(buf);
  let bin = "";
  for (let i = 0; i < bytes.length; i += 0x8000) {
    bin += String.fromCharCode.apply(null, Array.from(bytes.subarray(i, i + 0x8000)));
  }
  return btoa(bin);
}

/** The track whose length best matches the race distance - usually the answer
 *  when a shared race map holds several courses (half/10K/4K). */
function bestMatch(tracks: CourseTrack[], raceKm: number): number {
  let best = 0;
  for (let i = 1; i < tracks.length; i++) {
    if (Math.abs(tracks[i].distance_km - raceKm) < Math.abs(tracks[best].distance_km - raceKm)) {
      best = i;
    }
  }
  return best;
}

export function CourseDialog({
  open,
  onOpenChange,
  race,
  onSaved,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  race: Race;
  onSaved: () => void;
}) {
  const [url, setUrl] = React.useState("");
  const [tracks, setTracks] = React.useState<CourseTrack[] | null>(null);
  const [selected, setSelected] = React.useState(0);
  const [loading, setLoading] = React.useState(false);
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const fileRef = React.useRef<HTMLInputElement>(null);
  const { toast } = useToast();

  React.useEffect(() => {
    if (!open) return;
    setUrl("");
    setTracks(null);
    setError(null);
  }, [open]);

  const preview = async (body: { url?: string; content_b64?: string }) => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.coursePreview(body);
      setTracks(res.tracks);
      setSelected(bestMatch(res.tracks, race.distance_km));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't load that course");
    } finally {
      setLoading(false);
    }
  };

  const onFile = async (file: File | undefined) => {
    if (!file) return;
    await preview({ content_b64: toBase64(await file.arrayBuffer()) });
    if (fileRef.current) fileRef.current.value = ""; // allow re-picking the same file
  };

  const save = async () => {
    if (!tracks) return;
    setSaving(true);
    try {
      await api.setRaceCourse(race.id, tracks[selected].points);
      toast("Course map saved");
      onOpenChange(false);
      onSaved();
    } catch {
      toast("Save failed — is the backend running?", "error");
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    setSaving(true);
    try {
      await api.clearRaceCourse(race.id);
      toast("Course map removed");
      onOpenChange(false);
      onSaved();
    } catch {
      toast("Remove failed — is the backend running?", "error");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogTitle>Course map</DialogTitle>
      <DialogDescription>
        Paste a shared Google My Maps link, or upload the course as a KML, KMZ or GPX file.
      </DialogDescription>

      <div className="mt-4 space-y-4">
        <div className="flex gap-2">
          <Input
            value={url}
            placeholder="https://www.google.com/maps/d/viewer?mid=…"
            onChange={(e) => setUrl(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && url.trim()) void preview({ url: url.trim() });
            }}
          />
          <Button
            variant="outline"
            disabled={!url.trim() || loading}
            onClick={() => preview({ url: url.trim() })}
          >
            {loading ? "Loading…" : "Load"}
          </Button>
        </div>

        <div className="flex items-center gap-3">
          <div className="h-px flex-1 bg-border" />
          <span className="text-xs text-muted-foreground">or</span>
          <div className="h-px flex-1 bg-border" />
        </div>

        <input
          ref={fileRef}
          type="file"
          accept=".kml,.kmz,.gpx"
          className="hidden"
          onChange={(e) => void onFile(e.target.files?.[0])}
        />
        <Button
          variant="outline"
          className="w-full"
          disabled={loading}
          onClick={() => fileRef.current?.click()}
        >
          <Upload className="h-4 w-4" />
          Upload KML / KMZ / GPX
        </Button>

        {error && <p className="text-sm text-danger">{error}</p>}

        {tracks && (
          <div className="space-y-3">
            {/* Race maps often hold several courses - pick the right one. */}
            {tracks.length > 1 && (
              <div className="space-y-1.5">
                {tracks.map((t, i) => (
                  <label
                    key={i}
                    className={cn(
                      "flex cursor-pointer items-center justify-between rounded-xl border px-3 py-2 text-sm",
                      i === selected
                        ? "border-accent bg-accent/5 font-medium"
                        : "border-border hover:bg-muted",
                    )}
                  >
                    <span className="flex items-center gap-2.5">
                      <input
                        type="radio"
                        name="course-track"
                        checked={i === selected}
                        onChange={() => setSelected(i)}
                        className="accent-[hsl(var(--accent))]"
                      />
                      {t.name}
                    </span>
                    <span className="tabular-nums text-muted-foreground">
                      {t.distance_km.toFixed(1)} km
                    </span>
                  </label>
                ))}
              </div>
            )}
            <RouteMap route={tracks[selected].points} className="h-56 rounded-xl sm:h-64" />
          </div>
        )}
      </div>

      <DialogFooter className="justify-between">
        <div>
          {race.course && (
            <Button variant="ghost" className="text-danger" disabled={saving} onClick={remove}>
              Remove current map
            </Button>
          )}
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={save} disabled={!tracks || saving}>
            {saving ? "Saving…" : "Save course"}
          </Button>
        </div>
      </DialogFooter>
    </Dialog>
  );
}
