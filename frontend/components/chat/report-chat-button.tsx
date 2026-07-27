"use client";

// Member-facing "report this chat" (the QA fast-follow reserved by ADR 0016's
// spec). One tap sends the whole session - transcript frozen server-side, the
// same view the nightly judge grades - to the admin's quality card, so nobody
// screenshots a bad conversation. Reports are per session and upsert in place.

import * as React from "react";
import { Flag } from "lucide-react";
import { api, safe } from "@/lib/api";
import { useChat } from "@/components/chat/chat-provider";
import { Button } from "@/components/ui/button";
import { Dialog, DialogDescription, DialogFooter, DialogTitle } from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/components/ui/toast";

export function ReportChatButton({ compact = false }: { compact?: boolean }) {
  const { sessionId, sessions } = useChat();
  const { toast } = useToast();
  const [open, setOpen] = React.useState(false);
  const [comment, setComment] = React.useState("");
  const [sending, setSending] = React.useState(false);
  const [reportedSession, setReportedSession] = React.useState<string | null>(null);

  // No session yet (fresh page, nothing sent) - nothing to report.
  if (!sessionId) return null;
  // Server flag survives reloads; local state covers the just-reported session
  // before the list refreshes. A reported session stays reported (the disabled
  // button also keeps a resend from wiping the original comment).
  const reported =
    reportedSession === sessionId ||
    (sessions.find((s) => s.id === sessionId)?.reported ?? false);

  const submit = async () => {
    setSending(true);
    const res = await safe(
      api.postFeedback({ surface: "chat_session", ref: sessionId, rating: -1, comment }),
    );
    setSending(false);
    if (!res) {
      toast("Couldn't send the report - please try again.", "error");
      return;
    }
    setReportedSession(sessionId);
    setOpen(false);
    setComment("");
    toast("Reported. Your admin can now see this conversation.");
  };

  return (
    <>
      {compact ? (
        // Icon-only trigger matching the floating panel's header buttons.
        <button
          type="button"
          title={reported ? "Reported" : "Report this chat"}
          aria-label={reported ? "Chat reported" : "Report this chat"}
          disabled={reported}
          onClick={() => setOpen(true)}
          className="flex h-11 w-11 items-center justify-center rounded-lg text-muted-foreground hover:bg-muted hover:text-foreground disabled:pointer-events-none disabled:text-accent md:h-8 md:w-8"
        >
          <Flag className="h-4 w-4" />
        </button>
      ) : (
        <Button
          variant="outline"
          size="sm"
          disabled={reported}
          onClick={() => setOpen(true)}
        >
          <Flag className="h-3.5 w-3.5" />
          {reported ? "Reported" : "Report"}
        </Button>
      )}
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogTitle>Report this chat</DialogTitle>
        <DialogDescription>
          Sends this whole conversation to your household admin so they can look
          into what went wrong. Only this chat is shared.
        </DialogDescription>
        <Textarea
          className="mt-4"
          rows={3}
          maxLength={1000}
          placeholder="What went wrong? (optional)"
          value={comment}
          onChange={(e) => setComment(e.target.value)}
        />
        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)}>
            Cancel
          </Button>
          <Button onClick={submit} disabled={sending}>
            {sending ? "Sending…" : "Send report"}
          </Button>
        </DialogFooter>
      </Dialog>
    </>
  );
}
