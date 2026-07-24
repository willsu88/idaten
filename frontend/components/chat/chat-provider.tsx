"use client";

// Chat state lives here, mounted ONCE in the app shell, so the SSE stream,
// thread, and session survive closing the floating panel and navigating
// between pages. The /chat page and the floating panel are two views over
// the same state.

import * as React from "react";
import { usePathname } from "next/navigation";
import type { ChatQuota, ChatSession, PendingEdit } from "@/lib/types";
import { api, ApiError, streamChat } from "@/lib/api";
import { coachFirstName, useCoach } from "@/components/coach-provider";

export type ThreadItem =
  | {
      kind: "message";
      id: number;
      role: "user" | "assistant";
      content: string;
      /** User message that matched a slash command — rendered as a command chip. */
      shortcut?: boolean;
      /** Assistant reply the server stopped mid-stream — gets a "— stopped" marker. */
      stopped?: boolean;
    }
  | { kind: "tool"; id: number; name: string; status: "running" | "done" }
  | { kind: "edit"; id: number; edit: PendingEdit }
  // Backend-refused send (400 too long / 429 rate limit): the user-ready
  // `detail` sentence, rendered as a muted inline notice — not an error toast.
  // `canStop` marks the one-stream-conflict 429 so the notice can offer an
  // inline stop action (the client may not be streaming, e.g. another tab or
  // a stream orphaned by a dropped connection — there's no stop button then).
  | { kind: "notice"; id: number; content: string; canStop?: boolean }
  // Local, non-persisted /help response — never sent to the API.
  | { kind: "help"; id: number };

// Slash commands are expanded SERVER-side (v1.11): the client sends the raw
// typed text and only knows the command names for the menu + chip detection.
// /help is the exception — handled entirely client-side, nothing is sent.
export const SLASH_SHORTCUTS = [
  { command: "/week", hint: "Summarize my week" },
  { command: "/replan", hint: "Adjust upcoming plan" },
  { command: "/race-plan", hint: "Race strategy" },
  { command: "/sport", hint: "Plan around another sport — add what/when, e.g. /sport surfing saturday" },
  { command: "/help", hint: "What the coach can do (client-side, free)" },
];

/** Commands the server expands; used to flag live-sent messages as shortcut chips. */
const SERVER_COMMANDS = ["/week", "/replan", "/race-plan", "/sport"];

function firstToken(text: string): string {
  return text.split(/\s+/, 1)[0].toLowerCase();
}

interface ChatContextValue {
  sessions: ChatSession[];
  /** Daily chat message quota (chat messages only; cap null = unlimited).
   *  null until the first sessions load. */
  quota: ChatQuota | null;
  sessionId: string | undefined;
  items: ThreadItem[];
  streaming: boolean;
  input: string;
  setInput: (value: string) => void;
  contextDate: string | undefined;
  setContextDate: (date: string | undefined) => void;
  send: (raw?: string) => Promise<void>;
  openSession: (id: string) => Promise<void>;
  newSession: () => void;
  /** Composer placeholder: the transient one if set, else the coach default. */
  placeholder: string;
  /** Set (or clear with undefined) the transient composer placeholder. */
  setPlaceholder: (text: string | undefined) => void;
  panelOpen: boolean;
  openPanel: () => void;
  /**
   * Open the floating panel with a transient composer placeholder (cleared
   * when the panel closes or a message is sent). Never touches the input.
   */
  openWithPlaceholder: (text: string) => void;
  /**
   * Open the floating panel with text pre-typed into the composer (e.g.
   * "/replan " from the Week page). The user still reviews and presses send.
   */
  openWithDraft: (text: string) => void;
  closePanel: () => void;
  togglePanel: () => void;
  unread: boolean;
}

const ChatContext = React.createContext<ChatContextValue | null>(null);

export function useChat(): ChatContextValue {
  const ctx = React.useContext(ChatContext);
  if (!ctx) throw new Error("useChat must be used within <ChatProvider>");
  return ctx;
}

function isChatPage(pathname: string): boolean {
  return pathname === "/chat" || pathname.startsWith("/chat/");
}

