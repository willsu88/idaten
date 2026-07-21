"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import type { UserInfo } from "@/lib/types";
import { api, safe } from "@/lib/api";
import { AdminLlmCard } from "@/components/admin-llm-card";
import { AdminQualityCard } from "@/components/admin-quality-card";
import { MembersCard } from "@/components/members-card";
import { PageHeader } from "@/components/page-header";
import { Skeleton } from "@/components/ui/skeleton";

/**
 * Household administration. Admin-only: an invited member never sees this page
 * or its nav item. This client guard is UX only — the real boundary is the
 * server, where member management and the roster read are all Depends(admin_user).
 */
export default function AdminPage() {
  const router = useRouter();
  const [me, setMe] = React.useState<UserInfo | null>(null);

  React.useEffect(() => {
    safe(api.authMe()).then((user) => {
      if (!user || !user.is_admin) {
        router.replace("/"); // bounce non-admins (and logged-out) home
        return;
      }
      setMe(user);
    });
  }, [router]);

  if (!me) {
    return (
      <div>
        <PageHeader title="Admin" />
        <Skeleton className="h-64 rounded-2xl" />
      </div>
    );
  }

  return (
    <div>
      <PageHeader title="Admin" subtitle="Manage household members and invites" />
      <div className="space-y-5">
        <MembersCard me={me} />
        <AdminLlmCard />
        <AdminQualityCard />
      </div>
    </div>
  );
}
