"use client";

import Link from "next/link";
import { Check, ChevronRight, ListChecks } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

interface Item {
  label: string;
  done: boolean;
  href: string;
}

function ChecklistRow({ item }: { item: Item }) {
  const inner = (
    <>
      <span
        className={cn(
          "flex h-5 w-5 shrink-0 items-center justify-center rounded-full border",
          item.done
            ? "border-success bg-success text-success-foreground"
            : "border-muted-foreground/40",
        )}
      >
        {item.done && <Check className="h-3 w-3" strokeWidth={3} />}
      </span>
      <span
        className={cn(
          "flex-1 text-sm",
          item.done ? "text-muted-foreground line-through decoration-muted-foreground/50" : "font-medium",
        )}
      >
        {item.label}
      </span>
      {!item.done && <ChevronRight className="h-4 w-4 text-muted-foreground" />}
    </>
  );

  if (item.done) {
    return <div className="flex min-h-10 items-center gap-3 px-2 py-1.5">{inner}</div>;
  }
  return (
    <Link
      href={item.href}
      className="flex min-h-10 items-center gap-3 rounded-xl px-2 py-1.5 transition-colors hover:bg-muted/60"
    >
      {inner}
    </Link>
  );
}

/**
 * Compact "Getting started" checklist shown on the Today dashboard until all
 * three items are done — completion is the dismissal.
 */
export function GettingStartedCard({
  garminConnected,
  tutorialDone,
  hasRace,
}: {
  garminConnected: boolean;
  tutorialDone: boolean;
  hasRace: boolean;
}) {
  if (garminConnected && tutorialDone && hasRace) return null;

  const items: Item[] = [
    { label: "Connect Garmin", done: garminConnected, href: "/welcome?step=2" },
    { label: "Meet your coach", done: tutorialDone, href: "/welcome?replay=1" },
    { label: "Add a race", done: hasRace, href: "/races" },
  ];
  const doneCount = items.filter((i) => i.done).length;

  return (
    <Card className="border-accent/40">
      <CardContent className="p-4">
        <div className="mb-1.5 flex items-center justify-between gap-2 px-2">
          <p className="inline-flex items-center gap-2 text-sm font-semibold">
            <ListChecks className="h-4 w-4 text-accent" />
            Getting started
          </p>
          <span className="text-xs tabular-nums text-muted-foreground">{doneCount}/3</span>
        </div>
        <div>
          {items.map((item) => (
            <ChecklistRow key={item.label} item={item} />
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
