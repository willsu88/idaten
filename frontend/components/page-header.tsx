import { ThemeToggle } from "@/components/theme-toggle";

export function PageHeader({
  title,
  subtitle,
  actions,
  titleActions,
}: {
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  actions?: React.ReactNode;
  // Compact icon controls pinned in the title row beside the theme toggle
  // (e.g. Today's sync) — for anything that would look stranded below the
  // subtitle as a lone `actions` button.
  titleActions?: React.ReactNode;
}) {
  // The theme toggle is app chrome: it stays pinned to the title row on every
  // page and never wraps below with page-specific actions.
  return (
    <header className="mb-6">
      <div className="flex items-start justify-between gap-4">
        <h1 className="min-w-0 text-2xl font-semibold tracking-tight">{title}</h1>
        <div className="flex shrink-0 items-center gap-1">
          {titleActions}
          <ThemeToggle />
        </div>
      </div>
      {subtitle && <div className="mt-1.5 text-sm text-muted-foreground">{subtitle}</div>}
      {actions && <div className="mt-3 flex flex-wrap items-center gap-2">{actions}</div>}
    </header>
  );
}
