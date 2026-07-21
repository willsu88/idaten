"use client";

import * as React from "react";
import { createPortal } from "react-dom";
import { cn } from "@/lib/utils";

/**
 * Minimal dropdown menu: a trigger + a panel that closes on outside-click or
 * Escape. Not a full ARIA menu (no roving focus) — enough for a compact
 * overflow of actions on small screens.
 *
 * The panel renders through a portal to <body> with fixed positioning anchored
 * to the trigger. That's load-bearing: callers (e.g. the week-view day cards)
 * live inside an `overflow-hidden` container, which would clip an in-flow
 * absolutely-positioned menu regardless of z-index. A portal escapes every
 * ancestor's overflow/transform/stacking context.
 */
export function DropdownMenu({
  trigger,
  children,
  align = "end",
  className,
}: {
  trigger: React.ReactNode;
  children: React.ReactNode;
  align?: "start" | "end";
  className?: string;
}) {
  const [open, setOpen] = React.useState(false);
  const [style, setStyle] = React.useState<React.CSSProperties | null>(null);
  const triggerRef = React.useRef<HTMLDivElement>(null);
  const menuRef = React.useRef<HTMLDivElement>(null);

  const place = React.useCallback(() => {
    const el = triggerRef.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    // Flip above the trigger when there isn't room for the panel below it —
    // the common case on mobile where the card sits low in the viewport.
    const openUp = window.innerHeight - r.bottom < 180;
    // Clamp horizontally so the panel never overflows a narrow viewport.
    // First pass estimates the width (min-w-[13rem] = 208px); the second pass
    // below re-measures the mounted panel.
    const menuW = menuRef.current?.offsetWidth ?? 208;
    const margin = 16;
    const desiredLeft = align === "end" ? r.right - menuW : r.left;
    const left = Math.max(
      margin,
      Math.min(desiredLeft, window.innerWidth - menuW - margin),
    );
    setStyle({
      position: "fixed",
      ...(openUp ? { bottom: window.innerHeight - r.top + 4 } : { top: r.bottom + 4 }),
      left,
    });
  }, [align]);

  React.useLayoutEffect(() => {
    if (!open) return;
    place();
    const onReflow = () => place();
    window.addEventListener("scroll", onReflow, true);
    window.addEventListener("resize", onReflow);
    return () => {
      window.removeEventListener("scroll", onReflow, true);
      window.removeEventListener("resize", onReflow);
    };
  }, [open, place]);

  // Second placement pass once the panel is mounted: place() can now measure
  // the real width instead of the 208px estimate, so the clamp is exact.
  const placed = Boolean(style);
  React.useLayoutEffect(() => {
    if (open && placed) place();
  }, [open, placed, place]);

  React.useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      const t = e.target as Node;
      if (triggerRef.current?.contains(t) || menuRef.current?.contains(t)) return;
      setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div ref={triggerRef} className={cn("relative", className)}>
      {/* eslint-disable-next-line jsx-a11y/no-static-element-interactions, jsx-a11y/click-events-have-key-events */}
      <div onClick={() => setOpen((o) => !o)}>{trigger}</div>
      {open &&
        style &&
        typeof document !== "undefined" &&
        createPortal(
          <div
            ref={menuRef}
            role="menu"
            onClick={() => setOpen(false)}
            style={style}
            className="z-50 min-w-[13rem] max-w-[calc(100vw-2rem)] rounded-xl border border-border bg-background p-1 shadow-lg"
          >
            {children}
          </div>,
          document.body,
        )}
    </div>
  );
}

export function DropdownItem({
  onClick,
  disabled,
  children,
}: {
  onClick?: () => void;
  disabled?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      role="menuitem"
      onClick={onClick}
      disabled={disabled}
      className="flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-sm font-medium transition-colors hover:bg-muted/60 disabled:pointer-events-none disabled:opacity-50"
    >
      {children}
    </button>
  );
}
