import type { HrZones } from "@/lib/types";
import { primaryZoneForHr, ZONE_COLORS, ZONE_LABELS, type ZoneKey } from "@/lib/workout";
import { cn } from "@/lib/utils";

const ZONE_ORDER: ZoneKey[] = ["z1", "z2", "z3", "z4", "z5"];

/**
 * Locates a whole-run HR target on the athlete's Z1–Z5 scale: five proportional
 * zone bands with the target range highlighted and its primary zone named. This
 * is the "what type of run" signal for an HR-targeted plan day.
 */
export function HrZoneBar({
  zones,
  low,
  high,
}: {
  zones: HrZones;
  low: number;
  high: number;
}) {
  const scaleLo = zones.z1[0];
  const scaleHi = zones.z5[1];
  const span = scaleHi - scaleLo;
  if (span <= 0) return null;

  const pct = (bpm: number) => ((Math.min(Math.max(bpm, scaleLo), scaleHi) - scaleLo) / span) * 100;
  const primary = primaryZoneForHr(zones, low, high);
  const point = low === high;
  const left = pct(low);
  const width = Math.max(pct(high) - left, point ? 0 : 1);

  return (
    <div>
      <div className="flex items-center justify-between">
        <p className="text-sm font-semibold">Target zone</p>
        <p className="text-sm font-medium tabular-nums text-muted-foreground">
          {point ? `HR ${low}` : `HR ${low}–${high}`} bpm
        </p>
      </div>

      <div className="relative mt-2 h-7">
        {/* zone bands */}
        <div className="flex h-full overflow-hidden rounded-lg">
          {ZONE_ORDER.map((z) => {
            const [lo, hi] = zones[z];
            const w = ((hi - lo) / span) * 100;
            const active = z === primary;
            return (
              <div
                key={z}
                className={cn(
                  "flex items-center justify-center text-[10px] font-semibold uppercase tracking-wide transition-opacity",
                  active ? "text-white" : "text-white/70",
                )}
                style={{
                  width: `${w}%`,
                  backgroundColor: ZONE_COLORS[z],
                  opacity: active ? 1 : 0.35,
                }}
                title={`${z.toUpperCase()} · ${lo}–${hi} bpm`}
              >
                {w > 7 ? z.toUpperCase() : ""}
              </div>
            );
          })}
        </div>
        {/* target overlay */}
        <div
          className="pointer-events-none absolute inset-y-0 rounded-md border-2 border-foreground/80 bg-foreground/5"
          style={{ left: `${left}%`, width: `${width}%`, minWidth: point ? 2 : undefined }}
        />
      </div>

      {/* boundary ticks */}
      <div className="relative mt-1 h-4 text-[10px] tabular-nums text-muted-foreground">
        {[...ZONE_ORDER.map((z) => zones[z][0]), scaleHi].map((bpm, i, arr) => (
          <span
            key={i}
            className="absolute -translate-x-1/2"
            style={{
              left: `${pct(bpm)}%`,
              transform:
                i === 0 ? "translateX(0)" : i === arr.length - 1 ? "translateX(-100%)" : undefined,
            }}
          >
            {bpm}
          </span>
        ))}
      </div>

      <p className="mt-1.5 text-sm">
        <span
          className="font-semibold"
          style={{ color: ZONE_COLORS[primary] }}
        >
          {primary.toUpperCase()} · {ZONE_LABELS[primary]}
        </span>
      </p>
    </div>
  );
}
