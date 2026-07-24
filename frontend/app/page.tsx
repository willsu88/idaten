"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Flag, Watch } from "lucide-react";
import type { DashboardToday, DayIntent, PlanDay, Settings, WeekSummary } from "@/lib/types";
import { api, safe } from "@/lib/api";
import { APP_LOCALE, addDays, formatSeconds, isoDate, mondayOf, weekDates } from "@/lib/utils";
import { WeekStrip, WeekSummaryLine } from "@/components/week-strip";
import { formatSignedSeconds } from "@/components/race-chip";
import { SHOW_RACE_PREDICTION } from "@/lib/flags";
import { PageHeader } from "@/components/page-header";
import { SyncButton } from "@/components/sync-button";
import { GettingStartedCard } from "@/components/getting-started-card";
import { ReadinessCard } from "@/components/readiness-card";
import { CycleTodayCard } from "@/components/cycle-today-card";
import { NiggleCard } from "@/components/niggle-card";
import { DailyCoachNote } from "@/components/daily-coach-note";
import { TodayWorkoutCard } from "@/components/workout-card";
import { EditProposalCard } from "@/components/edit-proposal-card";
import { RpeCard } from "@/components/rpe-card";
import { AttributionCard } from "@/components/attribution-card";
import { ResultCard } from "@/components/result-card";
import { StrengthTodayCard, SupportSessionCard } from "@/components/support-session-card";
import { PhaseChip, usePlanInfo } from "@/components/training-phases-card";
import { CoachModeBadge } from "@/components/coach-mode-badge";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

