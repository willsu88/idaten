"use client";

// Shared thread + composer, rendered by BOTH the /chat page and the floating
// panel. All state comes from ChatProvider; only presentation lives here.

import * as React from "react";
import { Check, Loader2, SendHorizonal, Sparkles, Square, X } from "lucide-react";
import { stopChat } from "@/lib/api";
import { EditProposalCard } from "@/components/edit-proposal-card";
import { Markdown } from "@/components/chat/markdown";
import { SLASH_SHORTCUTS, useChat } from "@/components/chat/chat-provider";
import { coachFirstName, useCoach } from "@/components/coach-provider";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { APP_LOCALE, cn } from "@/lib/utils";

const TOOL_LABELS: Record<string, string> = {
  get_training_data: "Looking at your training data…",
  get_health_data: "Checking your recovery data…",
  update_plan: "Drafting a plan change…",
};

function toolLabel(name: string, status: "running" | "done") {
  const base = TOOL_LABELS[name] ?? `Running ${name.replace(/_/g, " ")}…`;
  return status === "done" ? base.replace(/…$/, "") : base;
}

/**
 * Muted bubble for a backend-refused send. For the one-stream-conflict 429 the
 * composer's stop button may not be visible (the stuck stream can belong to a
 * dropped connection or another tab), so the notice itself offers the stop.
 */
function NoticeBubble({
  content,
  canStop,
  compact,
  indent,
}: {
  content: string;
  canStop?: boolean;
  compact?: boolean;
  indent: boolean;
}) {
  const [state, setState] = React.useState<"idle" | "stopping" | "stopped">("idle");
  const stop = async () => {
    setState("stopping");
    try {
      await stopChat();
      setState("stopped");
    } catch {
      setState("idle");
    }
  };
  return (
    <div className={cn("flex justify-start", indent && "pl-8")}>
      <div
        className={cn(
          "max-w-[85%] rounded-2xl border border-dashed border-border bg-muted/50 px-4 py-2.5 text-sm leading-relaxed text-muted-foreground",
          !compact && "md:max-w-[70%]",
        )}
      >
        {state === "stopped" ? "Stopped — send your message again." : content}
        {canStop && state !== "stopped" && (
          <button
            type="button"
            onClick={stop}
            disabled={state === "stopping"}
            className="mt-1.5 block text-xs font-medium text-accent underline underline-offset-2 disabled:opacity-50"
          >
            {state === "stopping" ? "Stopping…" : "Stop that reply now"}
          </button>
        )}
      </div>
    </div>
  );
}

// One-line descriptions for the local /help item (the prompts themselves live
// server-side; the client only knows the command names).
const HELP_COMMANDS = [
  { command: "/week", description: "Summarize your week and how the plan is going." },
  { command: "/replan", description: "Review recent training and propose plan adjustments." },
  { command: "/race-plan", description: "Build a race plan for your goal race." },
  {
    command: "/sport",
    description: "Plan a day around another sport — add what/when, e.g. /sport surfing saturday ~90min.",
  },
  { command: "/help", description: "Show this help (nothing is sent to the coach)." },
];

/** Local, non-persisted /help response — rendered like an assistant card. */
function HelpCard({ coachName, compact }: { coachName: string; compact: boolean }) {
  return (
    <div
      className={cn(
        "max-w-[85%] space-y-3 rounded-2xl border border-border bg-card px-4 py-3 text-sm leading-relaxed",
        !compact && "md:max-w-[70%]",
      )}
    >
      <div>
        <p className="mb-1.5 font-medium">Shortcuts</p>
        <ul className="space-y-1">
          {HELP_COMMANDS.map((c) => (
            <li key={c.command} className="flex items-baseline gap-2">
              <code className="shrink-0 rounded bg-muted px-1.5 py-0.5 font-mono text-xs text-accent">
                {c.command}
              </code>
              <span className="text-muted-foreground">{c.description}</span>
            </li>
          ))}
        </ul>
      </div>
      <p className="text-muted-foreground">
        {coachName} answers with your real Garmin data — training, recovery, and race readiness.
        Plan changes arrive as proposals you approve before they apply, and you can log day
        intents for other sports so the week is planned around them.
      </p>
      <p className="text-muted-foreground">
        While a reply is streaming, the send button becomes a stop button — press it to cut the
        reply short.
      </p>
    </div>
  );
}

