"use client";

import * as React from "react";
import { Check, Watch } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type { UserInfo } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-sm font-medium">{label}</span>
      {children}
    </label>
  );
}

/** Garmin connection management: first-time connect (kicks off onboarding) or
 *  updating credentials on an already-connected account. */
export function ConnectGarminCard({
  me,
  onConnected,
}: {
  me: UserInfo;
  onConnected?: () => void;
}) {
  const wasConnected = me.garmin_connected;
  const [email, setEmail] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [done, setDone] = React.useState<"onboarding" | "updated" | null>(null);
  const [editing, setEditing] = React.useState(!wasConnected);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email || !password || busy) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.garminConnect(email, password);
      setDone(res.onboarding_started ? "onboarding" : "updated");
      setEditing(false);
      setPassword("");
      onConnected?.();
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 400
          ? err.message
          : "Couldn't reach the server — try again in a moment.",
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card className="border-accent/40">
      <CardHeader>
        <div className="flex items-center gap-2 text-accent">
          <Watch className="h-4 w-4" />
          <span className="text-xs font-semibold uppercase tracking-wider">
            {wasConnected ? "Garmin connection" : "Connect Garmin"}
          </span>
        </div>
        <CardTitle className="text-base">
          {wasConnected ? "Garmin account" : "Link your Garmin account"}
        </CardTitle>
        <CardDescription>
          {wasConnected
            ? "Your credentials are only sent to your own backend, never to third parties."
            : "Your credentials are only sent to your own backend, never to third parties. The coach syncs the last two weeks first (about a minute), then loads 300 days of history in the background. Your plan is ready the next time you open Today."}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {done === "onboarding" && (
          <p className="inline-flex items-center gap-1.5 text-sm font-medium text-success">
            <Check className="h-4 w-4" />
            Connected — your history is loading
          </p>
        )}
        {done === "updated" && (
          <p className="inline-flex items-center gap-1.5 text-sm font-medium text-success">
            <Check className="h-4 w-4" />
            Credentials updated and verified
          </p>
        )}
        {!editing && done === null && wasConnected && (
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="inline-flex items-center gap-1.5 text-sm text-muted-foreground">
              <Check className="h-4 w-4 text-success" />
              Connected{me.garmin_email ? ` as ${me.garmin_email}` : ""}
            </p>
            <Button variant="outline" size="sm" onClick={() => setEditing(true)}>
              Update credentials
            </Button>
          </div>
        )}
        {editing && (
          <form onSubmit={submit} className="space-y-3">
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Garmin email">
                <Input
                  type="email"
                  autoComplete="off"
                  placeholder={me.garmin_email ?? undefined}
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                />
              </Field>
              <Field label="Garmin password">
                <Input
                  type="password"
                  autoComplete="off"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
              </Field>
            </div>
            {error && <p className="text-sm text-danger">{error}</p>}
            <div className="flex items-center gap-2">
              <Button type="submit" disabled={busy || !email || !password}>
                {busy ? "Verifying…" : wasConnected ? "Verify & save" : "Connect Garmin"}
              </Button>
              {wasConnected && (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    setEditing(false);
                    setError(null);
                  }}
                >
                  Cancel
                </Button>
              )}
            </div>
          </form>
        )}
      </CardContent>
    </Card>
  );
}
