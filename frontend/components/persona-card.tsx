"use client";

// Coach personas: a frontend naming/presentation layer over Settings.coach_style.
// The API is unchanged — coach_style still stores "default" | "chill" | "strict".
// Portraits are illustration PNGs in /public/coaches (cropped from Will's
// source art in /images): a full running/standing pose for the setup wizard,
// a square head crop for the compact Settings cards.

import * as React from "react";
import { Check } from "lucide-react";
import type { Settings } from "@/lib/types";
import { cn } from "@/lib/utils";

type CoachStyle = Settings["coach_style"];

export interface Persona {
  style: CoachStyle;
  name: string;
  tagline: string;
  flavor: string;
  /** /public paths: full pose (wizard) and head crop (settings). */
  fullSrc: string;
  headSrc: string;
  /** Static Tailwind classes for the selected ring, per-coach palette. */
  selectedClasses: string;
}

export const PERSONAS: Persona[] = [
  {
    style: "default",
    name: "Coach Sam",
    tagline: "Balanced and data-driven.",
    flavor: "A balanced mix of workouts, always grounded in your numbers.",
    fullSrc: "/coaches/sam-full.png",
    headSrc: "/coaches/sam-head.png",
    selectedClasses: "border-sky-500 ring-2 ring-sky-500/40",
  },
  {
    style: "chill",
    name: "Coach Koa",
    tagline: "Zero jargon, all good vibes.",
    flavor: "Expect fartleks, relaxed progressions, and plain-language advice.",
    fullSrc: "/coaches/koa-full.png",
    headSrc: "/coaches/koa-head.png",
    selectedClasses: "border-orange-500 ring-2 ring-orange-500/40",
  },
  {
    style: "strict",
    name: "Coach Viktoria",
    tagline: "No excuses — but never past your limits.",
    flavor: "Expect track intervals and tempo blocks. Recovery rules still always win.",
    fullSrc: "/coaches/viktoria-full.png",
    headSrc: "/coaches/viktoria-head.png",
    selectedClasses: "border-purple-500 ring-2 ring-purple-500/40",
  },
];

export function PersonaCard({
  persona,
  selected,
  onSelect,
  disabled,
  variant = "head",
}: {
  persona: Persona;
  selected: boolean;
  onSelect: () => void;
  disabled?: boolean;
  /** "full" shows the whole pose (wizard); "head" a round avatar (settings). */
  variant?: "full" | "head";
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      disabled={disabled}
      aria-pressed={selected}
      className={cn(
        "relative flex flex-1 flex-col items-center gap-2 rounded-2xl border border-border bg-card text-center transition-all",
        variant === "full" ? "overflow-hidden p-0 pb-4" : "p-4",
        "hover:border-muted-foreground/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        "disabled:pointer-events-none disabled:opacity-60",
        selected && persona.selectedClasses,
      )}
    >
      {selected && (
        <span className="absolute right-2.5 top-2.5 z-10 flex h-5 w-5 items-center justify-center rounded-full bg-accent text-accent-foreground">
          <Check className="h-3 w-3" strokeWidth={3} />
        </span>
      )}
      {variant === "full" ? (
        <img
          src={persona.fullSrc}
          alt={`Portrait of ${persona.name}`}
          className="aspect-[16/17] w-full object-cover"
        />
      ) : (
        <img
          src={persona.headSrc}
          alt={`Portrait of ${persona.name}`}
          className="h-24 w-24 rounded-full border border-border object-cover"
        />
      )}
      <span className={cn("text-sm font-semibold leading-tight", variant === "full" && "px-4")}>
        {persona.name}
      </span>
      <span className="px-4 text-xs font-medium text-muted-foreground">{persona.tagline}</span>
      <span className="px-4 text-xs leading-relaxed text-muted-foreground/80">{persona.flavor}</span>
    </button>
  );
}
