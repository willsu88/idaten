"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import {
  Check,
  ChevronLeft,
  ChevronRight,
  ChevronsDownUp,
  ChevronsUpDown,
  MessageSquare,
  MoreHorizontal,
  Trash2,
  Watch,
} from "lucide-react";
import type { DayIntent, PlanDay, WeekSummary } from "@/lib/types";
import { api, safe } from "@/lib/api";
import {
  compactStepsSummary,
  WORKOUT_BADGE_CLASSES,
  WORKOUT_BAR_CLASSES,
  WORKOUT_LABELS,
  workoutTargetLabel,
} from "@/lib/workout";
import { PageHeader } from "@/components/page-header";
import { CoachHint } from "@/components/coach-hint";
import { useChat } from "@/components/chat/chat-provider";
import { coachFirstName, useCoach } from "@/components/coach-provider";
import { CoachNote } from "@/components/coach-note";
import { CyclePhaseChip } from "@/components/cycle-phase-chip";
import { PushButton } from "@/components/workout-card";
import { ScoreRing } from "@/components/execution-score";
import { WeekStrip, WeekSummaryLine } from "@/components/week-strip";
import { RevertButton } from "@/components/revert-button";
import { IntentChip, OtherSportButton } from "@/components/intent-dialog";
import { PhaseChip, usePlanInfo } from "@/components/training-phases-card";
import { CoachModeBadge } from "@/components/coach-mode-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Dialog, DialogDescription, DialogFooter, DialogTitle } from "@/components/ui/dialog";
import { DropdownItem, DropdownMenu } from "@/components/ui/dropdown-menu";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";
import {
  APP_LOCALE,
  addDays,
  cn,
  formatDay,
  formatDuration,
  formatWeekday,
  isoDate,
  mondayOf,
  weekDates,
} from "@/lib/utils";

/** Duration · distance · target on one short line (compact row). */
function metaInline(day: PlanDay): string {
  const parts: string[] = [];
  const dur = formatDuration(day.duration_min);
  if (dur) parts.push(dur);
  if (day.distance_km != null) parts.push(`${day.distance_km} km`);
  const target = workoutTargetLabel(day);
  if (target) parts.push(target);
  return parts.join(" · ");
}

/** Where a row navigates. A completed day with a matched run points at the run
 * (the score + analysis live there); everything else opens the plan detail. */
function dayHref(day: PlanDay): string {
  if (day.status === "completed" && day.execution) {
    return `/activities/${day.execution.activity_id}`;
  }
  return `/plan/${day.date}`;
}

/**
 * One day, one accordion row. Collapsed = a tight scannable row; the chevron
 * expands the full detail inline (pattern B). Tapping the row body navigates:
 * to the matched run for a completed day, else to /plan/[date]. The expanded
 * panel is raised above that link so its own controls stay interactive.
 */
