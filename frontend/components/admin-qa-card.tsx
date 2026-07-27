"use client";

// The nightly coach QA scorecard (ADR 0016): per rubric item, this week's
// counts, the version-grouped comparison table (the "did my prompt edit help"
// answer), and recent fails with the judge's reasons. Counts always show their
// denominators; n/a is excluded from every rate; no transcript drill-down -
// the session id is a pointer the operator follows deliberately.

import * as React from "react";
import { AlertTriangle, ShieldCheck } from "lucide-react";
import type { QaSummary } from "@/lib/types";
import { api, safe } from "@/lib/api";
import {
  applicable,
  currentWeek,
  hasData,
  pctLabel,
  ratioLabel,
  RUBRIC_LABELS,
  versionColumns,
} from "@/lib/qa";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { formatDay } from "@/lib/utils";

export function AdminQaCard() {
  const [summary, setSummary] = React.useState<QaSummary | null>(null);
  const [error, setError] = React.useState(false);

  React.useEffect(() => {
    safe(api.qaSummary()).then((s) => (s ? setSummary(s) : setError(true)));
  }, []);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Coach QA</CardTitle>
        <CardDescription>
          Every chat session judged nightly against the coach&apos;s rubric
          {summary && ` · judge ${summary.judge_model} · rubric ${summary.rubric_version}`}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        {summary == null && !error ? (
          <div className="grid gap-3 sm:grid-cols-3">
            <Skeleton className="h-20 rounded-xl" />
            <Skeleton className="h-20 rounded-xl" />
            <Skeleton className="h-20 rounded-xl" />
          </div>
        ) : error || !summary ? (
          <p className="text-sm text-muted-foreground">Couldn&apos;t load QA scores.</p>
        ) : (
          <>
            {!summary.enabled && (
              <p className="text-sm text-muted-foreground">
                QA scoring is toggled off - existing scores stay readable; nothing new is judged.
              </p>
            )}

            <div className="grid gap-3 sm:grid-cols-3">
              {summary.items.map((item) => {
                const week = currentWeek(item);
                return (
                  <div key={item.key} className="rounded-xl border border-border px-4 py-3">
                    <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
                      {RUBRIC_LABELS[item.key] ?? item.key}
                      {item.regression && <AlertTriangle className="h-3.5 w-3.5 text-amber-500" />}
                    </p>
                    <p className="mt-0.5 text-lg font-semibold tabular-nums">
                      {ratioLabel(week)}
                      <span className="ml-1 text-xs font-normal text-muted-foreground">
                        this week{week.na > 0 && ` · ${week.na} n/a`}
                      </span>
                    </p>
                  </div>
                );
              })}
            </div>

            <div>
              <p className="mb-2 text-sm font-medium">By prompt version</p>
              {summary.items.every((i) => !hasData(i)) ? (
                <p className="text-sm text-muted-foreground">
                  No judged sessions yet - scores appear after the first nightly run.
                </p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-border text-left text-xs text-muted-foreground">
                        <th className="py-2 pr-3 font-medium">Rubric item</th>
                        <th className="py-2 px-3 text-right font-medium">Versions (old → new)</th>
                      </tr>
                    </thead>
                    <tbody>
                      {summary.items.filter(hasData).map((item) => (
                        <tr key={item.key} className="border-b border-border/50 last:border-0">
                          <td className="py-2 pr-3 font-medium">
                            <span className="flex items-center gap-1.5">
                              {RUBRIC_LABELS[item.key] ?? item.key}
                              {item.regression && (
                                <AlertTriangle className="h-3.5 w-3.5 text-amber-500" />
                              )}
                            </span>
                          </td>
                          <td className="py-2 px-3 text-right tabular-nums">
                            {versionColumns(item).map((v, i, arr) => (
                              <span
                                key={v.prompt_version}
                                title={`${v.prompt_version} · ${v.pass} pass · ${v.fail} fail · ${v.na} n/a`}
                                className={
                                  item.regression && i === arr.length - 1
                                    ? "font-semibold text-amber-600 dark:text-amber-500"
                                    : undefined
                                }
                              >
                                {i > 0 && <span className="text-muted-foreground"> → </span>}
                                {ratioLabel(v)} ({pctLabel(v.pass_rate)})
                              </span>
                            ))}
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
                Recent fails
              </p>
              {summary.recent_fails.length === 0 ? (
                <p className="flex items-center gap-1.5 text-sm text-muted-foreground">
                  <ShieldCheck className="h-3.5 w-3.5" />
                  None on record - every checked session held up.
                </p>
              ) : (
                <div className="space-y-3">
                  {summary.recent_fails.map((f, i) => (
                    <div
                      key={`${f.session_id}:${f.rubric_key}:${i}`}
                      className="rounded-xl border border-border bg-background/50 p-3"
                    >
                      <div className="flex flex-wrap items-center gap-1.5">
                        <Badge variant="secondary">{RUBRIC_LABELS[f.rubric_key] ?? f.rubric_key}</Badge>
                        <span className="ml-auto text-xs text-muted-foreground">
                          {f.artifact_date && `${formatDay(f.artifact_date)} · `}
                          session {f.session_id.slice(0, 8)}
                        </span>
                      </div>
                      <p className="mt-1.5 text-sm leading-relaxed">{f.reason}</p>
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
