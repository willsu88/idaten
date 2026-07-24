"use client";

import * as React from "react";
import type { Settings, UsageBucket, UsageSummary } from "@/lib/types";
import { api, safe } from "@/lib/api";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";

type Provider = NonNullable<Settings["llm_provider"]>;

function fmtTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

function fmtCost(n: number): string {
  return `$${n.toFixed(n > 0 && n < 1 ? 4 : 2)}`;
}

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-xl border border-border px-4 py-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-0.5 text-lg font-semibold tabular-nums">{value}</p>
      {sub && <p className="text-xs text-muted-foreground">{sub}</p>}
    </div>
  );
}

/** A compact cost/usage table keyed by a label column (call site or user). */
function UsageTable({
  head,
  rows,
}: {
  head: string;
  rows: Array<{ key: string; label: string } & UsageBucket>;
}) {
  if (rows.length === 0) {
    return <p className="text-sm text-muted-foreground">No usage recorded yet.</p>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border text-left text-xs text-muted-foreground">
            <th className="py-2 pr-3 font-medium">{head}</th>
            <th className="py-2 px-3 text-right font-medium">Calls</th>
            <th className="py-2 px-3 text-right font-medium">In / Out</th>
            <th className="py-2 px-3 text-right font-medium">Cache</th>
            <th className="py-2 pl-3 text-right font-medium">Cost</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.key} className="border-b border-border/50 last:border-0">
              <td className="py-2 pr-3 font-medium">{r.label}</td>
              <td className="py-2 px-3 text-right tabular-nums">{r.calls}</td>
              <td className="py-2 px-3 text-right tabular-nums text-muted-foreground">
                {fmtTokens(r.input_tokens)} / {fmtTokens(r.output_tokens)}
              </td>
              <td className="py-2 px-3 text-right tabular-nums text-muted-foreground">
                {r.cache_hit_pct}%
              </td>
              <td className="py-2 pl-3 text-right font-semibold tabular-nums">
                {fmtCost(r.cost_usd)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// Mirrors the backend's CAP_MAX (chat_quota.py) — the PUT rejects anything above.
const CAP_MAX = 1000;

/** Inline editor for one member's daily chat cap. Blank (or "∞") = unlimited. */
function CapEditor({
  value,
  onSave,
}: {
  value: number | null;
  onSave: (cap: number | null) => void;
}) {
  const [editing, setEditing] = React.useState(false);
  const [draft, setDraft] = React.useState("");

  const commit = () => {
    setEditing(false);
    const text = draft.trim();
    if (text === "" || text === "∞") {
      if (value !== null) onSave(null);
      return;
    }
    const n = Number(text);
    if (!Number.isInteger(n) || n < 0 || n > CAP_MAX || n === value) return;
    onSave(n);
  };

  if (!editing) {
    return (
      <button
        type="button"
        onClick={() => {
          setDraft(value == null ? "" : String(value));
          setEditing(true);
        }}
        className="rounded-md px-2 py-0.5 tabular-nums underline decoration-dotted underline-offset-2 hover:bg-muted"
        aria-label="Edit daily chat cap"
      >
        {value == null ? "∞" : value}
      </button>
    );
  }
  return (
    <input
      autoFocus
      value={draft}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === "Enter") commit();
        if (e.key === "Escape") setEditing(false);
      }}
      inputMode="numeric"
      placeholder="∞"
      className="w-14 rounded-md border border-border bg-background px-1.5 py-0.5 text-right text-sm tabular-nums outline-none focus:ring-1 focus:ring-ring"
    />
  );
}