function DayRow({
  day,
  intent,
  isToday,
  mode,
  expanded,
  onToggle,
  onChanged,
}: {
  day: PlanDay;
  intent: DayIntent | null;
  isToday: boolean;
  mode: "editor" | "author" | null;
  expanded: boolean;
  onToggle: () => void;
  onChanged: () => void;
}) {
  const isRest = day.workout_type === "rest";
  const isDone = day.status === "completed";
  const wd = formatWeekday(day.date).slice(0, 3);
  const md = formatDay(day.date).replace(/^[^,]+,\s*/, ""); // "Sun, Jul 19" → "Jul 19"
  const meta = metaInline(day);
  // Untouched Garmin base day = editor mode, not the athlete's own sport, and no
  // coach rationale (a coach-authored/edited day always carries one, and its
  // note attributes it). `revertible` is NOT the signal — it goes false once a
  // day is completed, which would mislabel a coach-edited done day as Garmin's.
  const isGarminBase = mode === "editor" && !intent && !day.rationale;
  // Chips row: the Garmin-Coach marker, cycle, or a skipped tag. Completed shows
  // via the medallion + card state, so it's dropped from here.
  const hasChips = isGarminBase || !!day.cycle || day.status === "skipped";
  const href = dayHref(day);

  return (
    <Card
      id={`day-${day.date}`}
      className={cn(
        "group relative scroll-mt-20 overflow-hidden",
        isToday && "border-accent/50 ring-1 ring-accent/30",
        // Completed = a settled green state (keep the Today ring if it's today).
        isDone && (isToday ? "bg-success/5" : "border-success/30 bg-success/5"),
        isRest && "border-dashed bg-transparent",
        !isRest && !isDone && "transition-colors hover:border-accent/40",
      )}
    >
      {!isRest && (
        <Link href={href} aria-label={`Open ${day.title}`} className="absolute inset-0 z-10" />
      )}

      {/* Collapsed row — fixed date + badge columns so titles align. */}
      <div className="flex items-stretch">
        <div
          className={cn("w-1 shrink-0", isDone ? "bg-success" : WORKOUT_BAR_CLASSES[day.workout_type])}
        />
        <div className={cn("flex flex-1 items-center gap-2.5 px-3 py-2", isRest && "opacity-70")}>
          <div className="w-10 shrink-0 leading-tight">
            <p className="text-xs font-semibold">{wd}</p>
            {isToday ? (
              <p className="text-[10px] font-medium text-accent">Today</p>
            ) : (
              <p className="text-[10px] text-muted-foreground">{md}</p>
            )}
          </div>
          <div className="w-24 shrink-0">
            <Badge className={WORKOUT_BADGE_CLASSES[day.workout_type]}>
              {WORKOUT_LABELS[day.workout_type]}
            </Badge>
          </div>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium leading-tight group-hover:underline">
              {day.title}
            </p>
            {meta && <p className="truncate text-xs leading-tight text-muted-foreground">{meta}</p>}
          </div>
          {intent && (
            <span className="relative z-20 shrink-0">
              <IntentChip intent={intent} onRemoved={onChanged} />
            </span>
          )}
          {/* Completed → the execution-score medallion (links to the run); the
              green card state carries the "done" signal. Otherwise the on-watch
              glyph. */}
          {isDone && day.execution ? (
            <Link
              href={`/activities/${day.execution.activity_id}`}
              className="relative z-20 shrink-0"
              aria-label={`Execution score ${day.execution.score}`}
            >
              <ScoreRing score={day.execution.score} size="sm" check />
            </Link>
          ) : isDone ? (
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full border-2 border-success/50 bg-success/10 text-success">
              <Check className="h-4 w-4" strokeWidth={3} />
            </span>
          ) : day.pushed_at != null ? (
            <Watch className="h-4 w-4 shrink-0 text-success" aria-label="On watch" />
          ) : null}
          {/* Expand control — above the card link so it peeks, not navigates.
              44px hit area (negative margin keeps the visual footprint tight)
              so it's tap-reliable on mobile next to the full-card nav link. */}
          <button
            type="button"
            onClick={onToggle}
            aria-expanded={expanded}
            aria-label={expanded ? "Collapse" : "Expand"}
            className="relative z-20 -m-2 flex h-11 w-11 shrink-0 items-center justify-center rounded-md text-muted-foreground/60 transition-colors hover:bg-muted/60 hover:text-foreground"
          >
            <ChevronRight className={cn("h-4 w-4 transition-transform", expanded && "rotate-90")} />
          </button>
        </div>
      </div>

      {/* Expanded detail — no divider, no fill (the coach note's own box is the
          only tinted surface, so the card stays one background). */}
      {expanded && (
        <div className="relative z-20 space-y-3 px-4 pb-3 pt-1">
          {hasChips && (
            <div className="flex flex-wrap items-center gap-2">
              <CyclePhaseChip cycle={day.cycle} />
              {isGarminBase && (
                <Badge variant="secondary">
                  <Watch className="h-3 w-3" />
                  Garmin Coach
                </Badge>
              )}
              {day.status === "skipped" && <Badge variant="secondary">skipped</Badge>}
            </div>
          )}
          {!isRest && day.steps && day.steps.length > 0 && (
            <p className="text-sm tabular-nums text-foreground/80">
              {compactStepsSummary(day.steps)}
            </p>
          )}
          {day.description && <p className="text-sm text-muted-foreground">{day.description}</p>}
          {day.rationale && <CoachNote note={day.rationale} collapsible />}
          {/* Action bar: primary (push to watch) stays visible; secondary
              actions collapse into an overflow menu so the row stays clean on
              mobile. A completed day is LOCKED — no plan actions; the row body
              already navigates to the run. */}
          {!isDone && (
            <div className="flex flex-wrap items-center gap-2">
              <PushButton workout={day} size="sm" onPushed={onChanged} />
              <DropdownMenu
                trigger={
                  <Button variant="ghost" size="sm">
                    <MoreHorizontal className="h-4 w-4" />
                    More
                  </Button>
                }
              >
                {day.revertible && (
                  <RevertButton
                    date={day.date}
                    size="sm"
                    onReverted={onChanged}
                    className="w-full justify-start"
                  />
                )}
                <OtherSportButton
                  date={day.date}
                  intent={intent}
                  onSaved={onChanged}
                  size="sm"
                  className="w-full justify-start"
                />
              </DropdownMenu>
            </div>
          )}
        </div>
      )}
    </Card>
  );
}

