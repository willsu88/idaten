"use client";

import { usePathname } from "next/navigation";
import { MobileNav, Sidebar } from "@/components/sidebar";
import { OnboardingBanner } from "@/components/onboarding-banner";
import { ChatProvider } from "@/components/chat/chat-provider";
import { ChatWidget } from "@/components/chat/chat-widget";
import { CoachProvider } from "@/components/coach-provider";

/**
 * App chrome (sidebar / bottom tabs / onboarding banner / floating chat) for
 * logged-in pages. /login and the public /invite/[token] pages render bare —
 * no nav, no chat, no authed API calls. The /welcome setup wizard is authed
 * but full-screen: it also renders without chrome.
 */
export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();

  if (pathname === "/login" || pathname.startsWith("/invite") || pathname === "/welcome") {
    return <main className="min-h-dvh">{children}</main>;
  }

  return (
    // ChatProvider mounts ONCE here so chat state (thread, session, an
    // in-flight stream) survives panel close/open and page navigation.
    <CoachProvider>
      <ChatProvider>
        <Sidebar />
        <MobileNav />
        <main className="min-h-dvh pb-[calc(4.75rem+env(safe-area-inset-bottom))] md:pb-0 md:pl-56">
          <div className="mx-auto w-full max-w-5xl px-4 py-6 md:px-8 md:py-8">
            <OnboardingBanner />
            {children}
          </div>
        </main>
        <ChatWidget />
      </ChatProvider>
    </CoachProvider>
  );
}
