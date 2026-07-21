"use client";

// PUBLIC page: renders without a session. All API calls here go through the
// public invite endpoints with the 401→/login redirect disabled.

import * as React from "react";
import { Activity, Link2Off, Loader2 } from "lucide-react";
import type { InviteStatus } from "@/lib/types";
import { api, ApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";

const USERNAME_RE = /^[a-z0-9_.-]{2,32}$/;

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-dvh items-center justify-center px-4">
      <Card className="w-full max-w-sm">{children}</Card>
    </div>
  );
}

function Logo() {
  return (
    <span className="mb-2 flex h-12 w-12 items-center justify-center rounded-2xl bg-accent text-accent-foreground">
      <Activity className="h-6 w-6" />
    </span>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-sm font-medium">{label}</span>
      {children}
    </label>
  );
}

function InvalidCard() {
  return (
    <Shell>
      <CardHeader className="items-center text-center">
        <span className="mb-2 flex h-12 w-12 items-center justify-center rounded-2xl bg-muted text-muted-foreground">
          <Link2Off className="h-6 w-6" />
        </span>
        <CardTitle>This link has expired or was already used</CardTitle>
        <CardDescription>
          Invite and password-reset links are one-time and expire after 7 days. Ask the person who
          invited you for a fresh one.
        </CardDescription>
      </CardHeader>
    </Shell>
  );
}

function InviteForm({ token }: { token: string }) {
  const [username, setUsername] = React.useState("");
  const [displayName, setDisplayName] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [expired, setExpired] = React.useState(false);

  const normalizedUsername = username.trim().toLowerCase();
  const validUsername = USERNAME_RE.test(normalizedUsername);
  const validPassword = password.length >= 6;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (busy) return;
    if (!validUsername) {
      setError("Username must be 2–32 characters: lowercase letters, digits, _ . -");
      return;
    }
    if (!validPassword) {
      setError("Password must be at least 6 characters.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.acceptInvite(token, {
        username: normalizedUsername,
        password,
        ...(displayName.trim() ? { display_name: displayName.trim() } : {}),
      });
      window.location.href = "/"; // logged in via session cookie; dashboard takes it from here
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setError("That username is already taken.");
      } else if (err instanceof ApiError && err.status === 410) {
        setExpired(true);
      } else {
        setError("Couldn't create the account — try again in a moment.");
      }
      setBusy(false);
    }
  };

  if (expired) return <InvalidCard />;

  return (
    <Shell>
      <CardHeader className="items-center text-center">
        <Logo />
        <CardTitle>You&apos;ve been invited to Idaten</CardTitle>
        <CardDescription>Pick a username and password to create your account</CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={submit} className="space-y-3">
          <Field label="Username">
            <Input
              autoFocus
              autoComplete="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
            />
          </Field>
          <Field label="Display name (optional)">
            <Input
              autoComplete="name"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
            />
          </Field>
          <Field label="Password">
            <Input
              type="password"
              autoComplete="new-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </Field>
          {error && <p className="text-sm text-danger">{error}</p>}
          <Button type="submit" className="w-full" disabled={busy || !username || !password}>
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : "Create account"}
          </Button>
        </form>
      </CardContent>
    </Shell>
  );
}

function ResetForm({ token, username }: { token: string; username: string }) {
  const [password, setPassword] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [expired, setExpired] = React.useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (busy) return;
    if (password.length < 6) {
      setError("Password must be at least 6 characters.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.acceptInvite(token, { password });
      window.location.href = "/";
    } catch (err) {
      if (err instanceof ApiError && err.status === 410) {
        setExpired(true);
      } else {
        setError("Couldn't set the password — try again in a moment.");
      }
      setBusy(false);
    }
  };

  if (expired) return <InvalidCard />;

  return (
    <Shell>
      <CardHeader className="items-center text-center">
        <Logo />
        <CardTitle>Set a new password for @{username}</CardTitle>
        <CardDescription>You&apos;ll be signed in right after</CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={submit} className="space-y-3">
          <Field label="New password">
            <Input
              autoFocus
              type="password"
              autoComplete="new-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </Field>
          {error && <p className="text-sm text-danger">{error}</p>}
          <Button type="submit" className="w-full" disabled={busy || !password}>
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : "Set password"}
          </Button>
        </form>
      </CardContent>
    </Shell>
  );
}

export default function InvitePage({ params }: { params: { token: string } }) {
  const { token } = params;
  const [status, setStatus] = React.useState<InviteStatus | null>(null);
  const [failed, setFailed] = React.useState(false);

  React.useEffect(() => {
    api
      .inviteStatus(token)
      .then(setStatus)
      .catch(() => setFailed(true));
  }, [token]);

  if (failed || (status && !status.valid)) return <InvalidCard />;

  if (!status) {
    return (
      <div className="flex min-h-dvh items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return status.kind === "invite" ? (
    <InviteForm token={token} />
  ) : (
    <ResetForm token={token} username={status.username} />
  );
}