/** A date in the visible ISO week that has no materialized plan day. Past dates
 * read as rest/no-plan; future dates firm up as they approach the window. */
function PlaceholderRow({ date, isToday }: { date: string; isToday: boolean }) {
  const wd = formatWeekday(date).slice(0, 3);
  const md = formatDay(date).replace(/^[^,]+,\s*/, "");
  const isFuture = date > isoDate();
  return (
    <Card
      id={`day-${date}`}
      className={cn(
        "relative scroll-mt-20 overflow-hidden border-dashed bg-transparent",
        isToday && "border-accent/50 ring-1 ring-accent/30",
      )}
    >
      <div className="flex items-center gap-2.5 px-3 py-2 opacity-60">
        <div className="w-10 shrink-0 leading-tight">
          <p className="text-xs font-semibold">{wd}</p>
          {isToday ? (
            <p className="text-[10px] font-medium text-accent">Today</p>
          ) : (
            <p className="text-[10px] text-muted-foreground">{md}</p>
          )}
        </div>
        <p className="text-xs text-muted-foreground">
          {isFuture ? "Plan firms up closer to the day" : "No planned workout"}
        </p>
      </div>
    </Card>
  );
}

/** "Jul 14 – 20" (same month) or "Jun 30 – Jul 6" for the ISO week. */
function weekRangeLabel(monday: string): string {
  const sunday = addDays(monday, 6);
  const opts: Intl.DateTimeFormatOptions = { month: "short", day: "numeric" };
  const a = new Date(`${monday}T00:00:00`);
  const b = new Date(`${sunday}T00:00:00`);
  const left = a.toLocaleDateString(APP_LOCALE, opts);
  const right =
    a.getMonth() === b.getMonth()
      ? String(b.getDate())
      : b.toLocaleDateString(APP_LOCALE, opts);
  return `${left} – ${right}`;
}

