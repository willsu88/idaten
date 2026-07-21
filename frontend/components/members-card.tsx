"use client";

import * as React from "react";
import { Check, Copy, KeyRound, Trash2, UserPlus } from "lucide-react";
import type { InviteLink, Member, UserInfo } from "@/lib/types";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogDescription, DialogFooter, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";

interface RevealedLink {
  url: string;
  expires_at: string;
  /** What this link does, e.g. "Invite link" or "Password reset for Anna". */
  label: string;
}

function LinkReveal({ link, onDismiss }: { link: RevealedLink; onDismiss: () => void }) {
  const [copied, setCopied] = React.useState(false);
  const { toast } = useToast();

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(link.url);
      setCopied(true);
      toast("Link copied");
      setTimeout(() => setCopied(false), 2000);
    } catch {
      toast("Couldn't copy — select the link manually.", "error");
    }
  };

  return (
    <div className="space-y-2 rounded-xl border border-accent/40 bg-accent/5 p-3">
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm font-medium">{link.label}</p>
        <button
          type="button"
          onClick={onDismiss}
          className="text-xs text-muted-foreground underline hover:text-foreground"
        >
          dismiss
        </button>
      </div>
      <div className="flex items-center gap-2">
        <Input
          readOnly
          value={link.url}
          className="font-mono text-base sm:text-xs"
          onFocus={(e) => e.currentTarget.select()}
        />
        <Button variant="outline" size="icon" aria-label="Copy link" onClick={copy}>
          {copied ? <Check className="h-4 w-4 text-success" /> : <Copy className="h-4 w-4" />}
        </Button>
      </div>
      <p className="text-xs text-muted-foreground">
        One-time link, expires in 7 days — send it over any messenger.
      </p>
    </div>
  );
}

function RemoveMemberDialog({
  member,
  onOpenChange,
  onRemoved,
}: {
  member: Member | null;
  onOpenChange: (open: boolean) => void;
  onRemoved: () => void;
}) {
  const [busy, setBusy] = React.useState(false);
  const { toast } = useToast();

  const remove = async () => {
    if (!member || busy) return;
    setBusy(true);
    try {
      await api.deleteUser(member.id);
      toast(`Removed ${member.display_name || member.username}`);
      onOpenChange(false);
      onRemoved();
    } catch {
      toast("Couldn't remove the member — try again.", "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={member != null} onOpenChange={onOpenChange}>
      <DialogTitle>Remove {member?.display_name || member?.username}?</DialogTitle>
      <DialogDescription>
        This deletes their account <span className="font-medium text-foreground">and ALL their
        data</span> — activities, health history, plans, and chats. This cannot be undone.
      </DialogDescription>
      <DialogFooter>
        <Button variant="outline" onClick={() => onOpenChange(false)}>
          Cancel
        </Button>
        <Button variant="destructive" onClick={remove} disabled={busy}>
          <Trash2 className="h-3.5 w-3.5" />
          {busy ? "Removing…" : "Remove member"}
        </Button>
      </DialogFooter>
    </Dialog>
  );
}

function MemberRow({
  member,
  isAdminViewer,
  onResetLink,
  onRemove,
  busy,
}: {
  member: Member;
  isAdminViewer: boolean;
  onResetLink: (member: Member) => void;
  onRemove: (member: Member) => void;
  busy: boolean;
}) {
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-xl border border-border px-4 py-3">
      <span
        title={member.garmin_connected ? "Garmin connected" : "Garmin not connected"}
        className={cn(
          "h-2 w-2 shrink-0 rounded-full",
          member.garmin_connected ? "bg-success" : "bg-muted-foreground/30",
        )}
      />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-1.5">
          <p className="truncate text-sm font-semibold">
            {member.display_name || member.username}
          </p>
          {member.is_me && <Badge variant="secondary">You</Badge>}
          {member.is_admin && <Badge>Admin</Badge>}
        </div>
        <p className="text-xs text-muted-foreground">@{member.username}</p>
      </div>
      {isAdminViewer && !member.is_me && (
        <div className="flex items-center gap-1">
          <Button variant="outline" size="sm" disabled={busy} onClick={() => onResetLink(member)}>
            <KeyRound className="h-3.5 w-3.5" />
            Reset password
          </Button>
          <Button
            variant="ghost"
            size="icon"
            aria-label={`Remove ${member.display_name || member.username}`}
            disabled={busy}
            className="text-muted-foreground hover:text-danger"
            onClick={() => onRemove(member)}
          >
            <Trash2 className="h-4 w-4" />
          </Button>
        </div>
      )}
    </div>
  );
}

export function MembersCard({ me }: { me: UserInfo }) {
  const [members, setMembers] = React.useState<Member[] | null>(null);
  const [error, setError] = React.useState(false);
  const [link, setLink] = React.useState<RevealedLink | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [removing, setRemoving] = React.useState<Member | null>(null);
  const { toast } = useToast();

  const load = React.useCallback(async () => {
    try {
      setMembers(await api.members());
      setError(false);
    } catch {
      setError(true);
    }
  }, []);

  React.useEffect(() => {
    load();
  }, [load]);

  const reveal = async (fn: () => Promise<InviteLink>, label: string) => {
    if (busy) return;
    setBusy(true);
    try {
      const created = await fn();
      setLink({ url: window.location.origin + created.path, expires_at: created.expires_at, label });
    } catch {
      toast("Couldn't create the link — try again.", "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between space-y-0">
        <div>
          <CardTitle>Members</CardTitle>
          <CardDescription>
            Everyone on Idaten — each with their own login, Garmin connection, and plan
          </CardDescription>
        </div>
        {me.is_admin && (
          <Button
            variant="outline"
            size="sm"
            className="shrink-0"
            disabled={busy}
            onClick={() => reveal(() => api.createInvite(), "Invite link")}
          >
            <UserPlus className="h-3.5 w-3.5" />
            Invite member
          </Button>
        )}
      </CardHeader>
      <CardContent className="space-y-3">
        {link && <LinkReveal link={link} onDismiss={() => setLink(null)} />}

        {members == null && !error ? (
          <>
            <Skeleton className="h-14 rounded-xl" />
            <Skeleton className="h-14 rounded-xl" />
          </>
        ) : error ? (
          <p className="text-sm text-muted-foreground">
            Couldn&apos;t load members — is the backend running?
          </p>
        ) : (
          members?.map((member) => (
            <MemberRow
              key={member.id}
              member={member}
              isAdminViewer={me.is_admin}
              busy={busy}
              onResetLink={(m) =>
                reveal(
                  () => api.createResetLink(m.id),
                  `Password reset for ${m.display_name || m.username}`,
                )
              }
              onRemove={setRemoving}
            />
          ))
        )}

        {!me.is_admin && (
          <p className="text-xs text-muted-foreground">
            Membership is managed by the admin — ask them for invites or password resets.
          </p>
        )}
      </CardContent>

      <RemoveMemberDialog
        member={removing}
        onOpenChange={(open) => {
          if (!open) setRemoving(null);
        }}
        onRemoved={load}
      />
    </Card>
  );
}
