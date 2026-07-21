"use client";

// The coach's voice, embedded — avatar + name + what they have to say. Shared
// by the Today workout card, the Week day rows, and the daily review note, so
// the coach speaks with one consistent presence everywhere (replaces the old
// lightbulb-next-to-jargon treatment on the Week page).

import * as React from "react";
import { ThumbsDown, ThumbsUp } from "lucide-react";
import type { FeedbackState } from "@/lib/types";
import { api, safe } from "@/lib/api";
import { useCoach } from "@/components/coach-provider";
import type { Persona } from "@/components/persona-card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useToast } from "@/components/ui/toast";
import { cn } from "@/lib/utils";

/** Wiring for the quality thumbs: which artifact this note is, and my rating. */
export type CoachNoteFeedback = {
  surface: "coach_note" | "execution_analysis";
  ref: string; // review date ISO, or activity id as string
  state: FeedbackState;
};

// Thumbs-down reason chips (multi-select). Keys are the wire tags.
const DOWN_TAGS: Array<{ tag: string; label: string }> = [
  { tag: "wrong", label: "Wrong or ungrounded" },
  { tag: "off_tone", label: "Off tone" },
  { tag: "too_long", label: "Too long" },
  { tag: "not_useful", label: "Not useful" },
];

/**
 * The two quality thumbs, bottom-right of the note. 👍 posts immediately
 * (optimistic fill); 👎 opens a small popover with the reason chips + an
 * optional comment. Re-tapping either thumb changes the rating.
 */
