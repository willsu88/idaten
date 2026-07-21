"use client";

// Stage-2 of the coach-quality loop (COACH_QUALITY.md): the admin's weekly
// glance at how the coach's output is landing. Thumb rates per surface, per
// member, and the recent thumbs-down list — each entry a ready-made eval case
// (the rated text + frozen inputs travel with the rating).

import * as React from "react";
import { ThumbsDown, ThumbsUp } from "lucide-react";
import type { FeedbackBucket, FeedbackSummary, FeedbackSurface, Member } from "@/lib/types";
import { api, safe } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { formatDay } from "@/lib/utils";

const SURFACE_LABELS: Record<FeedbackSurface, string> = {
  coach_note: "Daily note",
  execution_analysis: "Run analysis",
  edit_proposal: "Plan proposals",
};

const TAG_LABELS: Record<string, string> = {
  wrong: "Wrong or ungrounded",
  off_tone: "Off tone",
  too_long: "Too long",
  not_useful: "Not useful",
  didnt_want_change: "Didn't want the change",
  reasoning_wrong: "Reasoning was wrong",
};

/** "94%" when there are ratings, "—" when a surface is still unrated. */
function upRate(b: FeedbackBucket): string {
  const rated = b.up + b.down;
  return rated === 0 ? "—" : `${Math.round((b.up / rated) * 100)}%`;
}

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-xl border border-border px-4 py-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-0.5 text-lg font-semibold tabular-nums">{value}</p>
      {sub && <p className="text-xs text-muted-foreground">{sub}</p>}
    </div>
  );
}

function statSub(b: FeedbackBucket): string {
  const parts = [`${b.up} up · ${b.down} down`];
  if (b.dismiss_reasons > 0) parts.push(`${b.dismiss_reasons} dismiss reasons`);
  return parts.join(" · ");
}

export function AdminQualityCard() {
  const [summary, setSummary] = React.useState<FeedbackSummary | null>(null);
  const [members, setMembers] = React.useState<Member[]>([]);
  const [error, setError] = React.useState(false);

  React.useEffect(() => {
    safe(api.feedbackSummary(90)).then((s) => (s ? setSummary(s) : setError(true)));
    safe(api.members()).then((m) => setMembers(m ?? []));
  }, []);

  const memberName = (id: number) =>
    members.find((m) => m.id === id)?.display_name ?? `Member ${id}`;

  const surfaces = (Object.keys(SURFACE_LABELS) as FeedbackSurface[]).map((surface) => ({
    ...(summary?.by_surface.find((b) => b.surface === surface) ?? {
      up: 0,
      down: 0,
      dismiss_reasons: 0,
    }),
    surface,
  }));

  return (
    <Card>
      <CardHeader>
        <CardTitle>Coach quality</CardTitle>
        <CardDescription>Thumb ratings on the coach&apos;s output (last 90 days)</CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        {summary == null && !error ? (
          <div className="grid gap-3 sm:grid-cols-3">
            <Skeleton className="h-20 rounded-xl" />
            <Skeleton className="h-20 rounded-xl" />
            <Skeleton className="h-20 rounded-xl" />
          </div>
        ) : error || !summary ? (
          <p className="text-sm text-muted-foreground">Couldn&apos;t load feedback.</p>
        ) : (
          <>
            <div className="grid gap-3 sm:grid-cols-3">
              {surfaces.map((b) => (
                <Stat
                  key={b.surface}
                  label={SURFACE_LABELS[b.surface]}
                  value={upRate(b)}
                  sub={statSub(b)}
                />
              ))}
            </div>

            <div>
              <p className="mb-2 text-sm font-medium">By member</p>
              {summary.by_user.length === 0 ? (
                <p className="text-sm text-muted-foreground">No ratings yet.</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-border text-left text-xs text-muted-foreground">
                        <th className="py-2 pr-3 font-medium">Member</th>
                        <th className="py-2 px-3 text-right font-medium">Up</th>
                        <th className="py-2 px-3 text-right font-medium">Down</th>
                        <th className="py-2 pl-3 text-right font-medium">Up rate</th>
                      </tr>
                    </thead>
                    <tbody>
                      {summary.by_user.map((r) => (
                        <tr key={r.user_id} className="border-b border-border/50 last:border-0">
                          <td className="py-2 pr-3 font-medium">{memberName(r.user_id)}</td>
                          <td className="py-2 px-3 text-right tabular-nums">{r.up}</td>
                          <td className="py-2 px-3 text-right tabular-nums">{r.down}</td>
                          <td className="py-2 pl-3 text-right font-semibold tabular-nums">
                            {upRate(r)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

            <div>
              <p className="mb-2 flex items-center gap-1.5 text-sm font-medium">
                <ThumbsDown className="h-3.5 w-3.5 text-muted-foreground" />
                Recent thumbs-down
              </p>
              {summary.recent_negative.length === 0 ? (
                <p className="flex items-center gap-1.5 text-sm text-muted-foreground">
                  <ThumbsUp className="h-3.5 w-3.5" />
                  None in this window - quiet is good.
                </p>
              ) : (
                <div className="space-y-3">
                  {summary.recent_negative.map((n, i) => (
                    <div
                      key={`${n.surface}:${n.artifact_ref}:${n.user_id}:${i}`}
                      className="rounded-xl border border-border bg-background/50 p-3"
                    >
                      <div className="flex flex-wrap items-center gap-1.5">
                        <Badge variant="secondary">{SURFACE_LABELS[n.surface]}</Badge>
                        {n.tags.map((t) => (
                          <Badge key={t} variant="outline">
                            {TAG_LABELS[t] ?? t}
                          </Badge>
                        ))}
                        <span className="ml-auto text-xs text-muted-foreground">
                          {memberName(n.user_id)}
                          {n.updated_at && ` · ${formatDay(n.updated_at.slice(0, 10))}`}
                        </span>
                      </div>
                      {n.comment && <p className="mt-1.5 text-sm italic">&ldquo;{n.comment}&rdquo;</p>}
                      <p className="mt-1.5 line-clamp-2 text-xs leading-relaxed text-muted-foreground">
                        {n.artifact_text}
                      </p>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}