export function ChatProvider({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const persona = useCoach();
  const [sessions, setSessions] = React.useState<ChatSession[]>([]);
  const [quota, setQuota] = React.useState<ChatQuota | null>(null);
  const [sessionId, setSessionId] = React.useState<string | undefined>(undefined);
  const [items, setItems] = React.useState<ThreadItem[]>([]);
  const [input, setInput] = React.useState("");
  const [streaming, setStreaming] = React.useState(false);
  const [contextDate, setContextDate] = React.useState<string | undefined>(undefined);
  const [panelOpen, setPanelOpen] = React.useState(false);
  const [unread, setUnread] = React.useState(false);
  // Transient composer placeholder (openWithPlaceholder / ?date deep links).
  const [transientPlaceholder, setTransientPlaceholder] = React.useState<string | undefined>(
    undefined,
  );
  const idRef = React.useRef(0);

  // Must fit one line in the single-row composer on a 375px phone — anything
  // longer wraps into the textarea's clipped second line.
  const placeholder =
    transientPlaceholder ??
    `Ask ${persona ? coachFirstName(persona) : "your coach"} anything… (/ for shortcuts)`;

  // Refs so the async send() sees the CURRENT visibility when the reply lands,
  // not what it was when the message was sent.
  const panelOpenRef = React.useRef(panelOpen);
  panelOpenRef.current = panelOpen;
  const pathnameRef = React.useRef(pathname);
  pathnameRef.current = pathname;

  const nextId = () => ++idRef.current;

  const loadSessions = React.useCallback(async () => {
    try {
      const res = await api.chatSessions();
      setSessions(res.sessions);
      setQuota(res.quota);
    } catch {
      setSessions([]);
    }
  }, []);

  React.useEffect(() => {
    loadSessions();
  }, [loadSessions]);

  // Landing on /chat counts as reading the chat.
  React.useEffect(() => {
    if (isChatPage(pathname)) setUnread(false);
  }, [pathname]);

  const openSession = React.useCallback(async (id: string) => {
    setSessionId(id);
    try {
      const history = await api.chatHistory(id);
      setItems(
        history.map((m): ThreadItem => {
          if (m.kind === "edit_proposed" && m.edit) {
            return { kind: "edit", id: nextId(), edit: m.edit };
          }
          return {
            kind: "message",
            id: nextId(),
            role: m.role,
            content: m.content,
            shortcut: m.kind === "shortcut",
          };
        }),
      );
    } catch {
      setItems([]);
    }
  }, []);

  const newSession = React.useCallback(() => {
    setSessionId(undefined);
    setItems([]);
  }, []);

  const send = React.useCallback(
    async (raw?: string) => {
      const text = (raw ?? input).trim();
      if (!text || streaming) return;

      // /help is client-side only: render a local help item, no API call,
      // no rate-limit spend, nothing persisted.
      if (firstToken(text) === "/help") {
        setInput("");
        setTransientPlaceholder(undefined);
        setItems((prev) => [
          ...prev,
          { kind: "message", id: nextId(), role: "user", content: text, shortcut: true },
          { kind: "help", id: nextId() },
        ]);
        return;
      }

      // Shortcuts are expanded server-side — send exactly what the user typed.
      // The command names are only used to render the message as a chip.
      const isShortcut = SERVER_COMMANDS.includes(firstToken(text));

      setInput("");
      setTransientPlaceholder(undefined);
      setStreaming(true);
      const assistantId = nextId();
      setItems((prev) => [
        ...prev,
        { kind: "message", id: nextId(), role: "user", content: text, shortcut: isShortcut },
        { kind: "message", id: assistantId, role: "assistant", content: "" },
      ]);

      const appendText = (delta: string) => {
        setItems((prev) =>
          prev.map((it) =>
            it.kind === "message" && it.id === assistantId
              ? { ...it, content: it.content + delta }
              : it,
          ),
        );
      };

      // Non-text items are inserted before the (still open) assistant bubble.
      const insertBeforeAssistant = (item: ThreadItem) => {
        setItems((prev) => {
          const idx = prev.findIndex((it) => it.kind === "message" && it.id === assistantId);
          if (idx === -1) return [...prev, item];
          return [...prev.slice(0, idx), item, ...prev.slice(idx)];
        });
      };

      try {
        await streamChat(
          { session_id: sessionId, message: text, context_date: contextDate },
          (event) => {
            switch (event.type) {
              case "session":
                setSessionId(event.session_id);
                break;
              case "text":
                appendText(event.delta);
                break;
              case "tool":
                setItems((prev) => {
                  const running = prev.findIndex(
                    (it) =>
                      it.kind === "tool" && it.name === event.name && it.status === "running",
                  );
                  if (event.status === "done" && running !== -1) {
                    const copy = [...prev];
                    copy[running] = {
                      ...(copy[running] as Extract<ThreadItem, { kind: "tool" }>),
                      status: "done",
                    };
                    return copy;
                  }
                  const idx = prev.findIndex(
                    (it) => it.kind === "message" && it.id === assistantId,
                  );
                  const item: ThreadItem = {
                    kind: "tool",
                    id: nextId(),
                    name: event.name,
                    status: event.status,
                  };
                  if (idx === -1) return [...prev, item];
                  return [...prev.slice(0, idx), item, ...prev.slice(idx)];
                });
                break;
              case "edit_proposed":
                // The server supersedes older pending proposals when a new one
                // is created — mirror that on cards already in the thread so
                // the user is never stuck behind a stale Accept button.
                setItems((prev) =>
                  prev.map((it) =>
                    it.kind === "edit" && it.edit.status === "pending"
                      ? { ...it, edit: { ...it.edit, status: "superseded" } }
                      : it,
                  ),
                );
                insertBeforeAssistant({ kind: "edit", id: nextId(), edit: event.edit });
                break;
              case "error":
                appendText(`\n\nSomething went wrong: ${event.message}`);
                break;
              case "stopped":
                // Terminal like "done"; the partial text stays, with a marker.
                setItems((prev) =>
                  prev.map((it) =>
                    it.kind === "message" && it.id === assistantId
                      ? { ...it, stopped: true }
                      : it,
                  ),
                );
                break;
              case "done":
                break;
              case "quota":
                setQuota({ used: event.used, cap: event.cap });
                break;
            }
          },
        );
      } catch (err) {
        if (err instanceof ApiError && (err.status === 400 || err.status === 429)) {
          // The empty assistant bubble is dropped in `finally`; the notice
          // stays and the composer re-enables via setStreaming(false).
          setItems((prev) => [
            ...prev,
            {
              kind: "notice",
              id: nextId(),
              content: err.message,
              // Matches the backend's one-stream-conflict copy (rate_limit.acquire_stream).
              canStop: err.status === 429 && /press stop/i.test(err.message),
            },
          ]);
        } else {
          appendText("Couldn't reach the coach — is the backend running?");
        }
      } finally {
        setStreaming(false);
        // Drop an assistant bubble that never received text (a stopped one
        // keeps its "— stopped" marker as feedback).
        setItems((prev) =>
          prev.filter(
            (it) =>
              !(it.kind === "message" && it.id === assistantId && it.content === "" && !it.stopped),
          ),
        );
        // Reply finished while chat wasn't visible → unread dot on the bubble.
        if (!panelOpenRef.current && !isChatPage(pathnameRef.current)) {
          setUnread(true);
        }
        loadSessions();
      }
    },
    [input, streaming, sessionId, contextDate, loadSessions],
  );

  const openPanel = React.useCallback(() => {
    setPanelOpen(true);
    setUnread(false);
  }, []);
  const openWithPlaceholder = React.useCallback((text: string) => {
    setPanelOpen(true);
    setUnread(false);
    setTransientPlaceholder(text);
  }, []);
  const openWithDraft = React.useCallback((text: string) => {
    setPanelOpen(true);
    setUnread(false);
    setInput(text);
  }, []);
  const closePanel = React.useCallback(() => {
    setPanelOpen(false);
    setTransientPlaceholder(undefined);
  }, []);
  const togglePanel = React.useCallback(() => {
    setPanelOpen((open) => {
      if (!open) setUnread(false);
      else setTransientPlaceholder(undefined);
      return !open;
    });
  }, []);

  const value: ChatContextValue = {
    sessions,
    quota,
    sessionId,
    items,
    streaming,
    input,
    setInput,
    contextDate,
    setContextDate,
    send,
    openSession,
    newSession,
    placeholder,
    setPlaceholder: setTransientPlaceholder,
    panelOpen,
    openPanel,
    openWithPlaceholder,
    openWithDraft,
    closePanel,
    togglePanel,
    unread,
  };

  return <ChatContext.Provider value={value}>{children}</ChatContext.Provider>;
}
