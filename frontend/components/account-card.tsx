"use client";

import * as React from "react";
import Link from "next/link";
import { LogOut } from "lucide-react";
import type { UserInfo } from "@/lib/types";
import { api, ApiError } from "@/lib/api";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useToast } from "@/components/ui/toast";

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-sm font-medium">{label}</span>
      {children}
    </label>
  );
}

function DisplayNameForm({ me }: { me: UserInfo }) {
  const [name, setName] = React.useState(me.display_name);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const { toast } = useToast();

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = name.trim();
    if (busy) return;
    if (trimmed.length < 1 || trimmed.length > 40) {
      setError("Pick a name between 1 and 40 characters.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const user = await api.updateProfile(trimmed);
      setName(user.display_name);
      toast("Name updated");
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 422
          ? "Pick a name between 1 and 40 characters."
          : "Couldn't save your name — try again in a moment.",
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="space-y-3">
      <div className="flex flex-wrap items-end gap-3">
        <Field label="Display name">
          <Input
            className="w-56"
            value={name}
            maxLength={40}
            onChange={(e) => setName(e.target.value)}
          />
        </Field>
        <Button
          type="submit"
          variant="outline"
          size="sm"
          disabled={busy || name.trim() === me.display_name}
        >
          {busy ? "Saving…" : "Save name"}
        </Button>
      </div>
      {error && <p className="text-sm text-danger">{error}</p>}
    </form>
  );
}

function ChangePasswordForm() {
  const [current, setCurrent] = React.useState("");
  const [next, setNext] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const { toast } = useToast();

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!current || !next || busy) return;
    setBusy(true);
    setError(null);
    try {
      await api.changePassword({ current_password: current, new_password: next });
      setCurrent("");
      setNext("");
      toast("Password changed");
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 401
          ? "Current password is incorrect."
          : "Couldn't change the password — try again.",
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="space-y-3">
      <p className="text-sm font-semibold">Change password</p>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Current password">
          <Input
            type="password"
            autoComplete="current-password"
            value={current}
            onChange={(e) => setCurrent(e.target.value)}
          />
        </Field>
        <Field label="New password">
          <Input
            type="password"
            autoComplete="new-password"
            value={next}
            onChange={(e) => setNext(e.target.value)}
          />
        </Field>
      </div>
      {error && <p className="text-sm text-danger">{error}</p>}
      <Button type="submit" variant="outline" size="sm" disabled={busy || !current || !next}>
        {busy ? "Changing…" : "Change password"}
      </Button>
    </form>
  );
}

/**
 * "Account & advanced": display name, password, tutorial replay, then any
 * advanced settings fields the page passes as children, and logout last.
 */
export function AccountCard({ me, children }: { me: UserInfo; children?: React.ReactNode }) {
  const [loggingOut, setLoggingOut] = React.useState(false);
  const { toast } = useToast();

  const logout = async () => {
    setLoggingOut(true);
    try {
      await api.logout();
      window.location.href = "/login";
    } catch {
      toast("Logout failed — try again.", "error");
      setLoggingOut(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Account &amp; advanced</CardTitle>
        <CardDescription>
          Signed in as <span className="font-medium text-foreground">{me.display_name}</span> (
          {me.username})
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        <DisplayNameForm me={me} />
        <ChangePasswordForm />
        <div className="flex items-center justify-between rounded-xl border border-border px-4 py-3">
          <div>
            <p className="text-sm font-medium">Tutorial</p>
            <p className="text-xs text-muted-foreground">Replay the setup wizard and app tour</p>
          </div>
          <Link
            href="/welcome?replay=1"
            className={buttonVariants({ variant: "outline", size: "sm" })}
          >
            Show tutorial
          </Link>
        </div>
        {children}
        <div className="flex justify-start">
          <Button variant="outline" size="sm" onClick={logout} disabled={loggingOut}>
            <LogOut className="h-3.5 w-3.5" />
            {loggingOut ? "Logging out…" : "Log out"}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