/** The member table: usage plus the daily chat cap (chat messages only). */
function MemberTable({
  rows,
  onSetCap,
}: {
  rows: UsageSummary["by_user"];
  onSetCap: (userId: number, cap: number | null) => void;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border text-left text-xs text-muted-foreground">
            <th className="py-2 pr-3 font-medium">Member</th>
            <th className="py-2 px-3 text-right font-medium">Calls</th>
            <th className="py-2 px-3 text-right font-medium">In / Out</th>
            <th className="py-2 px-3 text-right font-medium">Cache</th>
            <th className="py-2 px-3 text-right font-medium">Cost</th>
            <th className="py-2 px-3 text-right font-medium">Msgs today</th>
            <th className="py-2 pl-3 text-right font-medium">Daily cap</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.user_id} className="border-b border-border/50 last:border-0">
              <td className="py-2 pr-3 font-medium">{r.name}</td>
              <td className="py-2 px-3 text-right tabular-nums">{r.calls}</td>
              <td className="py-2 px-3 text-right tabular-nums text-muted-foreground">
                {fmtTokens(r.input_tokens)} / {fmtTokens(r.output_tokens)}
              </td>
              <td className="py-2 px-3 text-right tabular-nums text-muted-foreground">
                {r.cache_hit_pct}%
              </td>
              <td className="py-2 px-3 text-right font-semibold tabular-nums">
                {fmtCost(r.cost_usd)}
              </td>
              <td className="py-2 px-3 text-right tabular-nums text-muted-foreground">
                {r.msgs_today}
                {r.chat_daily_cap != null && ` / ${r.chat_daily_cap}`}
              </td>
              <td className="py-2 pl-3 text-right">
                <CapEditor value={r.chat_daily_cap} onSave={(cap) => onSetCap(r.user_id, cap)} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function AdminLlmCard() {
  const [provider, setProvider] = React.useState<Provider | null>(null);
  const [usage, setUsage] = React.useState<UsageSummary | null>(null);
  const [usageError, setUsageError] = React.useState(false);
  const { toast } = useToast();

  React.useEffect(() => {
    safe(api.getSettings()).then((s) => {
      if (s) setProvider((s.llm_provider ?? "anthropic") as Provider);
    });
    safe(api.usage(30)).then((u) => (u ? setUsage(u) : setUsageError(true)));
  }, []);

  const changeProvider = (next: Provider) => {
    if (next === provider) return;
    const previous = provider;
    setProvider(next); // optimistic
    api
      .putSettings({ llm_provider: next })
      .then(() => toast(`LLM provider set to ${next === "openai" ? "OpenAI" : "Anthropic"}`))
      .catch(() => {
        setProvider(previous);
        toast("Couldn't change the provider - try again.", "error");
      });
  };

  const setCap = (userId: number, cap: number | null) => {
    const previous = usage;
    setUsage((u) =>
      u && {
        ...u,
        by_user: u.by_user.map((r) =>
          r.user_id === userId ? { ...r, chat_daily_cap: cap } : r,
        ),
      },
    ); // optimistic
    api
      .setChatCap(userId, cap)
      .then(() => toast(cap == null ? "Chat cap removed" : `Chat cap set to ${cap}/day`))
      .catch(() => {
        setUsage(previous);
        toast("Couldn't update the chat cap - try again.", "error");
      });
  };

  const t = usage?.total;

  return (
    <Card>
      <CardHeader>
        <CardTitle>LLM</CardTitle>
        <CardDescription>Provider and token / cost usage (last 30 days)</CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        <div>
          <span className="mb-1.5 block text-sm font-medium">Provider</span>
          {provider == null ? (
            <Skeleton className="h-10 w-full max-w-xs rounded-xl" />
          ) : (
            <Select
              value={provider}
              onChange={(e) => changeProvider(e.target.value as Provider)}
              className="max-w-xs"
            >
              <option value="anthropic">Anthropic</option>
              <option value="openai">OpenAI</option>
            </Select>
          )}
          <p className="mt-1.5 text-xs text-muted-foreground">
            Whoever&apos;s API key funds the app picks the provider - members always run on this.
          </p>
        </div>

        <div className="border-t border-border pt-5">
          {usage == null && !usageError ? (
            <div className="grid gap-3 sm:grid-cols-3">
              <Skeleton className="h-20 rounded-xl" />
              <Skeleton className="h-20 rounded-xl" />
              <Skeleton className="h-20 rounded-xl" />
            </div>
          ) : usageError || !t ? (
            <p className="text-sm text-muted-foreground">Couldn&apos;t load usage.</p>
          ) : (
            <div className="space-y-5">
              <div className="grid gap-3 sm:grid-cols-3">
                <Stat label="Cost (30d)" value={fmtCost(t.cost_usd)} sub={`${t.calls} calls`} />
                <Stat
                  label="Tokens in / out"
                  value={`${fmtTokens(t.input_tokens)} / ${fmtTokens(t.output_tokens)}`}
                  sub={`${fmtTokens(t.cache_read_tokens)} cached`}
                />
                <Stat
                  label="Cache hit"
                  value={`${t.cache_hit_pct}%`}
                  sub="of input tokens read from cache"
                />
              </div>

              <div>
                <p className="mb-2 text-sm font-medium">By feature</p>
                <UsageTable
                  head="Feature"
                  rows={usage.by_call_site.map((r) => ({ ...r, key: r.call_site, label: r.call_site }))}
                />
              </div>

              <div>
                <p className="mb-2 text-sm font-medium">By member</p>
                <MemberTable rows={usage.by_user} onSetCap={setCap} />
                <p className="mt-1.5 text-xs text-muted-foreground">
                  The daily cap limits chat messages only - daily reviews, plans, and run
                  analysis are never blocked. One message can fan out into several calls.
                </p>
              </div>
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
