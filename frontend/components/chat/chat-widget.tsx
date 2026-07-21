"use client";

// Floating chat bubble + panel, mounted once in the app shell on authed pages.
// Desktop: docked ~400px panel above the bubble. Mobile: full-screen sheet.
// Closing only hides the view — thread/stream state stays in ChatProvider.

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { History, Maximize2, MessageCircle, MessageSquarePlus, Sparkles, X } from "lucide-react";
import { ChatConversation } from "@/components/chat/chat-conversation";
import { useChat } from "@/components/chat/chat-provider";
import { useCoach } from "@/components/coach-provider";
import { cn } from "@/lib/utils";

export function ChatWidget() {
  const pathname = usePathname();
  const { panelOpen, togglePanel, closePanel, newSession, unread } = useChat();
  const persona = useCoach();
  const [sessionsOpen, setSessionsOpen] = React.useState(false);

  // The /chat page IS the chat — no bubble on top of it.
  if (pathname === "/chat" || pathname.startsWith("/chat/")) return null;

  return (
    <>
      {panelOpen && (
        <div
          role="dialog"
          aria-label="Coach chat"
          className={cn(
            // Mobile: full-screen sheet above the tab bar (z-50 > nav z-40).
            "fixed inset-0 z-50 flex flex-col bg-card",
            // Desktop: docked panel above the bubble.
            "md:inset-auto md:bottom-[5.5rem] md:right-6 md:h-[min(40rem,80vh)] md:w-[25rem] md:rounded-2xl md:border md:border-border md:shadow-2xl",
          )}
        >
          <header className="flex items-center gap-2 border-b border-border px-4 py-3 pt-[max(0.75rem,env(safe-area-inset-top))] md:pt-3">
            {persona ? (
              <img
                src={persona.headSrc}
                alt={persona.name}
                className="h-7 w-7 rounded-full border border-border object-cover"
              />
            ) : (
              <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-accent/10 text-accent">
                <Sparkles className="h-4 w-4" />
              </span>
            )}
            <p className="flex-1 truncate text-sm font-semibold">{persona?.name ?? "Coach"}</p>
            <button
              type="button"
              title="History"
              aria-label="Chat history"
              onClick={() => setSessionsOpen((v) => !v)}
              className={cn(
                "flex h-11 w-11 items-center justify-center rounded-lg hover:bg-muted md:h-8 md:w-8",
                sessionsOpen ? "text-accent" : "text-muted-foreground hover:text-foreground",
              )}
            >
              <History className="h-4 w-4" />
            </button>
            <button
              type="button"
              title="New chat"
              aria-label="New chat"
              onClick={() => {
                newSession();
                setSessionsOpen(false);
              }}
              className="flex h-11 w-11 items-center justify-center rounded-lg text-muted-foreground hover:bg-muted hover:text-foreground md:h-8 md:w-8"
            >
              <MessageSquarePlus className="h-4 w-4" />
            </button>
            <Link
              href="/chat"
              title="Open full page"
              aria-label="Open chat as full page"
              onClick={closePanel}
              className="flex h-11 w-11 items-center justify-center rounded-lg text-muted-foreground hover:bg-muted hover:text-foreground md:h-8 md:w-8"
            >
              <Maximize2 className="h-4 w-4" />
            </Link>
            <button
              type="button"
              title="Close"
              aria-label="Close chat"
              onClick={closePanel}
              className="flex h-11 w-11 items-center justify-center rounded-lg text-muted-foreground hover:bg-muted hover:text-foreground md:h-8 md:w-8"
            >
              <X className="h-4 w-4" />
            </button>
          </header>
          <div className="flex min-h-0 flex-1 flex-col px-4 pb-[max(1rem,env(safe-area-inset-bottom))] pt-3 md:pb-4">
            <ChatConversation compact sessionsOpen={sessionsOpen} setSessionsOpen={setSessionsOpen} />
          </div>
        </div>
      )}

      <button
        type="button"
        onClick={togglePanel}
        aria-label={panelOpen ? "Close coach chat" : "Open coach chat"}
        className={cn(
          "fixed z-40 flex h-[3.25rem] w-[3.25rem] items-center justify-center rounded-full bg-accent text-accent-foreground shadow-lg transition-transform hover:scale-105 active:scale-95",
          // Clear of the mobile tab bar (+ safe area); plain corner on desktop.
          "bottom-[calc(4.5rem+env(safe-area-inset-bottom))] right-4 md:bottom-6 md:right-6",
        )}
      >
        {panelOpen ? (
          <X className="h-5 w-5" />
        ) : persona ? (
          // Full-bleed round crop of the selected coach's head portrait.
          // (Rounded on the img itself so the unread dot isn't clipped.)
          <img
            src={persona.headSrc}
            alt={persona.name}
            className="h-full w-full rounded-full object-cover"
          />
        ) : (
          <MessageCircle className="h-5 w-5" />
        )}
        {unread && !panelOpen && (
          <span
            aria-label="Unread reply"
            className="absolute right-0.5 top-0.5 h-3 w-3 rounded-full bg-danger ring-2 ring-background"
          />
        )}
      </button>
    </>
  );
}
