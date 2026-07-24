"use client";

import * as React from "react";
import type { Settings } from "@/lib/types";
import { cn } from "@/lib/utils";
import { InfoTip } from "@/components/metric-info";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Select } from "@/components/ui/select";

const FOCUS_LABELS: Record<Settings["strength"]["focus"], string> = {
  coach: "Let the coach decide",
  full: "Full body",
  upper: "Upper body",
  lower: "Lower body",
};

/**
 * The weekly-target contract: how many strength sessions the athlete wants,
 * and a focus preference. The target settles WHETHER strength is wanted — the
 * coach then only decides when and what (and treats it as guidance, not a
 * quota). Optimistic save via onChange, like every other Settings control.
 */
export function StrengthTrainingCard({
  settings,
  onChange,
}: {
  settings: Settings;
  onChange: (strength: Settings["strength"]) => void;
}) {
  const strength = settings.strength;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Strength training</CardTitle>
        <CardDescription>
          Optional - have your coach plan strength sessions alongside your runs
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="space-y-1.5">
          <p className="flex items-center text-sm font-medium">
            Sessions per week
            <InfoTip
              className="ml-1"
              title="How sessions get scheduled"
              body={
                "When Idaten writes your plan, strength sessions are placed into " +
                "your week automatically - around your runs, never before a hard " +
                "day. When you follow a Garmin Coach plan, Garmin owns the run " +
                "week, so your coach proposes placements instead (in the morning " +
                "note or chat) and nothing is scheduled until you accept. Either " +
                "way this number is guidance, not a quota - on a rough week the " +
                "coach may place fewer and say why."
              }
            />
          </p>
          <div className="flex gap-2" role="radiogroup" aria-label="Strength sessions per week">
            {[0, 1, 2, 3].map((n) => (
              <button
                key={n}
                type="button"
                role="radio"
                aria-checked={strength.sessions_per_week === n}
                onClick={() => onChange({ ...strength, sessions_per_week: n })}
                className={cn(
                  "h-10 flex-1 rounded-lg border text-sm font-medium transition-colors",
                  strength.sessions_per_week === n
                    ? "border-accent bg-accent/10 text-accent"
                    : "border-border text-muted-foreground hover:border-accent/40",
                )}
              >
                {n === 0 ? "Off" : n}
              </button>
            ))}
          </div>
        </div>
        {strength.sessions_per_week > 0 && (
          <div className="space-y-1.5">
            <p className="text-sm font-medium">Focus</p>
            <Select
              value={strength.focus}
              aria-label="Strength focus"
              onChange={(e) =>
                onChange({ ...strength, focus: e.target.value as Settings["strength"]["focus"] })
              }
            >
              {Object.entries(FOCUS_LABELS).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </Select>
            <p className="text-xs text-muted-foreground">
              The coach places sessions around your runs and adapts the focus —
              an open niggle biases toward prevention work regardless.
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
