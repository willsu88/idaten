import {
  Activity,
  Bike,
  Dumbbell,
  Flame,
  Footprints,
  Gauge,
  HeartPulse,
  Mountain,
  MountainSnow,
  PersonStanding,
  Snowflake,
  Waves,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";

/** Exact Garmin typeKey → icon; substring fallbacks cover the long tail. */
const ICON_BY_TYPE: Record<string, LucideIcon> = {
  running: Footprints,
  track_running: Footprints,
  trail_running: MountainSnow,
  treadmill_running: Gauge,
  indoor_running: Gauge,
  virtual_run: Gauge,
  walking: PersonStanding,
  casual_walking: PersonStanding,
  speed_walking: PersonStanding,
  hiking: Mountain,
  mountaineering: Mountain,
  indoor_cardio: HeartPulse,
  hiit: Flame,
  yoga: PersonStanding,
};

export function activityIcon(type: string): LucideIcon {
  const exact = ICON_BY_TYPE[type];
  if (exact) return exact;
  if (type.includes("running")) return Footprints;
  if (type.includes("walking")) return PersonStanding;
  if (type.includes("hiking")) return Mountain;
  if (type.includes("cycling") || type.includes("biking")) return Bike;
  if (type.includes("swim") || type.includes("surf") || type.includes("paddl")) return Waves;
  if (type.includes("strength") || type.includes("fitness")) return Dumbbell;
  if (type.includes("snow") || type.includes("ski")) return Snowflake;
  return Activity;
}

/** Round icon chip identifying an activity's type at a glance. */
export function ActivityTypeIcon({ type, className }: { type: string; className?: string }) {
  const Icon = activityIcon(type);
  return (
    <span
      className={cn(
        "flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-accent/10 text-accent",
        className,
      )}
      aria-hidden
    >
      <Icon className="h-4 w-4" />
    </span>
  );
}
