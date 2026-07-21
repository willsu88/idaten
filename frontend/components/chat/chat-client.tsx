"use client";

// Full-page /chat view. State lives in ChatProvider (mounted in the app
// shell), so this page and the floating panel share one session/stream.

import * as React from "react";
import { useSearchParams } from "next/navigation";
import { History, MessageSquarePlus } from "lucide-react";
import { PageHeader } from "@/components/page-header";
import { ChatConversation } from "@/components/chat/chat-conversation";
import { useChat } from "@/components/chat/chat-provider";
import { useCoach } from "@/components/coach-provider";
import { Button } from "@/components/ui/button";
import { isoDate } from "@/lib/utils";

export function ChatClient() {
  const searchParams = useSearchParams();
  const { setPlaceholder, setContextDate, newSession } = useChat();
  const persona = useCoach();
  const [sessionsOpen, setSessionsOpen] = React.useState(false);

  // ?date=YYYY-MM-DD deep links ("Ask about this workout") set the chat
  // context and a transient placeholder — never the input itself.
  React.useEffect(() => {
    const date = searchParams.get("date");
    if (date) {
      setContextDate(date);
      setPlaceholder(
        date === isoDate() ? "Ask about today's workout…" : "Ask about this workout…",
      );
    }
  }, [searchParams, setPlaceholder, setContextDate]);

  return (
    // 100dvh (not vh) so iOS Safari resizes the thread when the keyboard/URL bar
    // shows; the bottom tab bar + safe area are subtracted on mobile.
    <div className="flex h-[calc(100dvh-6.25rem-env(safe-area-inset-bottom))] flex-col md:h-[calc(100dvh-4rem)]">
      <PageHeader
        title={
          <span className="flex items-center gap-2.5">
            {persona && (
              <img
                src={persona.headSrc}
                alt={persona.name}
                className="h-7 w-7 rounded-full border border-border object-cover"
              />
            )}
            {persona?.name ?? "Coach"}
          </span>
        }
        subtitle="Ask anything about your training"
        actions={
          <>
            <Button variant="outline" size="sm" onClick={() => setSessionsOpen(!sessionsOpen)}>
              <History className="h-3.5 w-3.5" />
              History
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                newSession();
                setSessionsOpen(false);
              }}
            >
              <MessageSquarePlus className="h-3.5 w-3.5" />
              New chat
            </Button>
          </>
        }
      />
      <ChatConversation sessionsOpen={sessionsOpen} setSessionsOpen={setSessionsOpen} />
    </div>
  );
}