export default function TodayPage() {
  const router = useRouter();
  const [data, setData] = React.useState<DashboardToday | null>(null);
  const [intent, setIntent] = React.useState<DayIntent | null>(null);
  const [week, setWeek] = React.useState<{ days: PlanDay[]; summary: WeekSummary | null } | null>(
    null,
  );
  const [weekIntents, setWeekIntents] = React.useState<DayIntent[]>([]);
  const [settings, setSettings] = React.useState<Settings | null>(null);
  const [garminConnected, setGarminConnected] = React.useState(true);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState(false);
  const plan = usePlanInfo();

  const load = React.useCallback(async () => {
    const todayIso = isoDate();
    const monday = mondayOf(todayIso);
    try {
      // Week context (the at-a-glance strip) rides along; `safe` so a hiccup
      // there never blanks the dashboard.
      const [dashboard, intents, sync, s, weekPlan, weekInts] = await Promise.all([
        api.dashboardToday(),
        safe(api.intents(todayIso, todayIso)),
        safe(api.syncStatus()),
        safe(api.getSettings()),
        safe(api.planWeek(monday)),
        safe(api.intents(monday, addDays(monday, 6))),
      ]);
      // First-run users land in the setup wizard until it sets tutorial_done.
      // Only "/" redirects (never /welcome itself), so there is no loop.
      if (s && !s.tutorial_done) {
        router.replace("/welcome");
        return;
      }
      setData(dashboard);
      setIntent(intents?.find((i) => i.date === todayIso) ?? null);
      setWeek(weekPlan ? { days: weekPlan.days, summary: weekPlan.summary ?? null } : null);
      setWeekIntents(weekInts ?? []);
      setSettings(s);
      setGarminConnected(sync?.garmin_connected ?? true);
      setError(false);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, [router]);

  React.useEffect(() => {
    load();
  }, [load]);

  const today = new Date().toLocaleDateString(APP_LOCALE, {
    weekday: "long",
    month: "long",
    day: "numeric",
  });

  return (
    <div>
      <PageHeader
        title="Today"
        subtitle={
          <div className="space-y-1.5">
            <span className="flex flex-wrap items-center gap-2">
              <PhaseChip plan={plan} />
              <CoachModeBadge mode={data?.mode} />
            </span>
            <p>{today}</p>
          </div>
        }
        titleActions={<SyncButton compact onSynced={load} />}
      />

      {data?.race && data.days_to_race != null && (
        <div className="mb-5">
          {/* Two-line banner: name on top, countdown + prediction below. A single
              inline pill crammed name/days/prediction together and wrapped
              mid-phrase on mobile. */}
          <div className="flex items-start gap-1.5 rounded-xl border border-border px-3 py-2">
            <Flag className="mt-0.5 h-3.5 w-3.5 shrink-0 text-accent" />
            <div className="min-w-0 text-sm">
              <span className="font-semibold">{data.race.name}</span>
              <p className="mt-0.5 leading-snug text-muted-foreground">
                <span className="tabular-nums">
                  {data.days_to_race} day{data.days_to_race === 1 ? "" : "s"}
                </span>
                {SHOW_RACE_PREDICTION && data.race.prediction.likely_s != null && (
                  <span
                    className={
                      data.race.prediction.delta_s != null && data.race.prediction.delta_s <= 0
                        ? "tabular-nums text-success"
                        : "tabular-nums"
                    }
                  >
                    {" · "}
                    {data.race.prediction.confidence === "low" ||
                    data.race.prediction.low_s == null ||
                    data.race.prediction.high_s == null ? (
                      <>likely ~{formatSeconds(data.race.prediction.likely_s)}</>
                    ) : (
                      <>
                        likely {formatSeconds(data.race.prediction.low_s)}–
                        {formatSeconds(data.race.prediction.high_s)}
                      </>
                    )}
                    {data.race.prediction.goal_time_s != null && (
                      <> vs goal {formatSeconds(data.race.prediction.goal_time_s)}</>
                    )}
                  </span>
                )}
                {/* Default: Garmin's predicted finish (Idaten's own stays behind the flag). */}
                {!SHOW_RACE_PREDICTION && data.race.prediction.garmin_time_s != null && (
                  <span
                    className={
                      data.race.prediction.goal_time_s != null &&
                      data.race.prediction.garmin_time_s <= data.race.prediction.goal_time_s
                        ? "tabular-nums text-success"
                        : "tabular-nums"
                    }
                  >
                    {" · Garmin predicts "}
                    {formatSeconds(data.race.prediction.garmin_time_s)}
                    {data.race.prediction.goal_time_s != null && (
                      <>
                        {" · "}
                        {formatSignedSeconds(
                          data.race.prediction.garmin_time_s - data.race.prediction.goal_time_s,
                        )}{" "}
                        vs goal
                      </>
                    )}
                  </span>
                )}
              </p>
            </div>
          </div>
        </div>
      )}

      {loading ? (
        <div className="space-y-5">
          <Skeleton className="h-44 rounded-2xl" />
          <Skeleton className="h-64 rounded-2xl" />
        </div>
      ) : error ? (
        <Card>
          <CardContent className="p-6 text-sm text-muted-foreground">
            Couldn&apos;t reach the backend at the API URL. Start it and refresh, or hit Sync now.
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-5">
          <GettingStartedCard
            garminConnected={garminConnected}
            tutorialDone={settings?.tutorial_done ?? true}
            hasRace={data?.race != null}
          />

          {!garminConnected ? (
            <Card className="border-accent/40">
              <CardContent className="flex flex-col items-start gap-3 p-6">
                <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent/10 text-accent">
                  <Watch className="h-5 w-5" />
                </span>
                <div>
                  <p className="text-sm font-semibold">Connect your Garmin account to get started</p>
                  <p className="mt-1 text-sm text-muted-foreground">
                    The coach needs your Garmin data to build readiness scores and a training plan.
                    Head to Settings and link your account — your data syncs in about a minute, and
                    your plan is ready the next time you open Today.
                  </p>
                </div>
                <Link
                  href="/settings"
                  className="inline-flex h-9 items-center gap-2 rounded-xl bg-accent px-4 text-sm font-medium text-accent-foreground transition-colors hover:bg-accent/90"
                >
                  Go to Settings
                </Link>
              </CardContent>
            </Card>
          ) : (
            <>
              {/* The coach leads the page: the note (streamed in; a surfaced
                  proposal refetches the dashboard via onProposal) interprets
                  today, and the readiness data below is its supporting evidence.
                  A pending proposal is a decision - never below the fold.
                  Note then proposal: diagnosis before prescription. */}
              <DailyCoachNote onProposal={load} />

              {data?.pending_edit && (
                <EditProposalCard edit={data.pending_edit} onResolved={load} />
              )}

              <ReadinessCard readiness={data?.readiness ?? null} />

              {/* Week context without leaving Today: the same at-a-glance strip
                  as /week; a day tap deep-links to that day's card there. */}
              {week && week.days.length > 0 && (
                <Card>
                  <CardContent className="p-4">
                    <div className="mb-2.5 flex items-center justify-between gap-2">
                      <Link href="/week" className="text-sm font-semibold hover:underline">
                        This week
                      </Link>
                    </div>
                    <WeekStrip
                      dates={weekDates(mondayOf(isoDate()))}
                      days={week.days}
                      intents={weekIntents}
                      today={isoDate()}
                      onJump={(d) => router.push(`/week?day=${d}`)}
                    />
                    {/* Below the strip (not the header row) so the line can
                        wrap instead of truncating the tooltip away on phones. */}
                    <WeekSummaryLine summary={week.summary} className="mt-2.5" />
                  </CardContent>
                </Card>
              )}

              <CycleTodayCard cycle={data?.cycle ?? null} onChanged={load} />

              <NiggleCard niggles={data?.niggles ?? null} onChanged={load} />

              {/* Once today's planned run is done and scored, the plan card
                  gives way to the result card (score + lazy analysis). */}
              {data?.completed_workout ? (
                <ResultCard activity={data.completed_workout} />
              ) : (
                <TodayWorkoutCard
                  workout={data?.workout ?? null}
                  intent={intent}
                  mode={data?.mode}
                  onChanged={load}
                />
              )}

              <StrengthTodayCard session={data?.strength_session ?? null} onChanged={load} />

              <SupportSessionCard sessions={data?.support_activities ?? []} />

              {data?.unrated_activity && (
                <RpeCard activity={data.unrated_activity} onRated={load} />
              )}

              {data?.attribution_prompt && (
                <AttributionCard
                  activityId={data.attribution_prompt.activity_id}
                  workoutLabel={data.attribution_prompt.workout_label}
                  onResolved={load}
                />
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