function FeedbackThumbs({ feedback }: { feedback: CoachNoteFeedback }) {
  // Local override wins over the server-provided state once the athlete acts.
  const [override, setOverride] = React.useState<FeedbackState | undefined>(undefined);
  const state = override !== undefined ? override : feedback.state;
  const rating = state?.rating ?? null;

  const [open, setOpen] = React.useState(false);
  const [tags, setTags] = React.useState<string[]>([]);
  const [comment, setComment] = React.useState("");
  const [sending, setSending] = React.useState(false);
  const rootRef = React.useRef<HTMLDivElement>(null);
  const { toast } = useToast();

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

  const post = async (next: NonNullable<FeedbackState>) => {
    const previous = state;
    setOverride(next); // optimistic
    const res = await safe(
      api.postFeedback({
        surface: feedback.surface,
        ref: feedback.ref,
        rating: next.rating,
        tags: next.tags,
        comment: next.comment,
      }),
    );
    if (res) setOverride(res.feedback);
    else {
      setOverride(previous);
      toast("Couldn't save your feedback - try again.", "error");
    }
  };

  const thumbUp = () => {
    setOpen(false);
    if (rating === 1) return; // already up — nothing to change
    post({ rating: 1, tags: [], comment: "" });
  };

  const openDown = () => {
    // Pre-fill from the existing rating so re-opening edits, not restarts.
    setTags(state?.rating === -1 ? state.tags : []);
    setComment(state?.rating === -1 ? state.comment : "");
    setOpen((o) => !o);
  };

  const sendDown = async () => {
    setSending(true);
    await post({ rating: -1, tags, comment: comment.trim() });
    setSending(false);
    setOpen(false);
  };

  const thumbClass = (active: boolean) =>
    cn(
      // negative margin keeps layout tight while the hit area stays finger-friendly
      "-m-1.5 inline-flex min-h-9 min-w-9 items-center justify-center rounded-md p-1.5 transition-colors",
      active ? "text-accent" : "text-muted-foreground/70 hover:text-foreground",
    );

  return (
    <div ref={rootRef} className="relative mt-1 flex justify-end gap-2">
      <button
        type="button"
        aria-label="Good note"
        aria-pressed={rating === 1}
        onClick={thumbUp}
        className={cn(
          thumbClass(rating === 1),
          rating !== 1 && "sm:opacity-0 sm:transition-opacity sm:group-hover/note:opacity-100 sm:focus-visible:opacity-100",
        )}
      >
        <ThumbsUp className={cn("h-3.5 w-3.5", rating === 1 && "fill-current")} />
      </button>
      <button
        type="button"
        aria-label="Not a good note"
        aria-pressed={rating === -1}
        aria-expanded={open}
        onClick={openDown}
        className={cn(
          thumbClass(rating === -1 || open),
          rating !== -1 && !open && "sm:opacity-0 sm:transition-opacity sm:group-hover/note:opacity-100 sm:focus-visible:opacity-100",
        )}
      >
        <ThumbsDown className={cn("h-3.5 w-3.5", rating === -1 && "fill-current")} />
      </button>

      {open && (
        <div className="absolute right-0 top-full z-50 mt-1.5 w-64 max-w-[calc(100vw-2rem)] rounded-xl border border-border bg-card p-3 shadow-lg">
          <p className="mb-2 text-xs font-medium text-foreground">What was off?</p>
          <div className="flex flex-wrap gap-1.5">
            {DOWN_TAGS.map(({ tag, label }) => {
              const selected = tags.includes(tag);
              return (
                <button
                  key={tag}
                  type="button"
                  aria-pressed={selected}
                  onClick={() =>
                    setTags((t) => (selected ? t.filter((x) => x !== tag) : [...t, tag]))
                  }
                  className={cn(
                    "rounded-full border px-2.5 py-1 text-xs font-medium transition-colors",
                    selected
                      ? "border-accent/50 bg-accent/15 text-accent"
                      : "border-border text-muted-foreground hover:text-foreground",
                  )}
                >
                  {label}
                </button>
              );
            })}
          </div>
          <div className="mt-2 flex items-center gap-2">
            <Input
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              placeholder="Anything else? (optional)"
              maxLength={300}
              className="h-8 flex-1 sm:text-xs"
              onKeyDown={(e) => {
                if (e.key === "Enter") sendDown();
              }}
            />
            <Button size="sm" onClick={sendDown} disabled={sending}>
              Send
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

export function CoachNote({
  note,
  persona: personaProp,
  ask,
  feedback,
  collapsible = false,
  className,
}: {
  note: string;
  persona?: Persona | null;
  ask?: { label: string; onClick: () => void };
  /** Enable the quality thumbs on this note; absent = unrated (week rationales etc.). */
  feedback?: CoachNoteFeedback;
  /** Collapse to a one-line preview with a More/Less toggle (Week page). */
  collapsible?: boolean;
  className?: string;
}) {
  const fallback = useCoach();
  const persona = personaProp ?? fallback;
  const [open, setOpen] = React.useState(!collapsible);
  if (!note) return null;

  return (
    <div className={cn("group/note rounded-xl bg-muted/50 px-3.5 py-3", className)}>
      <div className="flex items-center gap-2">
        {persona && (
          <img
            src={persona.headSrc}
            alt={persona.name}
            className="h-6 w-6 rounded-full border border-border object-cover"
          />
        )}
        <span className="text-sm font-medium">{persona?.name ?? "Coach"}</span>
        {collapsible && (
          <button
            type="button"
            onClick={() => setOpen((o) => !o)}
            className="ml-auto text-xs font-medium text-muted-foreground hover:text-foreground"
            aria-expanded={open}
          >
            {open ? "Less" : "More"}
          </button>
        )}
      </div>
      <p
        className={cn(
          "mt-1.5 text-sm leading-relaxed text-muted-foreground",
          collapsible && !open && "line-clamp-1",
        )}
      >
        {note}
      </p>
      {ask && open && (
        <button
          type="button"
          onClick={ask.onClick}
          className="mt-2 text-sm font-medium text-accent hover:underline"
        >
          {ask.label}
        </button>
      )}
      {feedback && open && (
        // Keyed so local optimistic state resets when the artifact changes.
        <FeedbackThumbs key={`${feedback.surface}:${feedback.ref}`} feedback={feedback} />
      )}
    </div>
  );
}