function WeekPageInner() {
  const router = useRouter();
  const params = useSearchParams();
  const today = isoDate();
  const currentMonday = mondayOf(today);
  // The viewed week lives in the URL (?start=), so back-navigation from a
  // workout returns you to the week you were on, and a week is deep-linkable.
  // Bare /week = this week. Normalize any start to its Monday.
  const startParam = params.get("start");
  const weekStart = startParam ? mondayOf(startParam) : currentMonday;
  const [days, setDays] = React.useState<PlanDay[] | null>(null);
  const [summary, setSummary] = React.useState<WeekSummary | null>(null);
  const [mode, setMode] = React.useState<"editor" | "author" | null>(null);
  const [intents, setIntents] = React.useState<DayIntent[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState(false);
  const [revertingWeek, setRevertingWeek] = React.useState(false);
  const [confirmRevertOpen, setConfirmRevertOpen] = React.useState(false);
  const [pushingWeek, setPushingWeek] = React.useState(false);
  const [clearingWeek, setClearingWeek] = React.useState(false);
  const [confirmClearOpen, setConfirmClearOpen] = React.useState(false);
  const { toast } = useToast();
  const { openWithDraft } = useChat();
  const persona = useCoach();
  const plan = usePlanInfo();

  const isCurrentWeek = weekStart === currentMonday;

  // Accordion: rows collapse by default (the whole week scans at a glance); a
  // chevron expands each inline, and "Expand/Collapse all" drives them together.
  // `allExpanded` is the persisted default; `overrides` holds per-day toggles so
  // a background refetch never clobbers what the user opened.
  const [allExpanded, setAllExpanded] = React.useState(false);
  const [overrides, setOverrides] = React.useState<Record<string, boolean>>({});
  React.useEffect(() => {
    setAllExpanded(localStorage.getItem("week_expand_all") === "1");
  }, []);
  const isExpanded = (date: string) => overrides[date] ?? allExpanded;
  const toggleDay = (date: string) =>
    setOverrides((o) => ({ ...o, [date]: !(o[date] ?? allExpanded) }));
  const toggleAll = () => {
    const next = !allExpanded;
    setAllExpanded(next);
    setOverrides({}); // a fresh all-state clears individual toggles
    localStorage.setItem("week_expand_all", next ? "1" : "0");
  };

  // Strip cell tap: open that day's card and scroll it into view.
  const jumpToDay = React.useCallback((date: string) => {
    setOverrides((o) => ({ ...o, [date]: true }));
    document.getElementById(`day-${date}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, []);

  // /week?day=YYYY-MM-DD (Today's strip deep-links here): once the week has
  // loaded, open + scroll to that day. One-shot — later refetches leave the
  // user's scroll position alone.
  const dayParam = params.get("day");
  const jumpedRef = React.useRef(false);
  React.useEffect(() => {
    if (loading || jumpedRef.current || !dayParam) return;
    jumpedRef.current = true;
    jumpToDay(dayParam);
  }, [loading, dayParam, jumpToDay]);

  const load = React.useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.planWeek(weekStart);
      setDays(res.days);
      setSummary(res.summary ?? null);
      setMode(res.mode);
      setError(false);
      const start = weekStart;
      const end = addDays(weekStart, 6);
      setIntents((await safe(api.intents(start, end))) ?? []);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, [weekStart]);

  React.useEffect(() => {
    load();
  }, [load]);

  // Paging weeks rewrites the URL (replace, so arrow-clicks don't pile up
  // history — back still exits to where you came from). scroll:false keeps you
  // in place. Landing on the current week drops the param for a clean /week.
  const goToWeek = (monday: string) => {
    setOverrides({}); // per-day toggles don't carry across weeks
    const url = monday === currentMonday ? "/week" : `/week?start=${monday}`;
    router.replace(url, { scroll: false });
  };
  const goWeek = (deltaDays: number) => goToWeek(addDays(weekStart, deltaDays));

  const pushWeek = async () => {
    setPushingWeek(true);
    try {
      const res = await api.pushWeek(weekStart);
      toast(
        res.pushed === 0
          ? "Nothing to push — week is already on the watch"
          : `Pushed ${res.pushed} workout${res.pushed === 1 ? "" : "s"} to the watch`,
      );
      load();
    } catch {
      toast("Push failed — is the backend running?", "error");
    } finally {
      setPushingWeek(false);
    }
  };

  const clearWeek = async () => {
    setClearingWeek(true);
    setConfirmClearOpen(false);
    try {
      const res = await api.unpushWeek(weekStart);
      toast(
        res.removed === 0
          ? "Nothing on the watch for this week"
          : `Removed ${res.removed} workout${res.removed === 1 ? "" : "s"} from the watch`,
      );
      load();
    } catch {
      toast("Clear failed — is the backend running?", "error");
    } finally {
      setClearingWeek(false);
    }
  };

  const revertWeek = async () => {
    setRevertingWeek(true);
    setConfirmRevertOpen(false);
    try {
      const res = await api.revertToGarmin({ week: true, start: weekStart });
      toast(
        res.reverted.length === 0
          ? "No Idaten edits this week — already the Garmin Coach plan"
          : `Restored ${res.reverted.length} day${res.reverted.length === 1 ? "" : "s"} to the Garmin Coach plan`,
      );
      load();
    } catch {
      toast("Revert failed — is the backend running?", "error");
    } finally {
      setRevertingWeek(false);
    }
  };

  const hasEdits = (days ?? []).some((d) => d.revertible);

  // Progress across the week: completed run days over all non-rest days.
  const runDays = (days ?? []).filter((d) => d.workout_type !== "rest");
  const doneCount = runDays.filter((d) => d.status === "completed").length;

  // Every ISO day Mon…Sun, filled from the materialized plan or a placeholder.
  const byDate = new Map((days ?? []).map((d) => [d.date, d]));
  const slots = weekDates(weekStart);

  return (
    <div>
      <PageHeader
        title={isCurrentWeek ? "This week" : weekRangeLabel(weekStart)}
        subtitle={
          <span className="flex flex-wrap items-center gap-2">
            <PhaseChip plan={plan} />
            <CoachModeBadge mode={mode} />
          </span>
        }
      />

      {/* Week navigator: prev/next stepping, this week's progress, and an
          at-a-glance Mon-Sun strip that doubles as quick-jump. */}
      <div className="mb-6 space-y-2.5">
        <div className="flex items-center gap-2">
          <Button variant="outline" size="icon-sm" onClick={() => goWeek(-7)} aria-label="Previous week">
            <ChevronLeft className="h-4 w-4" />
          </Button>
          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium">{weekRangeLabel(weekStart)}</p>
            {!loading && (
              <WeekSummaryLine
                summary={summary}
                prefix={runDays.length > 0 ? `${doneCount} / ${runDays.length} done` : null}
              />
            )}
          </div>
          {!isCurrentWeek && (
            <Button variant="ghost" size="sm" onClick={() => goToWeek(currentMonday)}>
              This week
            </Button>
          )}
          <Button variant="outline" size="icon-sm" onClick={() => goWeek(7)} aria-label="Next week">
            <ChevronRight className="h-4 w-4" />
          </Button>
        </div>

        {loading ? (
          <Skeleton className="h-12 rounded-lg" />
        ) : (
          <WeekStrip
            dates={slots}
            days={days ?? []}
            intents={intents}
            today={today}
            onJump={jumpToDay}
          />
        )}
      </div>

      {/* Week actions — a dedicated left-aligned toolbar so they don't stagger
          in the header. Primary (ask the coach) first, then watch/plan management. */}
      <div className="mb-6 flex flex-wrap items-center gap-2">
        <Button
          variant="outline"
          size="sm"
          // Pre-types the /replan shortcut; the user adds context and sends.
          onClick={() => openWithDraft("/replan ")}
        >
          {persona ? (
            <img
              src={persona.headSrc}
              alt={persona.name}
              className="h-5 w-5 rounded-full border border-border object-cover"
            />
          ) : (
            <MessageSquare className="h-3.5 w-3.5" />
          )}
          Ask {persona ? coachFirstName(persona) : "your coach"} to adjust
        </Button>

        <span className="mx-0.5 hidden h-5 w-px bg-border sm:block" aria-hidden />

        {/* Watch/plan management — inline on desktop, tucked into an overflow
            menu on mobile so the toolbar stays a single tidy row. */}
        <div className="hidden items-center gap-2 sm:flex">
          <Button
            variant="outline"
            size="sm"
            onClick={pushWeek}
            disabled={pushingWeek || loading || !days || days.length === 0}
          >
            <Watch className="h-3.5 w-3.5" />
            {pushingWeek ? "Sending…" : "Send week to watch"}
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setConfirmClearOpen(true)}
            disabled={clearingWeek || loading || !days || days.length === 0}
          >
            <Trash2 className="h-3.5 w-3.5" />
            {clearingWeek ? "Clearing…" : "Clear week from watch"}
          </Button>
          {mode === "editor" && hasEdits && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => setConfirmRevertOpen(true)}
              disabled={revertingWeek || loading}
            >
              <Watch className="h-3.5 w-3.5" />
              {revertingWeek ? "Restoring…" : "Replace with Garmin Coach plan"}
            </Button>
          )}
        </div>

        <div className="sm:hidden">
          <DropdownMenu
            align="start"
            trigger={
              <Button variant="outline" size="sm">
                <MoreHorizontal className="h-3.5 w-3.5" />
                More
              </Button>
            }
          >
            <DropdownItem
              onClick={pushWeek}
              disabled={pushingWeek || loading || !days || days.length === 0}
            >
              <Watch className="h-4 w-4" />
              {pushingWeek ? "Sending…" : "Send week to watch"}
            </DropdownItem>
            <DropdownItem
              onClick={() => setConfirmClearOpen(true)}
              disabled={clearingWeek || loading || !days || days.length === 0}
            >
              <Trash2 className="h-4 w-4" />
              {clearingWeek ? "Clearing…" : "Clear week from watch"}
            </DropdownItem>
            {mode === "editor" && hasEdits && (
              <DropdownItem onClick={() => setConfirmRevertOpen(true)} disabled={revertingWeek || loading}>
                <Watch className="h-4 w-4" />
                {revertingWeek ? "Restoring…" : "Replace with Garmin Coach plan"}
              </DropdownItem>
            )}
          </DropdownMenu>
        </div>

        <Button
          variant="ghost"
          size="sm"
          onClick={toggleAll}
          className="ml-auto"
          aria-label={allExpanded ? "Collapse all days" : "Expand all days"}
        >
          {allExpanded ? (
            <ChevronsDownUp className="h-3.5 w-3.5" />
          ) : (
            <ChevronsUpDown className="h-3.5 w-3.5" />
          )}
          {allExpanded ? "Collapse all" : "Expand all"}
        </Button>
      </div>

      <CoachHint page="week" />

      <Dialog open={confirmClearOpen} onOpenChange={setConfirmClearOpen}>
        <DialogTitle>Clear week from watch?</DialogTitle>
        <DialogDescription>
          This deletes all of this week&apos;s pushed workouts from your Garmin calendar. Your plan
          here stays unchanged — you can resend it any time.
        </DialogDescription>
        <DialogFooter>
          <Button variant="outline" onClick={() => setConfirmClearOpen(false)}>
            Cancel
          </Button>
          <Button variant="destructive" onClick={clearWeek}>
            Clear week
          </Button>
        </DialogFooter>
      </Dialog>

      <Dialog open={confirmRevertOpen} onOpenChange={setConfirmRevertOpen}>
        <DialogTitle>Replace this week with the Garmin Coach plan?</DialogTitle>
        <DialogDescription>
          This discards Idaten&apos;s edits for this week and restores your original Garmin Coach
          workouts. Any of these days already pushed to your watch are removed so the native Garmin
          Coach workout stands. Your committed other-sport days are kept.
        </DialogDescription>
        <DialogFooter>
          <Button variant="outline" onClick={() => setConfirmRevertOpen(false)}>
            Cancel
          </Button>
          <Button onClick={revertWeek}>Replace with Garmin Coach</Button>
        </DialogFooter>
      </Dialog>

      {loading ? (
        <div className="space-y-3">
          {Array.from({ length: 7 }).map((_, i) => (
            <Skeleton key={i} className="h-24 rounded-2xl" />
          ))}
        </div>
      ) : error ? (
        <Card>
          <CardContent className="p-6 text-sm text-muted-foreground">
            Couldn&apos;t load the plan — is the backend running?
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-2">
          {slots.map((date) => {
            const day = byDate.get(date);
            return day ? (
              <DayRow
                key={date}
                day={day}
                intent={intents.find((i) => i.date === date) ?? null}
                isToday={date === today}
                mode={mode}
                expanded={isExpanded(date)}
                onToggle={() => toggleDay(date)}
                onChanged={load}
              />
            ) : (
              <PlaceholderRow key={date} date={date} isToday={date === today} />
            );
          })}
        </div>
      )}
    </div>
  );
}

export default function WeekPage() {
  // useSearchParams needs a Suspense boundary for the static shell.
  return (
    <React.Suspense fallback={<Skeleton className="h-24 rounded-2xl" />}>
      <WeekPageInner />
    </React.Suspense>
  );
}