export function ChatConversation({
  compact = false,
  sessionsOpen,
  setSessionsOpen,
}: {
  /** Panel mode: tighter bubbles/cards for the ~400px docked panel. */
  compact?: boolean;
  sessionsOpen: boolean;
  setSessionsOpen: (open: boolean) => void;
}) {
  const {
    sessions,
    sessionId,
    items,
    streaming,
    input,
    setInput,
    contextDate,
    setContextDate,
    send,
    openSession,
    placeholder,
    quota,
  } = useChat();
  const persona = useCoach();
  const bottomRef = React.useRef<HTMLDivElement>(null);
  const inputRef = React.useRef<HTMLTextAreaElement>(null);
  // Debounce the stop button: one POST per stream, re-enabled when it ends.
  const [stopPending, setStopPending] = React.useState(false);

  React.useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [items]);

  React.useEffect(() => {
    if (!streaming) setStopPending(false);
  }, [streaming]);

  const stop = async () => {
    setStopPending(true);
    try {
      // Ask the server to stop; the stream keeps being read until the
      // terminal "stopped" event arrives (the fetch is never aborted).
      await stopChat();
    } catch {
      setStopPending(false); // let the user retry
    }
  };

  const showSlashMenu = input.startsWith("/") && !input.includes(" ");
  const slashMatches = SLASH_SHORTCUTS.filter((s) => s.command.startsWith(input));

  // Daily chat cap: quiet until nearly out, then a hint; at the cap the
  // composer explains itself instead of letting a send bounce off a 429.
  const remaining = quota && quota.cap != null ? Math.max(0, quota.cap - quota.used) : null;
  const quotaExhausted = remaining === 0;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {sessionsOpen && (
        <Card className="mb-4 max-h-56 overflow-y-auto">
          <CardContent className="p-2">
            {sessions.length === 0 ? (
              <p className="px-3 py-2 text-sm text-muted-foreground">No previous sessions.</p>
            ) : (
              sessions.map((s) => (
                <button
                  key={s.id}
                  type="button"
                  onClick={() => {
                    openSession(s.id);
                    setSessionsOpen(false);
                  }}
                  className={cn(
                    "flex w-full items-center justify-between rounded-lg px-3 py-2 text-left text-sm hover:bg-muted",
                    s.id === sessionId && "bg-muted font-medium",
                  )}
                >
                  <span className="truncate">{s.title || "Untitled chat"}</span>
                  <span className="ml-3 shrink-0 text-xs text-muted-foreground">
                    {new Date(s.created_at).toLocaleDateString(APP_LOCALE)}
                  </span>
                </button>
              ))
            )}
          </CardContent>
        </Card>
      )}

      <div className="flex-1 space-y-4 overflow-y-auto pb-4 pr-1">
        {items.length === 0 && (
          <div className="mt-10 flex flex-col items-center gap-3 text-center">
            <span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-accent/10 text-accent">
              <Sparkles className="h-6 w-6" />
            </span>
            <p className="text-sm text-muted-foreground">
              Ask about your plan, your recovery, or type{" "}
              <code className="rounded bg-muted px-1">/</code> for shortcuts.
            </p>
          </div>
        )}

        {items.map((item, index) => {
          if (item.kind === "tool") {
            return (
              <div key={item.id} className={cn("flex justify-start", persona && "pl-8")}>
                <span className="inline-flex items-center gap-1.5 rounded-full bg-muted px-3 py-1 text-xs text-muted-foreground">
                  {item.status === "running" ? (
                    <Loader2 className="h-3 w-3 animate-spin" />
                  ) : (
                    <Check className="h-3 w-3 text-success" />
                  )}
                  {toolLabel(item.name, item.status)}
                </span>
              </div>
            );
          }
          if (item.kind === "notice") {
            // Backend refused the send (rate limit / too long) — muted
            // assistant-style bubble, no spinner, no toast.
            return (
              <NoticeBubble
                key={item.id}
                content={item.content}
                canStop={item.canStop}
                compact={compact}
                indent={persona != null}
              />
            );
          }
          if (item.kind === "help") {
            return (
              <div key={item.id} className={cn("flex justify-start", persona && "pl-8")}>
                <HelpCard
                  coachName={persona ? coachFirstName(persona) : "Your coach"}
                  compact={compact}
                />
              </div>
            );
          }
          if (item.kind === "edit") {
            // Resolved edits from history collapse to a receipt line — no stale buttons.
            if (item.edit.status !== "pending") {
              const accepted = item.edit.status === "accepted";
              return (
                <div key={item.id} className="flex justify-start">
                  <span className="inline-flex items-center gap-1.5 rounded-full border border-border bg-muted px-3 py-1 text-xs text-muted-foreground">
                    {accepted ? <Check className="h-3 w-3 text-success" /> : <X className="h-3 w-3" />}
                    Plan edit {item.edit.status}: {item.edit.summary}
                  </span>
                </div>
              );
            }
            return (
              <div key={item.id} className={cn(!compact && "max-w-xl")}>
                <EditProposalCard edit={item.edit} compact />
              </div>
            );
          }
          // Slash-command messages (live-sent or kind "shortcut" from history)
          // render as a compact command chip instead of a normal bubble.
          if (item.role === "user" && item.shortcut) {
            return (
              <div key={item.id} className="flex justify-end">
                <span className="max-w-[85%] break-words rounded-full border border-border bg-muted px-3 py-1 font-mono text-xs text-foreground">
                  {item.content}
                </span>
              </div>
            );
          }
          // Coach avatar on the first assistant message of a consecutive group;
          // later messages in the group keep an empty slot so bubbles align.
          const prev = items[index - 1];
          const groupHead = !(prev && prev.kind === "message" && prev.role === "assistant");
          return (
            <div
              key={item.id}
              className={cn(
                "flex",
                item.role === "user" ? "justify-end" : "justify-start",
                item.role === "assistant" && persona && "gap-2",
              )}
            >
              {item.role === "assistant" && persona && (
                <span className="w-6 shrink-0 self-start pt-1">
                  {groupHead && (
                    <img
                      src={persona.headSrc}
                      alt={persona.name}
                      className="h-6 w-6 rounded-full border border-border object-cover"
                    />
                  )}
                </span>
              )}
              <div
                className={cn(
                  "max-w-[92%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed sm:max-w-[85%]",
                  !compact && "md:max-w-[70%]",
                  item.role === "user"
                    ? "whitespace-pre-wrap bg-accent text-accent-foreground"
                    : "border border-border bg-card",
                )}
              >
                {item.content ? (
                  item.role === "assistant" ? (
                    <Markdown content={item.content} />
                  ) : (
                    item.content
                  )
                ) : (
                  streaming && <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
                )}
                {item.role === "assistant" && item.stopped && (
                  <p className="mt-1.5 text-xs text-muted-foreground">— stopped</p>
                )}
              </div>
            </div>
          );
        })}
        <div ref={bottomRef} />
      </div>

      <div className="relative border-t border-border pt-3">
        {showSlashMenu && slashMatches.length > 0 && (
          <div className="absolute bottom-full left-0 z-20 mb-2 w-72 max-w-full overflow-hidden rounded-xl border border-border bg-card shadow-lg">
            {slashMatches.map((s) => (
              <button
                key={s.command}
                type="button"
                onClick={() => {
                  // Insert the command itself (+ space for optional details);
                  // expansion happens server-side.
                  setInput(`${s.command} `);
                  inputRef.current?.focus();
                }}
                className="flex w-full items-baseline gap-2 px-3 py-2 text-left text-sm hover:bg-muted"
              >
                <span className="font-mono text-accent">{s.command}</span>
                <span className="text-xs text-muted-foreground">{s.hint}</span>
              </button>
            ))}
          </div>
        )}
        {quotaExhausted ? (
          <p className="mb-1.5 text-xs text-muted-foreground">
            Daily limit reached ({quota?.cap} coach messages) - the coach is back at midnight.
          </p>
        ) : (
          remaining != null &&
          remaining <= 2 && (
            <p className="mb-1.5 text-xs text-muted-foreground">
              {remaining} coach {remaining === 1 ? "message" : "messages"} left today.
            </p>
          )
        )}
        {contextDate && (
          <p className="mb-1.5 text-xs text-muted-foreground">
            Context: workout on <span className="font-medium">{contextDate}</span>{" "}
            <button
              type="button"
              className="underline hover:text-foreground"
              onClick={() => setContextDate(undefined)}
            >
              clear
            </button>
          </p>
        )}
        <div className="flex items-end gap-2">
          <Textarea
            ref={inputRef}
            value={input}
            rows={1}
            // placeholder:* — a too-long (transient) placeholder ellipsizes on
            // one line instead of wrapping into the clipped second row.
            className="min-h-[44px] resize-none placeholder:overflow-hidden placeholder:text-ellipsis placeholder:whitespace-nowrap"
            placeholder={quotaExhausted ? "Daily limit reached - back at midnight" : placeholder}
            disabled={quotaExhausted}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send();
              }
            }}
          />
          {streaming ? (
            <Button
              size="icon"
              variant="outline"
              onClick={stop}
              disabled={stopPending}
              aria-label="Stop"
            >
              <Square className="h-3.5 w-3.5" fill="currentColor" />
            </Button>
          ) : (
            <Button
              size="icon"
              onClick={() => send()}
              disabled={!input.trim() || quotaExhausted}
              aria-label="Send"
            >
              <SendHorizonal className="h-4 w-4" />
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}
