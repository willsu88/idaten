"use client";

import * as React from "react";
import { useTheme } from "next-themes";
import type { TooltipProps } from "recharts";

export interface ChartTheme {
  grid: string;
  axis: string;
  accent: string;
  blue: string;
  indigo: string;
  teal: string;
  amber: string;
  muted: string;
  areaPos: string;
  areaNeg: string;
}

const LIGHT: ChartTheme = {
  grid: "#e4e4e7",
  axis: "#71717a",
  accent: "#ea580c",
  blue: "#0284c7",
  indigo: "#4f46e5",
  teal: "#0d9488",
  amber: "#d97706",
  muted: "#a1a1aa",
  areaPos: "#059669",
  areaNeg: "#dc2626",
};

const DARK: ChartTheme = {
  grid: "#27272a",
  axis: "#a1a1aa",
  accent: "#fb923c",
  blue: "#38bdf8",
  indigo: "#818cf8",
  teal: "#2dd4bf",
  amber: "#fbbf24",
  muted: "#52525b",
  areaPos: "#34d399",
  areaNeg: "#f87171",
};

export function useChartTheme(): ChartTheme {
  const { resolvedTheme } = useTheme();
  const [mounted, setMounted] = React.useState(false);
  React.useEffect(() => setMounted(true), []);
  return mounted && resolvedTheme === "dark" ? DARK : LIGHT;
}

export function ChartTooltip({
  active,
  payload,
  label,
  formatter,
}: TooltipProps<number, string> & {
  formatter?: (value: number, name: string) => string;
}) {
  if (!active || !payload || payload.length === 0) return null;
  return (
    <div className="rounded-xl border border-border bg-card px-3 py-2 text-xs shadow-lg">
      <p className="mb-1 font-medium text-muted-foreground">{label}</p>
      {payload.map((entry) =>
        entry.value == null ? null : (
          <p key={String(entry.dataKey)} className="flex items-center gap-1.5 tabular-nums">
            <span
              className="inline-block h-2 w-2 rounded-full"
              style={{ background: entry.color ?? entry.stroke ?? undefined }}
            />
            <span className="text-muted-foreground">{entry.name}:</span>
            <span className="font-semibold text-foreground">
              {formatter
                ? formatter(Number(entry.value), String(entry.name))
                : Number(entry.value).toFixed(1)}
            </span>
          </p>
        ),
      )}
    </div>
  );
}
