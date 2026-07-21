"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Activity,
  CalendarDays,
  Droplets,
  Flag,
  Footprints,
  MessageSquare,
  MoreHorizontal,
  Settings,
  Shield,
  Sun,
  TrendingUp,
} from "lucide-react";
import { useCycleEnabled, useIsAdmin } from "@/components/coach-provider";
import { cn } from "@/lib/utils";

const CYCLE_NAV = { href: "/settings/cycle", label: "Cycle", icon: Droplets };
// Household administration — shown only to the admin (page + API are gated too).
const ADMIN_NAV = { href: "/admin", label: "Admin", icon: Shield };

const NAV = [
  { href: "/", label: "Today", icon: Sun },
  { href: "/week", label: "Week", icon: CalendarDays },
  { href: "/chat", label: "Chat", icon: MessageSquare },
  { href: "/trends", label: "Trends", icon: TrendingUp },
  { href: "/races", label: "Races", icon: Flag },
  { href: "/activities", label: "Activities", icon: Footprints },
  { href: "/settings", label: "Settings", icon: Settings },
  // About is hidden from the nav for now (route + page kept, see app/about).
];

function isActive(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/";
  // /settings must NOT claim /settings/cycle — that has its own nav item.
  if (href === "/settings") return pathname === "/settings";
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function Sidebar() {
  const pathname = usePathname();
  const cycleEnabled = useCycleEnabled();
  const isAdmin = useIsAdmin();
  // Slot "Cycle" right after Settings when tracking is on; append "Admin" last.
  const withCycle = cycleEnabled
    ? NAV.flatMap((item) => (item.href === "/settings" ? [item, CYCLE_NAV] : [item]))
    : NAV;
  const nav = isAdmin ? [...withCycle, ADMIN_NAV] : withCycle;

  return (
    <aside className="fixed inset-y-0 left-0 z-40 hidden w-56 flex-col border-r border-border bg-card px-3 py-5 md:flex">
      <Link href="/" className="mb-8 flex items-center gap-2.5 px-2">
        <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-accent text-accent-foreground">
          <Activity className="h-5 w-5" />
        </span>
        <span className="text-base font-semibold tracking-tight">Idaten</span>
      </Link>
      <nav className="flex flex-col gap-1">
        {nav.map(({ href, label, icon: Icon }) => {
          const active = isActive(pathname, href);
          return (
            <Link
              key={href}
              href={href}
              className={cn(
                "flex items-center gap-3 rounded-xl px-3 py-2 text-sm font-medium transition-colors",
                active
                  ? "bg-accent/10 text-accent"
                  : "text-muted-foreground hover:bg-muted hover:text-foreground",
              )}
            >
              <Icon className="h-4 w-4" />
              {label}
            </Link>
          );
        })}
      </nav>
      <p className="mt-auto px-3 text-xs text-muted-foreground">Personal AI running coach</p>
    </aside>
  );
}

// Bottom tab bar (below md): Today / Week / Trends + "More" sheet.
// Chat lives in the floating bubble on mobile, so it's not repeated here.
const PRIMARY_TABS = [
  { href: "/", label: "Today", icon: Sun, fillActive: true },
  { href: "/week", label: "Week", icon: CalendarDays, fillActive: true },
  { href: "/trends", label: "Trends", icon: TrendingUp, fillActive: false },
] as const;

const MORE_ITEMS = [
  { href: "/races", label: "Races", icon: Flag },
  { href: "/activities", label: "Activities", icon: Footprints },
  { href: "/settings", label: "Settings", icon: Settings },
  // About is hidden from the nav for now (route + page kept, see app/about).
] as const;

/** Hide the tab bar scrolling down, reveal it scrolling up (or near the top). */
function useHideOnScroll(disabled: boolean): boolean {
  const [hidden, setHidden] = React.useState(false);
  const lastY = React.useRef(0);

  React.useEffect(() => {
    if (disabled) {
      setHidden(false);
      return;
    }
    lastY.current = window.scrollY;
    const onScroll = () => {
      const y = window.scrollY;
      const delta = y - lastY.current;
      if (y < 24) {
        setHidden(false);
      } else if (delta > 8) {
        setHidden(true);
      } else if (delta < -8) {
        setHidden(false);
      }
      lastY.current = y;
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, [disabled]);

  return hidden;
}

export function MobileNav() {
  const pathname = usePathname();
  const cycleEnabled = useCycleEnabled();
  const isAdmin = useIsAdmin();
  const [moreOpen, setMoreOpen] = React.useState(false);
  const withCycle = cycleEnabled
    ? MORE_ITEMS.flatMap((item) => (item.href === "/settings" ? [item, CYCLE_NAV] : [item]))
    : MORE_ITEMS;
  const moreItems = isAdmin ? [...withCycle, ADMIN_NAV] : withCycle;

  // Close the sheet whenever navigation happens.
  React.useEffect(() => setMoreOpen(false), [pathname]);

  const moreActive = moreItems.some((item) => isActive(pathname, item.href));
  // Keep the bar visible while the More sheet is anchored to it.
  const hidden = useHideOnScroll(moreOpen);

  return (
    <>
      {moreOpen && (
        <div className="fixed inset-0 z-40 md:hidden">
          <div
            className="absolute inset-0 bg-black/50 backdrop-blur-sm"
            onClick={() => setMoreOpen(false)}
          />
          <div className="absolute inset-x-0 bottom-[calc(3.75rem+env(safe-area-inset-bottom))] rounded-t-2xl border-t border-border bg-card p-3 shadow-xl">
            <p className="px-3 pb-2 pt-1 text-xs font-medium uppercase tracking-wider text-muted-foreground">
              More
            </p>
            {moreItems.map(({ href, label, icon: Icon }) => {
              const active = isActive(pathname, href);
              return (
                <Link
                  key={href}
                  href={href}
                  onClick={() => setMoreOpen(false)}
                  className={cn(
                    "flex min-h-11 items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium",
                    active ? "bg-accent/10 text-accent" : "text-foreground hover:bg-muted",
                  )}
                >
                  <Icon className="h-4 w-4" />
                  {label}
                </Link>
              );
            })}
          </div>
        </div>
      )}

      <nav
        className={cn(
          "fixed inset-x-0 bottom-0 z-40 flex border-t border-border/60 bg-card/80 backdrop-blur-lg pb-[env(safe-area-inset-bottom)] transition-transform duration-200 md:hidden",
          hidden && "translate-y-full",
        )}
      >
        {PRIMARY_TABS.map(({ href, label, icon: Icon, fillActive }) => {
          const active = isActive(pathname, href) && !moreOpen;
          return (
            <Link
              key={href}
              href={href}
              onClick={() => setMoreOpen(false)}
              className={cn(
                "flex min-h-[3.75rem] flex-1 flex-col items-center justify-center gap-1 text-[11px] font-medium",
                active ? "text-accent" : "text-muted-foreground",
              )}
            >
              <Icon
                className="h-4 w-4"
                // "Filled" active variant; icons that fill badly get a heavier stroke instead.
                fill={active && fillActive ? "currentColor" : "none"}
                strokeWidth={active && !fillActive ? 2.75 : 2}
              />
              {label}
            </Link>
          );
        })}
        <button
          type="button"
          onClick={() => setMoreOpen((v) => !v)}
          aria-expanded={moreOpen}
          className={cn(
            "flex min-h-[3.75rem] flex-1 flex-col items-center justify-center gap-1 text-[11px] font-medium",
            moreOpen || moreActive ? "text-accent" : "text-muted-foreground",
          )}
        >
          <MoreHorizontal
            className="h-4 w-4"
            fill={moreOpen || moreActive ? "currentColor" : "none"}
          />
          More
        </button>
      </nav>
    </>
  );
}
