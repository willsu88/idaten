"use client";

// Shows which plan mode is active — "Following Garmin Coach" (editor: Garmin
// writes the plan, Idaten tweaks it) vs "Following Coach <persona>" (author:
// Idaten writes the whole plan). Hover/tap opens a tooltip explaining the
// difference and pointing to where to change it (Settings → Plan source).

import * as React from "react";
import Link from "next/link";
import { Watch, Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";
import { coachFirstName, useCoach } from "@/components/coach-provider";

export function CoachModeBadge({
  mode,
  className,
}: {
  mode: "editor" | "author" | null | undefined;
  className?: string;
}) {
  const persona = useCoach();
  const [open, setOpen] = React.useState(false);
  const [align, setAlign] = React.useState<"left" | "center" | "right">("center");
  const rootRef = React.useRef<HTMLSpanElement>(null);

  React.useEffect(() => {
    if (!open) return;
    const onPointerDown = (e: PointerEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  if (!mode) return null;

  const first = persona ? coachFirstName(persona) : "Idaten";
  const editor = mode === "editor";
  const label = editor ? "Following Garmin Coach" : `Following ${persona?.name ?? "Idaten"}`;
  const body = editor
    ? `Garmin Coach writes your plan; ${first} reviews it and suggests tweaks. To have ${first} author the whole plan instead, change it under Settings → Plan source.`
    : `${persona?.name ?? "Idaten"} writes your whole plan. To follow your Garmin Coach plan instead, change it under Settings → Plan source.`;
  const Icon = editor ? Watch : Sparkles;

  const show = () => {
    const rect = rootRef.current?.getBoundingClientRect();
    if (rect) {
      const popHalf = 144; // half of w-72
      const center = rect.left + rect.width / 2;
      if (center - popHalf < 12) setAlign("left");
      else if (center + popHalf > window.innerWidth - 12) setAlign("right");
      else setAlign("center");
    }
    setOpen(true);
  };

  return (
    <span ref={rootRef} className={cn("relative inline-flex", className)}>
      <button
        type="button"
        aria-label={label}
        aria-expanded={open}
        onClick={() => (open ? setOpen(false) : show())}
        onPointerEnter={(e) => {
          if (e.pointerType === "mouse") show();
        }}
        onPointerLeave={(e) => {
          if (e.pointerType === "mouse") setOpen(false);
        }}
        className={cn(
          "inline-flex items-center gap-1 rounded-full bg-muted px-2.5 py-0.5 text-xs font-medium text-muted-foreground transition-colors hover:text-foreground",
          open && "text-foreground",
        )}
      >
        <Icon className="h-3 w-3" />
        {label}
      </button>
      {open && (
        <span
          role="tooltip"
          className={cn(
            "absolute top-full z-50 mt-1.5 block w-72 max-w-[calc(100vw-2rem)] rounded-xl border border-border bg-card p-3 text-left shadow-lg",
            align === "center" && "left-1/2 -translate-x-1/2",
            align === "left" && "left-0",
            align === "right" && "right-0",
          )}
        >
          <span className="mb-1 block text-xs font-bold text-foreground">{label}</span>
          <span className="block text-xs font-normal leading-relaxed text-muted-foreground">
            {body}{" "}
            <Link href="/settings" className="font-medium text-accent hover:underline">
              Open Settings
            </Link>
          </span>
        </span>
      )}
    </span>
  );
}
