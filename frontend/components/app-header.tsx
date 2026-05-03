import Link from "next/link";
import { cn } from "@/lib/utils";

const NAV: Array<{ href: string; label: string }> = [
  { href: "/campaigns", label: "Campaigns" },
];

export function AppHeader({ activePath }: { activePath?: string }) {
  return (
    <header
      data-testid="app-header"
      className="sticky top-0 z-30 w-full border-b border-border bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/80"
    >
      {/* subtle top accent line */}
      <div className="h-px w-full bg-gradient-to-r from-transparent via-brand/60 to-transparent" />
      <div className="mx-auto flex h-14 max-w-7xl items-center gap-6 px-6">
        <Link href="/campaigns" className="flex items-center gap-3" data-testid="wordmark">
          <span className="font-heading text-base font-semibold tracking-widest uppercase">
            <span className="text-brand">Vistaline</span>
            <span className="text-gold">Digital</span>
          </span>
          <span
            aria-hidden
            className="hidden h-4 w-px bg-border sm:block"
          />
          <span className="hidden text-xs tracking-widest uppercase text-muted-foreground sm:block">
            Lead Sourcer
          </span>
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
                  "rounded-sm px-3 py-1.5 text-xs tracking-wider uppercase text-muted-foreground transition-colors hover:bg-muted hover:text-foreground",
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
          <span className="rounded-sm border border-border bg-muted px-2 py-1 font-mono text-foreground">DG</span>
        </div>
      </div>
    </header>
  );
}
