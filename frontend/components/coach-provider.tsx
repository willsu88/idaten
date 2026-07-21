"use client";

// The selected coach persona (settings.coach_style → PERSONAS), fetched once
// per shell mount so the chat bubble, chat headers, and coach notes all agree.
// Refetched after leaving /settings, where the coach can change mid-session.

import * as React from "react";
import { usePathname } from "next/navigation";
import { api, safe } from "@/lib/api";
import { PERSONAS, type Persona } from "@/components/persona-card";

const CoachContext = React.createContext<Persona | null>(null);
// Whether cycle tracking is on — drives the conditional "Manage cycle" nav item.
const CycleEnabledContext = React.createContext<boolean>(false);
// Whether the signed-in user is the admin — gates the "Admin" nav item + page.
const IsAdminContext = React.createContext<boolean>(false);

/** The selected coach persona, or null while settings haven't loaded. */
export function useCoach(): Persona | null {
  return React.useContext(CoachContext);
}

/** True when the athlete has menstrual cycle tracking enabled. */
export function useCycleEnabled(): boolean {
  return React.useContext(CycleEnabledContext);
}

/** True when the signed-in user is the admin. UI gate only — the server is the
 * real boundary (admin endpoints are `Depends(admin_user)`). */
export function useIsAdmin(): boolean {
  return React.useContext(IsAdminContext);
}

/** "Koa" from "Coach Koa" — for "Ask Koa"-style labels. */
export function coachFirstName(persona: Persona): string {
  return persona.name.replace(/^Coach\s+/, "");
}

/** The persona for a stored coach_style key (e.g. an analysis's author), so a
 * later coach switch never re-labels who wrote it. Falls back to the default. */
export function personaForStyle(style: string | null | undefined): Persona {
  return PERSONAS.find((p) => p.style === style) ?? PERSONAS[0];
}

export function CoachProvider({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [persona, setPersona] = React.useState<Persona | null>(null);
  const [cycleEnabled, setCycleEnabled] = React.useState(false);
  const [isAdmin, setIsAdmin] = React.useState(false);

  const refresh = React.useCallback(async () => {
    const [settings, me] = await Promise.all([safe(api.getSettings()), safe(api.authMe())]);
    if (settings) {
      setPersona(PERSONAS.find((p) => p.style === settings.coach_style) ?? PERSONAS[0]);
      setCycleEnabled(!!settings.cycle?.enabled);
    }
    if (me) setIsAdmin(!!me.is_admin);
  }, []);

  React.useEffect(() => {
    refresh();
  }, [refresh]);

  // Coach + cycle toggles happen under /settings — refetch when navigating away
  // so the nav's "Manage cycle" item appears/disappears without a full reload.
  const prevPathRef = React.useRef(pathname);
  React.useEffect(() => {
    const left = prevPathRef.current.startsWith("/settings") && !pathname.startsWith("/settings");
    if (left) refresh();
    prevPathRef.current = pathname;
  }, [pathname, refresh]);

  return (
    <CoachContext.Provider value={persona}>
      <CycleEnabledContext.Provider value={cycleEnabled}>
        <IsAdminContext.Provider value={isAdmin}>{children}</IsAdminContext.Provider>
      </CycleEnabledContext.Provider>
    </CoachContext.Provider>
  );
}
