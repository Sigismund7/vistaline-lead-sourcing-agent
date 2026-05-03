import Link from "next/link";
import { cn } from "@/lib/utils";

const NAV: Array<{ href: string; label: string }> = [
  { href: "/campaigns", label: "Campaigns" },
];

export function AppHeader({ activePath }: { activePath?: string }) {
  return (
    <header
      data-testid="app-header"
      className="sticky top-0 z-30 w-full border-b border-border/60 bg-background/80 backdrop-blur supports-[backdrop-filter]:bg-background/60"
    >
      <div className="mx-auto flex h-14 max-w-7xl items-center gap-6 px-6">
        <Link href="/campaigns" className="flex items-center gap-3" data-testid="wordmark">
          <span className="text-lg font-semibold tracking-tight">
            <span className="text-brand">Vistaline</span>
            <span className="text-foreground">Digital</span>
          </span>
          <span
            aria-hidden
            className="hidden h-5 w-px bg-border sm:block"
          />
          <span className="hidden text-sm text-muted-foreground sm:block">Lead Sourcer</span>
        </Link>
        <nav className="ml-2 flex items-center gap-1 text-sm">
          {NAV.map((item) => {
            const active = activePath?.startsWith(item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "rounded-md px-3 py-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground",
                  active && "bg-muted text-foreground",
                )}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>
        <div className="ml-auto flex items-center gap-3 text-xs text-muted-foreground">
          <span className="hidden sm:inline">$3.21 spend MTD</span>
          <span
            aria-hidden
            className="hidden h-4 w-px bg-border sm:block"
          />
          <span className="rounded-full bg-muted px-2 py-1 font-medium text-foreground">DG</span>
        </div>
      </div>
    </header>
  );
}
