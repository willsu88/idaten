"use client";

// First-run coach pointer: an inline callout at the top of a page's content,
// voiced by the selected persona and dismissed once per page id via
// settings.page_hints_seen. Same subtle styling as the Today coach note —
// not a modal, not an anchored overlay.

import * as React from "react";
import type { Settings } from "@/lib/types";
import { api, safe } from "@/lib/api";
import { useCoach } from "@/components/coach-provider";

export type HintPage = "week" | "trends" | "races" | "activities";

// 3 personas × 4 pages, one in-voice sentence each (≤ ~120 chars).
const HINTS: Record<Settings["coach_style"], Record<HintPage, string>> = {
  default: {
    week: "Your 7-day plan lives here — it adapts to your recovery data, so check back after each sync.",
    trends: "These charts track fitness and fatigue over time — the same numbers I use to shape your plan.",
    races: "Set a goal race here and I'll keep comparing your predicted time against it as training builds.",
    activities: "Every synced activity lands here — rate the effort and I'll calibrate your plan with it.",
  },
  chill: {
    week: "Here's your week at a glance. Nothing's set in stone — ping me anytime and we'll shuffle things.",
    trends: "All your body's signals in one place. Don't sweat every dip — the long curve is what counts.",
    races: "Got a race in mind? Drop it here and we'll cruise toward it, one steady week at a time.",
    activities: "Your workout diary. Tap a run, tell me how it felt — that helps way more than numbers do.",
  },
  strict: {
    week: "This is your week's plan. Follow it with intent — and tell me immediately when life gets in the way.",
    trends: "Your numbers don't lie. Watch load and recovery here — I do, and I plan accordingly.",
    races: "A goal race sharpens everything. Set it here, then we train with purpose — no wasted sessions.",
    activities: "Review every session here and rate your effort honestly. Honest data makes hard training safe.",
  },
};

export function CoachHint({ page }: { page: HintPage }) {
  const persona = useCoach();
  const [visible, setVisible] = React.useState(false);

  React.useEffect(() => {
    let cancelled = false;
    (async () => {
      const settings = await safe(api.getSettings());
      if (cancelled || !settings) return;
      if (settings.tutorial_done && !settings.page_hints_seen.includes(page)) {
        setVisible(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [page]);

  const dismiss = async () => {
    setVisible(false);
    try {
      // Refetch-before-write merge (same anti-clobber pattern as
      // tutorial_done), PUTting only the page_hints_seen key.
      const current = await api.getSettings();
      if (!current.page_hints_seen.includes(page)) {
        await api.putSettings({ page_hints_seen: [...current.page_hints_seen, page] });
      }
    } catch {
      // Non-fatal: the hint simply reappears on the next visit.
    }
  };

  if (!visible || !persona) return null;

  return (
    <div className="mb-5 rounded-xl bg-muted/50 px-3.5 py-3">
      <div className="flex items-center gap-2">
        <img
          src={persona.headSrc}
          alt={persona.name}
          className="h-6 w-6 rounded-full border border-border object-cover"
        />
        <span className="text-sm font-medium">{persona.name}</span>
      </div>
      <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">
        {HINTS[persona.style][page]}
      </p>
      <button
        type="button"
        onClick={dismiss}
        className="mt-2 text-sm font-medium text-accent hover:underline"
      >
        Got it
      </button>
    </div>
  );
}
