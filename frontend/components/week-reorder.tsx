"use client";

/**
 * Week edit mode: the drag-to-reorder list (spec: .scratch/week-reorder/spec.md).
 *
 * Rendering model mirrors lib/reorder.ts: seven fixed slots in Mon…Sun order;
 * dragging swaps the CONTENT of two unlocked slots (whole-day cards trade
 * dates). The date column belongs to the slot and never moves; everything
 * right of it rides with the content. Locked slots (past, completed/skipped,
 * placeholder) are inert anchors. All state is staged by the parent — this
 * component only reports swaps.
 */

import * as React from "react";
import {
  DndContext,
  type DragEndEvent,
  KeyboardSensor,
  PointerSensor,
  TouchSensor,
  closestCenter,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import {
  SortableContext,
  rectSwappingStrategy,
  sortableKeyboardCoordinates,
  useSortable,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { GripVertical, Lock, TriangleAlert } from "lucide-react";
import type { PlanDay } from "@/lib/types";
import { adjacentQualityDates, isLockedDay, swapSlots } from "@/lib/reorder";
import {
  WORKOUT_BADGE_CLASSES,
  WORKOUT_BAR_CLASSES,
  WORKOUT_LABELS,
  workoutTargetLabel,
} from "@/lib/workout";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { cn, formatDay, formatDuration, formatWeekday } from "@/lib/utils";

function contentMeta(day: PlanDay): string {
  const parts: string[] = [];
  const dur = formatDuration(day.duration_min);
  if (dur) parts.push(dur);
  if (day.distance_km != null) parts.push(`${day.distance_km} km`);
  const target = workoutTargetLabel(day);
  if (target) parts.push(target);
  return parts.join(" · ");
}

function EditRow({
  slotDate,
  content,
  locked,
  isToday,
  warn,
}: {
  slotDate: string;
  content: PlanDay | undefined;
  locked: boolean;
  isToday: boolean;
  warn: boolean;
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } =
    useSortable({ id: slotDate, disabled: locked });
  const wd = formatWeekday(slotDate).slice(0, 3);
  const md = formatDay(slotDate).replace(/^[^,]+,\s*/, "");
  const isRest = content?.workout_type === "rest";
  const meta = content ? contentMeta(content) : "";

  return (
    <Card
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      className={cn(
        "relative overflow-hidden",
        isToday && "border-accent/50 ring-1 ring-accent/30",
        isRest && "border-dashed bg-transparent",
        locked && "opacity-50",
        isDragging && "z-30 shadow-lg ring-2 ring-accent/50",
        warn && !isDragging && "border-warning/60",
      )}
      {...(locked ? {} : { ...attributes, ...listeners })}
      aria-label={locked ? `${wd} (locked)` : `Move ${content?.title ?? wd}`}
    >
      <div className={cn("flex items-stretch", !locked && "cursor-grab touch-none active:cursor-grabbing")}>
        <div
          className={cn(
            "w-1 shrink-0",
            content ? WORKOUT_BAR_CLASSES[content.workout_type] : "bg-muted",
          )}
        />
        <div className="flex flex-1 items-center gap-2.5 px-3 py-2">
          {/* The slot's date — anchored, never travels with a drag. */}
          <div className="w-10 shrink-0 leading-tight">
            <p className="text-xs font-semibold">{wd}</p>
            {isToday ? (
              <p className="text-[10px] font-medium text-accent">Today</p>
            ) : (
              <p className="text-[10px] text-muted-foreground">{md}</p>
            )}
          </div>
          {content ? (
            <>
              <div className="w-24 shrink-0">
                <Badge className={WORKOUT_BADGE_CLASSES[content.workout_type]}>
                  {WORKOUT_LABELS[content.workout_type]}
                </Badge>
              </div>
              <div className="min-w-0 flex-1">
                <p className={cn("truncate text-sm font-medium leading-tight", isRest && "opacity-70")}>
                  {content.title}
                </p>
                {meta && (
                  <p className="truncate text-xs leading-tight text-muted-foreground">{meta}</p>
                )}
              </div>
            </>
          ) : (
            <p className="flex-1 text-xs text-muted-foreground">No planned workout</p>
          )}
          {warn && (
            <TriangleAlert
              className="h-4 w-4 shrink-0 text-warning"
              aria-label="Back-to-back quality days"
            />
          )}
          {locked ? (
            <Lock className="h-4 w-4 shrink-0 text-muted-foreground/50" aria-label="Locked" />
          ) : (
            <GripVertical className="h-4 w-4 shrink-0 text-muted-foreground/60" aria-hidden />
          )}
        </div>
      </div>
    </Card>
  );
}

export function WeekReorderList({
  slots,
  byDate,
  assignment,
  onAssignmentChange,
  today,
}: {
  slots: string[];
  byDate: Map<string, PlanDay>;
  assignment: string[];
  onAssignmentChange: (next: string[]) => void;
  today: string;
}) {
  const locked = slots.map((date) => isLockedDay(byDate.get(date), date, today));
  const flagged = adjacentQualityDates(slots, assignment, byDate);
  const sensors = useSensors(
    // Small distance/delay thresholds keep taps and scrolls from lifting cards.
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 200, tolerance: 6 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  const onDragEnd = ({ active, over }: DragEndEvent) => {
    if (!over || active.id === over.id) return;
    const a = slots.indexOf(String(active.id));
    const b = slots.indexOf(String(over.id));
    onAssignmentChange(swapSlots(assignment, a, b, locked));
  };

  return (
    // The dotted frame marks the sortable group — the edit-mode surface.
    <div className="rounded-2xl border-2 border-dashed border-accent/40 p-2">
      <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
        <SortableContext items={slots} strategy={rectSwappingStrategy}>
          <div className="space-y-2">
            {slots.map((date, i) => (
              <EditRow
                key={date}
                slotDate={date}
                content={byDate.get(assignment[i])}
                locked={locked[i]}
                isToday={date === today}
                warn={flagged.has(date)}
              />
            ))}
          </div>
        </SortableContext>
      </DndContext>
      {flagged.size > 0 && (
        <p className="flex items-center gap-1.5 px-2 pb-1 pt-2 text-xs text-warning">
          <TriangleAlert className="h-3.5 w-3.5 shrink-0" />
          Two quality days back-to-back — an easy day between hard efforts helps you absorb them.
        </p>
      )}
    </div>
  );
}
