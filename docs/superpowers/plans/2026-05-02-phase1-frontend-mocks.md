# Phase 1 Frontend Mocks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build static, clickable mock pages for the hosted Vistaline lead-sourcing UI in `frontend/`. No real auth, no API wiring, no live data. Mock data drives every screen so the operator can review and iterate on the UX before Phase 2 wires Clerk + FastAPI.

**Architecture:** Next.js 16 App Router in `frontend/` (sibling to the Python pipeline at repo root — root stays untouched). Tailwind v4 + shadcn/ui + Geist for the design layer. Static mock data in `frontend/lib/mocks/` powers each route. Playwright smoke tests prove each page renders. The header wordmark, brand blue, and overall density mirror vistalinedigital.com (which is built on v0/shadcn) so brand transfer is automatic.

**Tech Stack:** Next.js 16.2 (App Router, Turbopack), React 19, TypeScript 5.9, Tailwind v4, shadcn/ui, Geist (already wired), Playwright (chromium-only), bun.

**Reference docs:**
- `docs/frontend-plan.md` — architecture, brand, locked decisions. Read §2 (brand), §5 (UX patterns), §6 (niche catalog) before starting.
- `frontend/AGENTS.md` — warns Next.js 16 has breaking changes; consult `frontend/node_modules/next/dist/docs/` if a Next API behaves unexpectedly. Notably: dynamic route `params` is a `Promise` and must be `await`ed in server components or `use()`'d in client components.
- This plan implements the Phase 1 row from `docs/frontend-plan.md` §8.

**Working directory:** All commands run from repo root (`/Users/daschelgorgenyi/Desktop/Vistaline-Lead Sourcing Agent`) unless stated otherwise.

**Branch:** `phase1-frontend-skeleton` (already created and checked out).

---

## File structure (locked)

```
frontend/
├── app/
│   ├── layout.tsx              ← updated (Task 1)
│   ├── globals.css             ← updated (Task 1)
│   ├── page.tsx                ← updated to redirect to /campaigns (Task 3)
│   ├── campaigns/
│   │   ├── page.tsx            ← created Task 6 — campaigns list
│   │   ├── new/page.tsx        ← created Task 7 — new-campaign form
│   │   └── [id]/
│   │       ├── page.tsx        ← created Task 8 — live run view
│   │       └── results/page.tsx ← created Task 9 — results table
├── components/
│   ├── ui/                     ← shadcn components (Task 2, auto-generated)
│   └── app-header.tsx          ← Task 4
├── lib/
│   ├── utils.ts                ← shadcn cn() (Task 2, auto-generated)
│   ├── types.ts                ← Task 5
│   └── mocks/
│       ├── niches.ts           ← Task 5
│       ├── campaigns.ts        ← Task 5
│       ├── events.ts           ← Task 5
│       └── leads.ts            ← Task 5
├── tests/
│   └── e2e/
│       ├── home.spec.ts        ← Task 3
│       ├── header.spec.ts      ← Task 4
│       ├── campaigns.spec.ts   ← Task 6
│       ├── new-campaign.spec.ts ← Task 7
│       ├── live-run.spec.ts    ← Task 8
│       └── results.spec.ts     ← Task 9
├── playwright.config.ts        ← Task 3
├── components.json             ← Task 2 (shadcn config)
└── (existing scaffold files)
```

Each page imports from `@/components/ui/*`, `@/components/app-header`, and `@/lib/mocks/*`. Page-specific UI fragments (StepRail, EventCard, NicheCombobox, etc.) live inline in the page file unless reused — keeps the file tree shallow and tasks self-contained.

---

## Task 1: Brand tokens + Geist polish

**Files:**
- Modify: `frontend/app/layout.tsx` (replace boilerplate metadata + className)
- Modify: `frontend/app/globals.css` (add brand color CSS vars + override default body font to Geist)

- [ ] **Step 1: Replace `frontend/app/layout.tsx` with branded version**

```tsx
import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Vistaline Lead Sourcer",
  description: "Source FindyMail-ready leads for residential contractors.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col bg-background text-foreground font-sans">
        {children}
      </body>
    </html>
  );
}
```

- [ ] **Step 2: Replace `frontend/app/globals.css` with brand-tokenized version**

```css
@import "tailwindcss";

:root {
  --background: #ffffff;
  --foreground: #0a0a0a;
  --muted: #f4f4f5;
  --muted-foreground: #52525b;
  --border: #e4e4e7;
  --input: #e4e4e7;
  --ring: #2563eb;
  --brand: #2563eb;
  --brand-hover: #1d4ed8;
  --brand-foreground: #ffffff;
  --success: #16a34a;
  --warning: #d97706;
  --danger: #dc2626;
  --info: #2563eb;
}

@media (prefers-color-scheme: dark) {
  :root {
    --background: #0a0a0a;
    --foreground: #fafafa;
    --muted: #18181b;
    --muted-foreground: #a1a1aa;
    --border: #27272a;
    --input: #27272a;
    --ring: #3b82f6;
    --brand: #3b82f6;
    --brand-hover: #2563eb;
    --brand-foreground: #ffffff;
  }
}

@theme inline {
  --color-background: var(--background);
  --color-foreground: var(--foreground);
  --color-muted: var(--muted);
  --color-muted-foreground: var(--muted-foreground);
  --color-border: var(--border);
  --color-input: var(--input);
  --color-ring: var(--ring);
  --color-brand: var(--brand);
  --color-brand-hover: var(--brand-hover);
  --color-brand-foreground: var(--brand-foreground);
  --color-success: var(--success);
  --color-warning: var(--warning);
  --color-danger: var(--danger);
  --color-info: var(--info);
  --font-sans: var(--font-geist-sans);
  --font-mono: var(--font-geist-mono);
}
```

- [ ] **Step 3: Start dev server and confirm it boots**

Run (from repo root):
```bash
cd frontend && bun dev
```
Expected: line containing `Ready in <ms>` and `Local: http://localhost:3000`. Stop the server with Ctrl-C after confirming. (Do NOT leave it running for the next steps — Task 3 will manage it via Playwright's `webServer`.)

- [ ] **Step 4: Commit**

```bash
git add frontend/app/layout.tsx frontend/app/globals.css
git commit -m "Phase 1.1: brand tokens and Geist polish"
```

---

## Task 2: shadcn/ui init + base components

**Files:**
- Create: `frontend/components.json` (via shadcn CLI)
- Create: `frontend/lib/utils.ts` (via shadcn CLI)
- Create: `frontend/components/ui/*.tsx` (via shadcn CLI)
- Modify: `frontend/package.json` (deps added by CLI)

- [ ] **Step 1: Initialize shadcn/ui non-interactively**

Run:
```bash
cd frontend && bunx shadcn@latest init --yes --base-color neutral --css-variables
```

Expected: creates `components.json`, `lib/utils.ts`, adds dependencies (`class-variance-authority`, `clsx`, `tailwind-merge`, `lucide-react`, `tw-animate-css`). Updates `app/globals.css` with shadcn's design-token block. **If the CLI overwrites the brand vars from Task 1, redo step 2 of Task 1 by re-adding the `--brand*`, `--success`, `--warning`, `--danger`, `--info` vars to `:root` and the `@theme inline` block — keep shadcn's other additions intact.**

- [ ] **Step 2: Verify components.json picked correct paths**

Run:
```bash
cat frontend/components.json
```
Expected: contains `"style": "default"`, `"rsc": true`, `"tsx": true`, `"tailwind": { "css": "app/globals.css", "baseColor": "neutral", "cssVariables": true }`, `"aliases": { "components": "@/components", "utils": "@/lib/utils", "ui": "@/components/ui", "lib": "@/lib", "hooks": "@/hooks" }`.

- [ ] **Step 3: Add the components needed for all mocks**

Run:
```bash
cd frontend && bunx shadcn@latest add --yes button input label card badge table separator sheet dialog command popover select sonner scroll-area checkbox skeleton tooltip
```

Expected: each component prints `✓ Created components/ui/<name>.tsx`. Adds `@radix-ui/*` peers as deps.

- [ ] **Step 4: Smoke-test that components import**

Create `frontend/scratch-import-check.tsx` with:
```tsx
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Table } from "@/components/ui/table";
import { Command } from "@/components/ui/command";
import { Popover } from "@/components/ui/popover";
import { Select } from "@/components/ui/select";
import { Checkbox } from "@/components/ui/checkbox";
import { Badge } from "@/components/ui/badge";

export const _smoke = { Button, Card, Input, Table, Command, Popover, Select, Checkbox, Badge };
```

Run:
```bash
cd frontend && bunx tsc --noEmit -p tsconfig.json
```
Expected: zero errors. Then delete the scratch file:
```bash
rm frontend/scratch-import-check.tsx
```

- [ ] **Step 5: Commit**

```bash
git add frontend/
git commit -m "Phase 1.2: shadcn/ui init + base components"
```

---

## Task 3: Playwright + home redirect

**Files:**
- Create: `frontend/playwright.config.ts`
- Create: `frontend/tests/e2e/home.spec.ts`
- Modify: `frontend/app/page.tsx` (replace boilerplate with redirect)
- Modify: `frontend/package.json` (add test script)
- Modify: `frontend/.gitignore` (add `test-results`, `playwright-report`)

- [ ] **Step 1: Install Playwright**

Run:
```bash
cd frontend && bun add -D @playwright/test && bunx playwright install chromium --with-deps
```

Expected: `@playwright/test` added; chromium downloaded. (`--with-deps` may prompt for sudo on Linux; on macOS it's a no-op.)

- [ ] **Step 2: Create `frontend/playwright.config.ts`**

```ts
import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: "http://localhost:3000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: {
    command: "bun run dev",
    url: "http://localhost:3000",
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
```

- [ ] **Step 3: Add test + Playwright scripts to `frontend/package.json`**

Edit `frontend/package.json` `scripts` block to:
```json
"scripts": {
  "dev": "next dev",
  "build": "next build",
  "start": "next start",
  "test:e2e": "playwright test",
  "test:e2e:ui": "playwright test --ui"
},
```

- [ ] **Step 4: Update `frontend/.gitignore`**

Append to existing `frontend/.gitignore`:
```
# playwright
/test-results/
/playwright-report/
/playwright/.cache/
```

- [ ] **Step 5: Write the failing test `frontend/tests/e2e/home.spec.ts`**

```ts
import { test, expect } from "@playwright/test";

test("home redirects to /campaigns", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveURL("/campaigns");
});
```

- [ ] **Step 6: Run the test — confirm it fails**

Run:
```bash
cd frontend && bun run test:e2e tests/e2e/home.spec.ts
```
Expected: FAIL — page does not redirect (or `/campaigns` 404s).

- [ ] **Step 7: Replace `frontend/app/page.tsx` with redirect**

```tsx
import { redirect } from "next/navigation";

export default function HomePage() {
  redirect("/campaigns");
}
```

- [ ] **Step 8: Add a placeholder `frontend/app/campaigns/page.tsx` so the redirect target 200s**

```tsx
export default function CampaignsPlaceholder() {
  return <main className="p-8">Campaigns dashboard coming in Task 6.</main>;
}
```

- [ ] **Step 9: Run the test — confirm it passes**

Run:
```bash
cd frontend && bun run test:e2e tests/e2e/home.spec.ts
```
Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add frontend/
git commit -m "Phase 1.3: playwright setup + home redirect"
```

---

## Task 4: AppHeader component + root layout integration

**Files:**
- Create: `frontend/components/app-header.tsx`
- Modify: `frontend/app/layout.tsx` (mount header)
- Create: `frontend/tests/e2e/header.spec.ts`

- [ ] **Step 1: Write the failing test `frontend/tests/e2e/header.spec.ts`**

```ts
import { test, expect } from "@playwright/test";

test("global header renders the VistalineDigital wordmark and active nav", async ({ page }) => {
  await page.goto("/campaigns");
  await expect(page.getByTestId("app-header")).toBeVisible();
  const wordmark = page.getByTestId("wordmark");
  await expect(wordmark).toContainText("Vistaline");
  await expect(wordmark).toContainText("Digital");
  await expect(page.getByRole("link", { name: "Campaigns" })).toBeVisible();
  await expect(page.getByText("Lead Sourcer")).toBeVisible();
});
```

- [ ] **Step 2: Run the test — confirm it fails**

Run:
```bash
cd frontend && bun run test:e2e tests/e2e/header.spec.ts
```
Expected: FAIL — `app-header` testid not found.

- [ ] **Step 3: Create `frontend/components/app-header.tsx`**

```tsx
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
```

- [ ] **Step 4: Update `frontend/app/layout.tsx` to mount the header**

Replace contents of `frontend/app/layout.tsx` with:

```tsx
import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { AppHeader } from "@/components/app-header";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Vistaline Lead Sourcer",
  description: "Source FindyMail-ready leads for residential contractors.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col bg-background text-foreground font-sans">
        <AppHeader activePath="/campaigns" />
        <main className="flex-1">{children}</main>
      </body>
    </html>
  );
}
```

(Active-nav highlighting based on the URL is improved per-page in later tasks via a client component if needed; hard-coding `/campaigns` is acceptable for the mock since every route lives under it.)

- [ ] **Step 5: Run the test — confirm it passes**

Run:
```bash
cd frontend && bun run test:e2e tests/e2e/header.spec.ts
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/
git commit -m "Phase 1.4: app header with branded wordmark"
```

---

## Task 5: Mock data files

**Files:**
- Create: `frontend/lib/types.ts`
- Create: `frontend/lib/mocks/niches.ts`
- Create: `frontend/lib/mocks/campaigns.ts`
- Create: `frontend/lib/mocks/events.ts`
- Create: `frontend/lib/mocks/leads.ts`

- [ ] **Step 1: Create `frontend/lib/types.ts`**

```ts
export type CampaignStatus = "queued" | "running" | "completed" | "failed";

export type StepName =
  | "sourcer"
  | "lead_filter"
  | "owner_researcher"
  | "csv_assembler";

export type StepStatus = "queued" | "running" | "done" | "failed" | "skipped";

export type EventLevel = "info" | "warn" | "error" | "success";

export interface NichePreset {
  slug: string;
  displayName: string;
  defaultKeyword: string;
  keywordVariants: string[];
}

export interface Campaign {
  id: string;
  city: string;
  stateAbbr: string;
  niche: string;
  targetCount: number;
  status: CampaignStatus;
  createdAt: string;
  completedAt?: string;
  totalLeads: number;
  keptLeads: number;
  withOwner: number;
  withEmail: number;
  spendUsd: number;
  triggeredBy: string;
}

export interface RunEvent {
  id: string;
  step: StepName;
  level: EventLevel;
  message: string;
  detail?: string;
  durationMs?: number;
  ts: string;
}

export interface StepProgress {
  step: StepName;
  label: string;
  status: StepStatus;
  durationMs?: number;
  summary?: string;
}

export interface Lead {
  id: string;
  businessName: string;
  phone: string;
  website: string;
  domain: string;
  address: string;
  areaCode: string;
  ownerFirst: string;
  ownerLast: string;
  ownerSource: "website" | "bbb" | "google" | "";
  email: string;
  kept: boolean;
  excludedByUser: boolean;
  rejectReason: string;
}
```

- [ ] **Step 2: Create `frontend/lib/mocks/niches.ts`**

```ts
import type { NichePreset } from "@/lib/types";

export const NICHE_PRESETS: NichePreset[] = [
  {
    slug: "kitchen-remodelers",
    displayName: "Kitchen remodelers",
    defaultKeyword: "kitchen remodelers",
    keywordVariants: ["kitchen remodeling", "kitchen renovation", "custom kitchen builder"],
  },
  {
    slug: "bathroom-remodelers",
    displayName: "Bathroom remodelers",
    defaultKeyword: "bathroom remodelers",
    keywordVariants: ["bathroom remodeling", "bathroom renovation", "shower remodel"],
  },
  {
    slug: "roofing",
    displayName: "Roofing",
    defaultKeyword: "roofing contractors",
    keywordVariants: ["roof repair", "roof replacement", "metal roofing"],
  },
  {
    slug: "hvac",
    displayName: "HVAC",
    defaultKeyword: "HVAC contractors",
    keywordVariants: ["air conditioning installation", "heating and cooling", "AC repair"],
  },
  {
    slug: "deck-builders",
    displayName: "Deck builders",
    defaultKeyword: "deck builders",
    keywordVariants: ["deck construction", "patio builders", "outdoor decking"],
  },
  {
    slug: "pool-builders",
    displayName: "Pool builders",
    defaultKeyword: "pool builders",
    keywordVariants: ["swimming pool installation", "custom pool design", "pool contractors"],
  },
  {
    slug: "adu-builders",
    displayName: "ADU / granny flat builders",
    defaultKeyword: "ADU builders",
    keywordVariants: ["accessory dwelling unit", "granny flat builder", "casita construction"],
  },
  {
    slug: "garage-conversions",
    displayName: "Garage conversions",
    defaultKeyword: "garage conversion contractors",
    keywordVariants: ["garage to living space", "garage remodel", "garage conversion"],
  },
  {
    slug: "whole-home-remodels",
    displayName: "Whole-home remodels",
    defaultKeyword: "whole home remodelers",
    keywordVariants: ["full home renovation", "complete home remodel", "general contractor remodel"],
  },
  {
    slug: "painters",
    displayName: "Painters",
    defaultKeyword: "residential painters",
    keywordVariants: ["interior painters", "exterior painters", "house painting"],
  },
  {
    slug: "flooring",
    displayName: "Flooring",
    defaultKeyword: "flooring contractors",
    keywordVariants: ["hardwood flooring", "tile installation", "luxury vinyl plank"],
  },
  {
    slug: "landscapers",
    displayName: "Landscapers",
    defaultKeyword: "landscaping contractors",
    keywordVariants: ["landscape design", "lawn care", "outdoor living"],
  },
];
```

- [ ] **Step 3: Create `frontend/lib/mocks/campaigns.ts`**

```ts
import type { Campaign } from "@/lib/types";

export const MOCK_CAMPAIGNS: Campaign[] = [
  {
    id: "20260502-153012-a1b2c3",
    city: "Tampa",
    stateAbbr: "FL",
    niche: "Bathroom remodelers",
    targetCount: 50,
    status: "running",
    createdAt: "2026-05-02T15:30:12Z",
    totalLeads: 31,
    keptLeads: 19,
    withOwner: 7,
    withEmail: 2,
    spendUsd: 1.42,
    triggeredBy: "Daschel",
  },
  {
    id: "20260502-103940-d4e5f6",
    city: "Orlando",
    stateAbbr: "FL",
    niche: "Kitchen remodelers",
    targetCount: 50,
    status: "completed",
    createdAt: "2026-05-02T10:39:40Z",
    completedAt: "2026-05-02T10:51:22Z",
    totalLeads: 47,
    keptLeads: 38,
    withOwner: 31,
    withEmail: 12,
    spendUsd: 2.18,
    triggeredBy: "Daschel",
  },
  {
    id: "20260501-184501-g7h8i9",
    city: "Austin",
    stateAbbr: "TX",
    niche: "HVAC",
    targetCount: 75,
    status: "failed",
    createdAt: "2026-05-01T18:45:01Z",
    totalLeads: 22,
    keptLeads: 0,
    withOwner: 0,
    withEmail: 0,
    spendUsd: 0.31,
    triggeredBy: "Daschel",
  },
  {
    id: "20260430-141220-j0k1l2",
    city: "Miami",
    stateAbbr: "FL",
    niche: "Roofing",
    targetCount: 50,
    status: "completed",
    createdAt: "2026-05-01T14:12:20Z",
    completedAt: "2026-05-01T14:24:09Z",
    totalLeads: 50,
    keptLeads: 42,
    withOwner: 35,
    withEmail: 18,
    spendUsd: 2.64,
    triggeredBy: "Daschel",
  },
  {
    id: "20260429-094533-m3n4o5",
    city: "Phoenix",
    stateAbbr: "AZ",
    niche: "Pool builders",
    targetCount: 40,
    status: "completed",
    createdAt: "2026-04-29T09:45:33Z",
    completedAt: "2026-04-29T09:55:48Z",
    totalLeads: 36,
    keptLeads: 28,
    withOwner: 21,
    withEmail: 9,
    spendUsd: 1.78,
    triggeredBy: "Teammate",
  },
  {
    id: "20260428-160055-p6q7r8",
    city: "Charlotte",
    stateAbbr: "NC",
    niche: "Deck builders",
    targetCount: 50,
    status: "completed",
    createdAt: "2026-04-28T16:00:55Z",
    completedAt: "2026-04-28T16:13:31Z",
    totalLeads: 44,
    keptLeads: 30,
    withOwner: 22,
    withEmail: 8,
    spendUsd: 2.05,
    triggeredBy: "Teammate",
  },
];
```

- [ ] **Step 4: Create `frontend/lib/mocks/events.ts`**

```ts
import type { RunEvent, StepProgress } from "@/lib/types";

export const MOCK_STEPS: StepProgress[] = [
  {
    step: "sourcer",
    label: "Source candidates",
    status: "done",
    durationMs: 4_200,
    summary: "47 unique businesses across Azure Maps + Yelp Fusion",
  },
  {
    step: "lead_filter",
    label: "Filter with Claude",
    status: "done",
    durationMs: 12_900,
    summary: "30 kept, 17 rejected (multi-trade, residential mismatch, no website)",
  },
  {
    step: "owner_researcher",
    label: "Identify owners",
    status: "running",
    summary: "Phase 1 website crawl: 19/30 complete",
  },
  {
    step: "csv_assembler",
    label: "Assemble CSV",
    status: "queued",
  },
];

export const MOCK_EVENTS: RunEvent[] = [
  {
    id: "evt-001",
    step: "sourcer",
    level: "info",
    message: "Sourcer started",
    ts: "2026-05-02T15:30:13Z",
  },
  {
    id: "evt-002",
    step: "sourcer",
    level: "info",
    message: 'Querying Azure Maps for "bathroom remodelers" in Tampa, FL',
    ts: "2026-05-02T15:30:13Z",
  },
  {
    id: "evt-003",
    step: "sourcer",
    level: "success",
    message: "Azure Maps returned 31 candidates",
    durationMs: 1_842,
    ts: "2026-05-02T15:30:15Z",
  },
  {
    id: "evt-004",
    step: "sourcer",
    level: "info",
    message: 'Querying Yelp Fusion for "bathroom remodelers" in Tampa, FL',
    ts: "2026-05-02T15:30:15Z",
  },
  {
    id: "evt-005",
    step: "sourcer",
    level: "success",
    message: "Yelp Fusion returned 24 candidates",
    durationMs: 1_103,
    ts: "2026-05-02T15:30:16Z",
  },
  {
    id: "evt-006",
    step: "sourcer",
    level: "info",
    message: "Deduping by phone + domain (rapidfuzz threshold 92)",
    ts: "2026-05-02T15:30:16Z",
  },
  {
    id: "evt-007",
    step: "sourcer",
    level: "success",
    message: "Sourcer complete · 47 unique businesses",
    durationMs: 4_212,
    ts: "2026-05-02T15:30:17Z",
  },
  {
    id: "evt-008",
    step: "lead_filter",
    level: "info",
    message: "Lead filter started · 47 leads in 2 batches of 25",
    ts: "2026-05-02T15:30:17Z",
  },
  {
    id: "evt-009",
    step: "lead_filter",
    level: "success",
    message: "Batch 1/2 filtered · 18 kept, 7 rejected",
    detail: "rejected: 4× multi-trade, 2× commercial, 1× no website",
    durationMs: 6_412,
    ts: "2026-05-02T15:30:23Z",
  },
  {
    id: "evt-010",
    step: "lead_filter",
    level: "success",
    message: "Batch 2/2 filtered · 12 kept, 10 rejected",
    detail: "rejected: 6× multi-trade, 3× franchise, 1× residential mismatch",
    durationMs: 6_488,
    ts: "2026-05-02T15:30:30Z",
  },
  {
    id: "evt-011",
    step: "lead_filter",
    level: "success",
    message: "Lead filter complete · 30 kept, 17 rejected",
    durationMs: 12_900,
    ts: "2026-05-02T15:30:30Z",
  },
  {
    id: "evt-012",
    step: "owner_researcher",
    level: "info",
    message: "Owner researcher started · Phase 1 website crawl on 30 leads (parallel)",
    ts: "2026-05-02T15:30:30Z",
  },
  {
    id: "evt-013",
    step: "owner_researcher",
    level: "success",
    message: "tampabathremodel.com → owner: Marcus Lloyd · email captured",
    durationMs: 720,
    ts: "2026-05-02T15:30:31Z",
  },
  {
    id: "evt-014",
    step: "owner_researcher",
    level: "warn",
    message: "graceandgrove.com → no owner name found, falling through to Phase 2",
    durationMs: 580,
    ts: "2026-05-02T15:30:31Z",
  },
  {
    id: "evt-015",
    step: "owner_researcher",
    level: "info",
    message: "Phase 1 in progress · 19/30 sites crawled",
    ts: "2026-05-02T15:30:42Z",
  },
];
```

- [ ] **Step 5: Create `frontend/lib/mocks/leads.ts`**

```ts
import type { Lead } from "@/lib/types";

export const MOCK_LEADS: Lead[] = [
  {
    id: "lead-001",
    businessName: "Lloyd & Sons Bath Remodel",
    phone: "(813) 555-0142",
    website: "https://tampabathremodel.com",
    domain: "tampabathremodel.com",
    address: "4421 W Kennedy Blvd, Tampa, FL 33609",
    areaCode: "813",
    ownerFirst: "Marcus",
    ownerLast: "Lloyd",
    ownerSource: "website",
    email: "marcus@tampabathremodel.com",
    kept: true,
    excludedByUser: false,
    rejectReason: "",
  },
  {
    id: "lead-002",
    businessName: "Grace & Grove Bathrooms",
    phone: "(727) 555-0188",
    website: "https://graceandgrove.com",
    domain: "graceandgrove.com",
    address: "112 4th St N, St. Petersburg, FL 33701",
    areaCode: "727",
    ownerFirst: "Avery",
    ownerLast: "Reyes",
    ownerSource: "bbb",
    email: "",
    kept: true,
    excludedByUser: false,
    rejectReason: "",
  },
  {
    id: "lead-003",
    businessName: "Sunrise Tile & Bath",
    phone: "(813) 555-0117",
    website: "https://sunrisetileandbath.com",
    domain: "sunrisetileandbath.com",
    address: "9803 N Florida Ave, Tampa, FL 33612",
    areaCode: "813",
    ownerFirst: "Diana",
    ownerLast: "Pham",
    ownerSource: "website",
    email: "diana@sunrisetileandbath.com",
    kept: true,
    excludedByUser: false,
    rejectReason: "",
  },
  {
    id: "lead-004",
    businessName: "Coastal Bathroom Co.",
    phone: "(813) 555-0166",
    website: "https://coastalbathroom.co",
    domain: "coastalbathroom.co",
    address: "210 Channelside Dr, Tampa, FL 33602",
    areaCode: "813",
    ownerFirst: "Jordan",
    ownerLast: "Whitaker",
    ownerSource: "google",
    email: "",
    kept: true,
    excludedByUser: false,
    rejectReason: "",
  },
  {
    id: "lead-005",
    businessName: "All Pro Bath & Kitchen",
    phone: "(813) 555-0144",
    website: "https://allprobathkitchen.com",
    domain: "allprobathkitchen.com",
    address: "5550 W Hillsborough Ave, Tampa, FL 33614",
    areaCode: "813",
    ownerFirst: "",
    ownerLast: "",
    ownerSource: "",
    email: "",
    kept: false,
    excludedByUser: false,
    rejectReason: "Multi-trade — also markets kitchen and full-home remodels",
  },
  {
    id: "lead-006",
    businessName: "Bay Bathroom Designs",
    phone: "(727) 555-0123",
    website: "https://baybathroomdesigns.com",
    domain: "baybathroomdesigns.com",
    address: "780 Central Ave, St. Petersburg, FL 33701",
    areaCode: "727",
    ownerFirst: "Priya",
    ownerLast: "Shah",
    ownerSource: "website",
    email: "priya@baybathroomdesigns.com",
    kept: true,
    excludedByUser: true,
    rejectReason: "",
  },
  {
    id: "lead-007",
    businessName: "Hillsborough Renovation Co.",
    phone: "(813) 555-0190",
    website: "https://hillsborenovation.com",
    domain: "hillsborenovation.com",
    address: "3702 W Cypress St, Tampa, FL 33607",
    areaCode: "813",
    ownerFirst: "Daniel",
    ownerLast: "Okafor",
    ownerSource: "website",
    email: "daniel@hillsborenovation.com",
    kept: true,
    excludedByUser: false,
    rejectReason: "",
  },
  {
    id: "lead-008",
    businessName: "TampaBay Re-Bath Franchise",
    phone: "(813) 555-0177",
    website: "https://rebath-tampabay.com",
    domain: "rebath-tampabay.com",
    address: "8701 Hidden River Pkwy, Tampa, FL 33637",
    areaCode: "813",
    ownerFirst: "",
    ownerLast: "",
    ownerSource: "",
    email: "",
    kept: false,
    excludedByUser: false,
    rejectReason: "Franchise — corporate ownership, not owner-operator",
  },
  {
    id: "lead-009",
    businessName: "Modern Bath Studio",
    phone: "(813) 555-0156",
    website: "https://modernbathstudio.co",
    domain: "modernbathstudio.co",
    address: "1421 Tampa St, Tampa, FL 33602",
    areaCode: "813",
    ownerFirst: "Elena",
    ownerLast: "Marchetti",
    ownerSource: "website",
    email: "elena@modernbathstudio.co",
    kept: true,
    excludedByUser: false,
    rejectReason: "",
  },
  {
    id: "lead-010",
    businessName: "Riverside Bathrooms LLC",
    phone: "(813) 555-0102",
    website: "https://riversidebathroomsfl.com",
    domain: "riversidebathroomsfl.com",
    address: "2204 N Westshore Blvd, Tampa, FL 33607",
    areaCode: "813",
    ownerFirst: "Connor",
    ownerLast: "McAllister",
    ownerSource: "google",
    email: "",
    kept: true,
    excludedByUser: false,
    rejectReason: "",
  },
];
```

- [ ] **Step 6: Verify TypeScript still passes**

Run:
```bash
cd frontend && bunx tsc --noEmit -p tsconfig.json
```
Expected: zero errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/lib/
git commit -m "Phase 1.5: mock data — niches, campaigns, events, leads"
```

---

## Task 6: Campaigns list page

**Files:**
- Modify: `frontend/app/campaigns/page.tsx` (replace placeholder from Task 3)
- Create: `frontend/tests/e2e/campaigns.spec.ts`

- [ ] **Step 1: Write the failing test `frontend/tests/e2e/campaigns.spec.ts`**

```ts
import { test, expect } from "@playwright/test";

test("campaigns list shows recent runs and a new-campaign button", async ({ page }) => {
  await page.goto("/campaigns");
  await expect(page.getByRole("heading", { name: "Campaigns" })).toBeVisible();
  await expect(page.getByRole("link", { name: /new campaign/i })).toHaveAttribute(
    "href",
    "/campaigns/new",
  );

  // Active running campaign
  await expect(page.getByText("Tampa, FL").first()).toBeVisible();
  await expect(page.getByText("Bathroom remodelers").first()).toBeVisible();
  await expect(page.getByText("running", { exact: false }).first()).toBeVisible();

  // Completed campaign with stats
  await expect(page.getByText("Orlando, FL").first()).toBeVisible();
  await expect(page.getByText("38 / 47").first()).toBeVisible();
});
```

- [ ] **Step 2: Run the test — confirm it fails**

Run:
```bash
cd frontend && bun run test:e2e tests/e2e/campaigns.spec.ts
```
Expected: FAIL — placeholder page does not have "Campaigns" heading or new-campaign link.

- [ ] **Step 3: Implement `frontend/app/campaigns/page.tsx`**

Replace the file's contents with:

```tsx
import Link from "next/link";
import { ArrowUpRight, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { MOCK_CAMPAIGNS } from "@/lib/mocks/campaigns";
import type { CampaignStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

const STATUS_TONE: Record<CampaignStatus, string> = {
  queued: "bg-muted text-muted-foreground",
  running: "bg-info/10 text-info border-info/30",
  completed: "bg-success/10 text-success border-success/30",
  failed: "bg-danger/10 text-danger border-danger/30",
};

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function formatCurrency(value: number): string {
  return value.toLocaleString(undefined, { style: "currency", currency: "USD" });
}

export default function CampaignsPage() {
  const running = MOCK_CAMPAIGNS.filter((c) => c.status === "running");
  const recent = MOCK_CAMPAIGNS.filter((c) => c.status !== "running");

  const totalLeads = MOCK_CAMPAIGNS.reduce((sum, c) => sum + c.keptLeads, 0);
  const totalSpend = MOCK_CAMPAIGNS.reduce((sum, c) => sum + c.spendUsd, 0);

  return (
    <div className="mx-auto max-w-7xl px-6 py-10">
      <div className="flex flex-wrap items-end justify-between gap-4 pb-8">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Campaigns</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Runs initiated by your team. Each campaign produces a FindyMail-ready CSV when it completes.
          </p>
        </div>
        <Button asChild>
          <Link href="/campaigns/new">
            <Plus className="mr-2 size-4" /> New campaign
          </Link>
        </Button>
      </div>

      <div className="grid gap-4 pb-8 sm:grid-cols-3">
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Active runs</CardDescription>
            <CardTitle className="text-2xl">{running.length}</CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Total leads kept (lifetime)</CardDescription>
            <CardTitle className="text-2xl">{totalLeads}</CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Spend (lifetime)</CardDescription>
            <CardTitle className="text-2xl">{formatCurrency(totalSpend)}</CardTitle>
          </CardHeader>
        </Card>
      </div>

      {running.length > 0 && (
        <section className="pb-10">
          <h2 className="pb-3 text-sm font-medium uppercase tracking-wider text-muted-foreground">
            In progress
          </h2>
          <div className="grid gap-3">
            {running.map((c) => (
              <Card key={c.id} className="transition-colors hover:border-brand/50">
                <CardContent className="flex flex-wrap items-center justify-between gap-4 p-4">
                  <div className="flex flex-col gap-1">
                    <div className="flex items-center gap-2">
                      <span className="font-medium">{c.city}, {c.stateAbbr}</span>
                      <Badge variant="outline" className={cn("border", STATUS_TONE[c.status])}>
                        running
                      </Badge>
                    </div>
                    <div className="text-sm text-muted-foreground">
                      {c.niche} · target {c.targetCount} · started {formatDate(c.createdAt)} · {c.triggeredBy}
                    </div>
                  </div>
                  <div className="flex items-center gap-6 text-sm">
                    <div>
                      <span className="text-muted-foreground">progress</span>{" "}
                      <span className="font-medium">{c.keptLeads} / {c.targetCount}</span>
                    </div>
                    <div>
                      <span className="text-muted-foreground">spend</span>{" "}
                      <span className="font-medium">{formatCurrency(c.spendUsd)}</span>
                    </div>
                    <Button asChild variant="outline" size="sm">
                      <Link href={`/campaigns/${c.id}`}>
                        Watch run <ArrowUpRight className="ml-1 size-3.5" />
                      </Link>
                    </Button>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        </section>
      )}

      <section>
        <h2 className="pb-3 text-sm font-medium uppercase tracking-wider text-muted-foreground">
          Recent
        </h2>
        <div className="overflow-hidden rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>City</TableHead>
                <TableHead>Niche</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="text-right">Kept / Total</TableHead>
                <TableHead className="text-right">Owner</TableHead>
                <TableHead className="text-right">Email</TableHead>
                <TableHead className="text-right">Spend</TableHead>
                <TableHead>When</TableHead>
                <TableHead></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {recent.map((c) => (
                <TableRow key={c.id}>
                  <TableCell className="font-medium">{c.city}, {c.stateAbbr}</TableCell>
                  <TableCell className="text-muted-foreground">{c.niche}</TableCell>
                  <TableCell>
                    <Badge variant="outline" className={cn("border capitalize", STATUS_TONE[c.status])}>
                      {c.status}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-right font-mono text-xs">
                    {c.keptLeads} / {c.totalLeads}
                  </TableCell>
                  <TableCell className="text-right font-mono text-xs">{c.withOwner}</TableCell>
                  <TableCell className="text-right font-mono text-xs">{c.withEmail}</TableCell>
                  <TableCell className="text-right font-mono text-xs">{formatCurrency(c.spendUsd)}</TableCell>
                  <TableCell className="text-muted-foreground">{formatDate(c.createdAt)}</TableCell>
                  <TableCell className="text-right">
                    <Button asChild variant="ghost" size="sm">
                      <Link href={`/campaigns/${c.id}/results`}>Open</Link>
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </section>
    </div>
  );
}
```

- [ ] **Step 4: Run the test — confirm it passes**

Run:
```bash
cd frontend && bun run test:e2e tests/e2e/campaigns.spec.ts
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/
git commit -m "Phase 1.6: campaigns list page"
```

---

## Task 7: New-campaign form

**Files:**
- Create: `frontend/app/campaigns/new/page.tsx`
- Create: `frontend/tests/e2e/new-campaign.spec.ts`

- [ ] **Step 1: Write the failing test `frontend/tests/e2e/new-campaign.spec.ts`**

```ts
import { test, expect } from "@playwright/test";

test("new-campaign form shows city, niche selector, count, and start button", async ({ page }) => {
  await page.goto("/campaigns/new");
  await expect(page.getByRole("heading", { name: /new campaign/i })).toBeVisible();
  await expect(page.getByLabel("City")).toBeVisible();
  await expect(page.getByLabel(/state/i)).toBeVisible();
  await expect(page.getByLabel(/lead count/i)).toBeVisible();
  await expect(page.getByRole("button", { name: /select niche/i })).toBeVisible();
  await expect(page.getByRole("button", { name: /start campaign/i })).toBeVisible();
});

test("niche combobox opens and lists presets + custom option", async ({ page }) => {
  await page.goto("/campaigns/new");
  await page.getByRole("button", { name: /select niche/i }).click();
  await expect(page.getByText("Kitchen remodelers")).toBeVisible();
  await expect(page.getByText("Bathroom remodelers")).toBeVisible();
  await expect(page.getByText("Roofing")).toBeVisible();
  await expect(page.getByText(/custom\.\.\./i)).toBeVisible();
});
```

- [ ] **Step 2: Run the test — confirm it fails**

Run:
```bash
cd frontend && bun run test:e2e tests/e2e/new-campaign.spec.ts
```
Expected: FAIL — `/campaigns/new` 404s.

- [ ] **Step 3: Create `frontend/app/campaigns/new/page.tsx`**

```tsx
"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Check, ChevronsUpDown, Pencil } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList, CommandSeparator } from "@/components/ui/command";
import { Badge } from "@/components/ui/badge";
import { NICHE_PRESETS } from "@/lib/mocks/niches";
import { cn } from "@/lib/utils";

const STATES = [
  "AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","HI","ID","IL","IN","IA","KS","KY","LA","ME","MD","MA","MI","MN","MS","MO","MT","NE","NV","NH","NJ","NM","NY","NC","ND","OH","OK","OR","PA","RI","SC","SD","TN","TX","UT","VT","VA","WA","WV","WI","WY",
];

const CUSTOM_SLUG = "__custom__";

export default function NewCampaignPage() {
  const router = useRouter();
  const [city, setCity] = useState("");
  const [stateAbbr, setStateAbbr] = useState("FL");
  const [count, setCount] = useState(50);
  const [radius, setRadius] = useState(15);
  const [open, setOpen] = useState(false);
  const [nicheSlug, setNicheSlug] = useState<string | null>(null);
  const [customNiche, setCustomNiche] = useState("");
  const [keywordVariants, setKeywordVariants] = useState<string[]>([]);

  const selected = nicheSlug && nicheSlug !== CUSTOM_SLUG
    ? NICHE_PRESETS.find((n) => n.slug === nicheSlug) ?? null
    : null;
  const isCustom = nicheSlug === CUSTOM_SLUG;

  function selectPreset(slug: string) {
    setNicheSlug(slug);
    const preset = NICHE_PRESETS.find((n) => n.slug === slug);
    if (preset) setKeywordVariants(preset.keywordVariants);
    setOpen(false);
  }

  function selectCustom() {
    setNicheSlug(CUSTOM_SLUG);
    setKeywordVariants([]);
    setOpen(false);
  }

  function nicheLabel() {
    if (selected) return selected.displayName;
    if (isCustom) return customNiche || "Custom niche";
    return "Select niche...";
  }

  function estimatedSpend() {
    return (count * 0.045).toFixed(2);
  }

  function handleStart(e: React.FormEvent) {
    e.preventDefault();
    router.push("/campaigns/20260502-153012-a1b2c3");
  }

  return (
    <div className="mx-auto max-w-3xl px-6 py-10">
      <div className="pb-8">
        <p className="text-sm text-muted-foreground">Step 1 of 1 · configure your run</p>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight">New campaign</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Pick a city, niche, and lead count. The pipeline sources, filters, and researches owners — you'll watch each step in real time.
        </p>
      </div>

      <form onSubmit={handleStart} className="space-y-6">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Where</CardTitle>
            <CardDescription>City and state for the search.</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4 sm:grid-cols-3">
            <div className="sm:col-span-2 space-y-2">
              <Label htmlFor="city">City</Label>
              <Input
                id="city"
                placeholder="Tampa"
                value={city}
                onChange={(e) => setCity(e.target.value)}
                autoFocus
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="state">State</Label>
              <select
                id="state"
                value={stateAbbr}
                onChange={(e) => setStateAbbr(e.target.value)}
                className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-xs transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              >
                {STATES.map((s) => (
                  <option key={s} value={s}>{s}</option>
                ))}
              </select>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">What</CardTitle>
            <CardDescription>
              Pick a vetted niche or define your own. Niche drives the search keyword variants.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label>Niche</Label>
              <Popover open={open} onOpenChange={setOpen}>
                <PopoverTrigger asChild>
                  <Button
                    type="button"
                    variant="outline"
                    role="combobox"
                    aria-expanded={open}
                    className="w-full justify-between"
                  >
                    <span className={cn(!selected && !isCustom && "text-muted-foreground")}>
                      {nicheLabel()}
                    </span>
                    <ChevronsUpDown className="ml-2 size-4 opacity-50" />
                  </Button>
                </PopoverTrigger>
                <PopoverContent className="w-[var(--radix-popover-trigger-width)] p-0" align="start">
                  <Command>
                    <CommandInput placeholder="Search niches..." />
                    <CommandList>
                      <CommandEmpty>No matching preset.</CommandEmpty>
                      <CommandGroup heading="Presets">
                        {NICHE_PRESETS.map((preset) => (
                          <CommandItem
                            key={preset.slug}
                            value={preset.displayName}
                            onSelect={() => selectPreset(preset.slug)}
                          >
                            <Check
                              className={cn(
                                "mr-2 size-4",
                                nicheSlug === preset.slug ? "opacity-100" : "opacity-0",
                              )}
                            />
                            <span className="flex-1">{preset.displayName}</span>
                            <span className="ml-2 text-xs text-muted-foreground">
                              {preset.keywordVariants.length + 1} kw
                            </span>
                          </CommandItem>
                        ))}
                      </CommandGroup>
                      <CommandSeparator />
                      <CommandGroup>
                        <CommandItem onSelect={selectCustom}>
                          <Pencil className="mr-2 size-4" />
                          Custom...
                        </CommandItem>
                      </CommandGroup>
                    </CommandList>
                  </Command>
                </PopoverContent>
              </Popover>
            </div>

            {isCustom && (
              <div className="space-y-2">
                <Label htmlFor="custom-niche">Custom niche name</Label>
                <Input
                  id="custom-niche"
                  placeholder="e.g. tile setters"
                  value={customNiche}
                  onChange={(e) => setCustomNiche(e.target.value)}
                />
              </div>
            )}

            {(selected || isCustom) && (
              <div className="space-y-2">
                <Label>Keyword variants</Label>
                <p className="text-xs text-muted-foreground">
                  These run against Azure Maps and Yelp Fusion. Edit freely.
                </p>
                <div className="flex flex-wrap gap-2">
                  {(selected ? [selected.defaultKeyword, ...keywordVariants] : keywordVariants).map((kw, i) => (
                    <Badge key={`${kw}-${i}`} variant="secondary" className="rounded-full">
                      {kw}
                    </Badge>
                  ))}
                  {(!selected && keywordVariants.length === 0) && (
                    <span className="text-xs text-muted-foreground">
                      Add a keyword above to seed the search.
                    </span>
                  )}
                </div>
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">How many</CardTitle>
            <CardDescription>Target lead count and search radius.</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="count">Lead count target</Label>
              <Input
                id="count"
                type="number"
                min={10}
                max={250}
                value={count}
                onChange={(e) => setCount(Number(e.target.value))}
              />
              <p className="text-xs text-muted-foreground">10–250. Most teams run 50.</p>
            </div>
            <div className="space-y-2">
              <Label htmlFor="radius">Search radius (miles)</Label>
              <Input
                id="radius"
                type="number"
                min={5}
                max={50}
                value={radius}
                onChange={(e) => setRadius(Number(e.target.value))}
              />
              <p className="text-xs text-muted-foreground">5–50 miles from city center.</p>
            </div>
          </CardContent>
        </Card>

        <Card className="border-dashed">
          <CardContent className="flex items-center justify-between p-4 text-sm">
            <div>
              <p className="font-medium">Estimated spend</p>
              <p className="text-xs text-muted-foreground">
                Based on Anthropic + source-API average of $0.045/lead.
              </p>
            </div>
            <span className="font-mono text-base">${estimatedSpend()}</span>
          </CardContent>
        </Card>

        <div className="flex items-center justify-end gap-3">
          <Button type="button" variant="ghost" onClick={() => router.push("/campaigns")}>
            Cancel
          </Button>
          <Button type="submit">Start campaign</Button>
        </div>
      </form>
    </div>
  );
}
```

- [ ] **Step 4: Run the test — confirm it passes**

Run:
```bash
cd frontend && bun run test:e2e tests/e2e/new-campaign.spec.ts
```
Expected: PASS (both tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/
git commit -m "Phase 1.7: new-campaign form with niche combobox"
```

---

## Task 8: Live run view

**Files:**
- Create: `frontend/app/campaigns/[id]/page.tsx`
- Create: `frontend/tests/e2e/live-run.spec.ts`

- [ ] **Step 1: Write the failing test `frontend/tests/e2e/live-run.spec.ts`**

```ts
import { test, expect } from "@playwright/test";

test("live run view shows step rail and event stream", async ({ page }) => {
  await page.goto("/campaigns/20260502-153012-a1b2c3");

  await expect(page.getByText("Tampa, FL")).toBeVisible();
  await expect(page.getByText("Bathroom remodelers")).toBeVisible();

  // step rail
  await expect(page.getByText("Source candidates")).toBeVisible();
  await expect(page.getByText("Filter with Claude")).toBeVisible();
  await expect(page.getByText("Identify owners")).toBeVisible();
  await expect(page.getByText("Assemble CSV")).toBeVisible();

  // event stream content
  await expect(page.getByText(/Sourcer started/)).toBeVisible();
  await expect(page.getByText(/Yelp Fusion returned 24 candidates/)).toBeVisible();
  await expect(page.getByText(/Phase 1 in progress/)).toBeVisible();
});
```

- [ ] **Step 2: Run the test — confirm it fails**

Run:
```bash
cd frontend && bun run test:e2e tests/e2e/live-run.spec.ts
```
Expected: FAIL — `/campaigns/[id]` 404s.

- [ ] **Step 3: Create `frontend/app/campaigns/[id]/page.tsx`**

```tsx
import Link from "next/link";
import { notFound } from "next/navigation";
import { CheckCircle2, CircleDashed, CircleSlash, Loader2, XCircle, ArrowUpRight, Square } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { ScrollArea } from "@/components/ui/scroll-area";
import { MOCK_CAMPAIGNS } from "@/lib/mocks/campaigns";
import { MOCK_EVENTS, MOCK_STEPS } from "@/lib/mocks/events";
import type { EventLevel, StepProgress, StepStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

const STEP_ICON: Record<StepStatus, React.ComponentType<{ className?: string }>> = {
  queued: CircleDashed,
  running: Loader2,
  done: CheckCircle2,
  failed: XCircle,
  skipped: CircleSlash,
};

const STEP_TONE: Record<StepStatus, string> = {
  queued: "text-muted-foreground",
  running: "text-info",
  done: "text-success",
  failed: "text-danger",
  skipped: "text-muted-foreground",
};

const EVENT_TONE: Record<EventLevel, string> = {
  info: "border-l-border",
  success: "border-l-success",
  warn: "border-l-warning",
  error: "border-l-danger",
};

function formatDuration(ms: number | undefined): string {
  if (!ms) return "";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString(undefined, {
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
  });
}

export default async function LiveRunPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const campaign = MOCK_CAMPAIGNS.find((c) => c.id === id);
  if (!campaign) notFound();

  const steps: StepProgress[] = MOCK_STEPS;
  const events = MOCK_EVENTS;

  return (
    <div className="mx-auto max-w-7xl px-6 py-10">
      <div className="flex flex-wrap items-end justify-between gap-4 pb-8">
        <div>
          <div className="flex items-center gap-2 pb-1">
            <Link href="/campaigns" className="text-sm text-muted-foreground hover:text-foreground">
              Campaigns
            </Link>
            <span className="text-muted-foreground">/</span>
            <span className="text-sm font-mono text-muted-foreground">{campaign.id.slice(0, 14)}</span>
          </div>
          <h1 className="text-2xl font-semibold tracking-tight">
            {campaign.city}, {campaign.stateAbbr}
            <span className="ml-2 text-base font-normal text-muted-foreground">
              · {campaign.niche}
            </span>
          </h1>
          <div className="mt-2 flex items-center gap-3 text-sm text-muted-foreground">
            <Badge variant="outline" className="border-info/30 bg-info/10 text-info capitalize">
              {campaign.status}
            </Badge>
            <span>target {campaign.targetCount}</span>
            <span>·</span>
            <span>started by {campaign.triggeredBy}</span>
            <span>·</span>
            <span>${campaign.spendUsd.toFixed(2)} spent</span>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm">
            <Square className="mr-2 size-3.5" /> Cancel run
          </Button>
          <Button asChild variant="outline" size="sm">
            <Link href={`/campaigns/${campaign.id}/results`}>
              Preview results <ArrowUpRight className="ml-1 size-3.5" />
            </Link>
          </Button>
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-[280px_1fr]">
        <aside className="space-y-1">
          <h2 className="px-1 pb-2 text-xs font-medium uppercase tracking-wider text-muted-foreground">
            Pipeline
          </h2>
          {steps.map((step, idx) => {
            const Icon = STEP_ICON[step.status];
            const isRunning = step.status === "running";
            return (
              <div
                key={step.step}
                className={cn(
                  "rounded-md border p-3 transition-colors",
                  isRunning ? "border-info/40 bg-info/5" : "border-transparent",
                )}
              >
                <div className="flex items-start gap-3">
                  <Icon
                    className={cn(
                      "mt-0.5 size-4 shrink-0",
                      STEP_TONE[step.status],
                      isRunning && "animate-spin",
                    )}
                  />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-sm font-medium">{step.label}</span>
                      <span className="text-xs text-muted-foreground">
                        {formatDuration(step.durationMs)}
                      </span>
                    </div>
                    {step.summary && (
                      <p className="mt-1 text-xs text-muted-foreground">{step.summary}</p>
                    )}
                    <p className="mt-1 text-xs uppercase tracking-wider text-muted-foreground">
                      step {idx + 1}/{steps.length} · {step.status}
                    </p>
                  </div>
                </div>
              </div>
            );
          })}
        </aside>

        <section>
          <Card className="overflow-hidden">
            <div className="flex items-center justify-between border-b border-border px-4 py-2.5">
              <div className="flex items-center gap-2 text-sm">
                <span className="size-2 animate-pulse rounded-full bg-info" />
                <span className="font-medium">Live event stream</span>
                <span className="text-xs text-muted-foreground">{events.length} events</span>
              </div>
              <span className="font-mono text-xs text-muted-foreground">SSE · auto-reconnect</span>
            </div>
            <ScrollArea className="h-[560px]">
              <CardContent className="space-y-2 p-4">
                {events.map((evt) => (
                  <div
                    key={evt.id}
                    className={cn(
                      "flex items-start gap-3 rounded-md border-l-2 bg-muted/30 px-3 py-2 text-sm",
                      EVENT_TONE[evt.level],
                    )}
                  >
                    <span className="font-mono text-xs text-muted-foreground tabular-nums">
                      {formatTime(evt.ts)}
                    </span>
                    <Badge variant="outline" className="shrink-0 font-mono text-xs uppercase">
                      {evt.step}
                    </Badge>
                    <div className="min-w-0 flex-1">
                      <p>{evt.message}</p>
                      {evt.detail && (
                        <p className="mt-0.5 text-xs text-muted-foreground">{evt.detail}</p>
                      )}
                    </div>
                    {evt.durationMs && (
                      <span className="font-mono text-xs text-muted-foreground tabular-nums">
                        {formatDuration(evt.durationMs)}
                      </span>
                    )}
                  </div>
                ))}
                <Separator className="my-3" />
                <p className="text-center text-xs text-muted-foreground">
                  Stream is live. New events stream in as agents progress.
                </p>
              </CardContent>
            </ScrollArea>
          </Card>
        </section>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run the test — confirm it passes**

Run:
```bash
cd frontend && bun run test:e2e tests/e2e/live-run.spec.ts
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/
git commit -m "Phase 1.8: live run view with step rail and event stream"
```

---

## Task 9: Results preview table

**Files:**
- Create: `frontend/app/campaigns/[id]/results/page.tsx`
- Create: `frontend/tests/e2e/results.spec.ts`

- [ ] **Step 1: Write the failing test `frontend/tests/e2e/results.spec.ts`**

```ts
import { test, expect } from "@playwright/test";

test("results page shows leads, exclude checkboxes, cost panel, and CSV export", async ({ page }) => {
  await page.goto("/campaigns/20260502-103940-d4e5f6/results");

  await expect(page.getByRole("heading", { name: /results/i })).toBeVisible();
  await expect(page.getByText("Lloyd & Sons Bath Remodel")).toBeVisible();
  await expect(page.getByText("Sunrise Tile & Bath")).toBeVisible();

  // cost panel
  await expect(page.getByText(/total spend/i)).toBeVisible();

  // exclude checkboxes
  const checkboxes = page.getByRole("checkbox");
  await expect(checkboxes.first()).toBeVisible();

  // download button
  await expect(page.getByRole("button", { name: /download findymail csv/i })).toBeVisible();
});
```

- [ ] **Step 2: Run the test — confirm it fails**

Run:
```bash
cd frontend && bun run test:e2e tests/e2e/results.spec.ts
```
Expected: FAIL — results page 404s.

- [ ] **Step 3: Create `frontend/app/campaigns/[id]/results/page.tsx`**

```tsx
"use client";

import { use, useMemo, useState } from "react";
import Link from "next/link";
import { Download, ExternalLink, Mail, Phone, Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { MOCK_CAMPAIGNS } from "@/lib/mocks/campaigns";
import { MOCK_LEADS } from "@/lib/mocks/leads";
import { cn } from "@/lib/utils";

export default function ResultsPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const campaign = MOCK_CAMPAIGNS.find((c) => c.id === id) ?? MOCK_CAMPAIGNS[0];

  const [excluded, setExcluded] = useState<Set<string>>(
    () => new Set(MOCK_LEADS.filter((l) => l.excludedByUser).map((l) => l.id)),
  );
  const [search, setSearch] = useState("");

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return MOCK_LEADS.filter((l) => {
      if (!q) return true;
      return (
        l.businessName.toLowerCase().includes(q) ||
        l.address.toLowerCase().includes(q) ||
        l.ownerFirst.toLowerCase().includes(q) ||
        l.ownerLast.toLowerCase().includes(q)
      );
    });
  }, [search]);

  const kept = MOCK_LEADS.filter((l) => l.kept);
  const ready = kept.filter((l) => !excluded.has(l.id));
  const withEmail = ready.filter((l) => l.email).length;

  function toggle(id: string) {
    setExcluded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  return (
    <div className="mx-auto max-w-7xl px-6 py-10">
      <div className="flex flex-wrap items-end justify-between gap-4 pb-8">
        <div>
          <div className="flex items-center gap-2 pb-1">
            <Link href="/campaigns" className="text-sm text-muted-foreground hover:text-foreground">
              Campaigns
            </Link>
            <span className="text-muted-foreground">/</span>
            <Link
              href={`/campaigns/${campaign.id}`}
              className="text-sm font-mono text-muted-foreground hover:text-foreground"
            >
              {campaign.id.slice(0, 14)}
            </Link>
            <span className="text-muted-foreground">/</span>
            <span className="text-sm">results</span>
          </div>
          <h1 className="text-2xl font-semibold tracking-tight">Results · {campaign.city}, {campaign.stateAbbr}</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Review and trim before exporting to FindyMail. Unchecked rows won't be included.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline">
            <Download className="mr-2 size-4" /> Download master CSV
          </Button>
          <Button>
            <Download className="mr-2 size-4" /> Download FindyMail CSV
          </Button>
        </div>
      </div>

      <div className="grid gap-4 pb-8 sm:grid-cols-4">
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Ready for FindyMail</CardDescription>
            <CardTitle className="text-2xl">{ready.length}</CardTitle>
          </CardHeader>
          <CardContent className="text-xs text-muted-foreground">
            {withEmail} already have an email captured · saves that many FindyMail credits
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Kept by filter</CardDescription>
            <CardTitle className="text-2xl">{kept.length}</CardTitle>
          </CardHeader>
          <CardContent className="text-xs text-muted-foreground">
            of {MOCK_LEADS.length} sourced
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Excluded by you</CardDescription>
            <CardTitle className="text-2xl">{excluded.size}</CardTitle>
          </CardHeader>
          <CardContent className="text-xs text-muted-foreground">
            uncheck to add back
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Total spend</CardDescription>
            <CardTitle className="text-2xl">${campaign.spendUsd.toFixed(2)}</CardTitle>
          </CardHeader>
          <CardContent className="text-xs text-muted-foreground">
            Anthropic + source APIs · ${(campaign.spendUsd / Math.max(kept.length, 1)).toFixed(3)}/lead
          </CardContent>
        </Card>
      </div>

      <div className="flex items-center justify-between pb-3">
        <div className="relative w-full max-w-sm">
          <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="Search business, owner, or address..."
            className="pl-9"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <div className="text-xs text-muted-foreground">
          showing {filtered.length} of {MOCK_LEADS.length}
        </div>
      </div>

      <div className="overflow-hidden rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-10"></TableHead>
              <TableHead>Business</TableHead>
              <TableHead>Owner</TableHead>
              <TableHead>Phone</TableHead>
              <TableHead>Website</TableHead>
              <TableHead>Email</TableHead>
              <TableHead>Status</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {filtered.map((lead) => {
              const isExcluded = excluded.has(lead.id);
              const isFiltered = !lead.kept;
              return (
                <TableRow
                  key={lead.id}
                  className={cn(
                    (isExcluded || isFiltered) && "opacity-50",
                  )}
                >
                  <TableCell>
                    <Checkbox
                      checked={lead.kept && !isExcluded}
                      disabled={!lead.kept}
                      onCheckedChange={() => toggle(lead.id)}
                      aria-label={`Include ${lead.businessName}`}
                    />
                  </TableCell>
                  <TableCell>
                    <div className="font-medium">{lead.businessName}</div>
                    <div className="text-xs text-muted-foreground">{lead.address}</div>
                    {isFiltered && (
                      <div className="mt-1 text-xs text-danger">
                        Filtered: {lead.rejectReason}
                      </div>
                    )}
                  </TableCell>
                  <TableCell>
                    {lead.ownerFirst || lead.ownerLast ? (
                      <div>
                        <div>{lead.ownerFirst} {lead.ownerLast}</div>
                        {lead.ownerSource && (
                          <div className="text-xs text-muted-foreground">via {lead.ownerSource}</div>
                        )}
                      </div>
                    ) : (
                      <span className="text-xs text-muted-foreground">—</span>
                    )}
                  </TableCell>
                  <TableCell className="font-mono text-xs">
                    <a href={`tel:${lead.phone}`} className="inline-flex items-center gap-1 hover:text-foreground">
                      <Phone className="size-3" />
                      {lead.phone}
                    </a>
                  </TableCell>
                  <TableCell className="text-xs">
                    {lead.website ? (
                      <a
                        href={lead.website}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-1 text-muted-foreground hover:text-foreground"
                      >
                        <ExternalLink className="size-3" />
                        {lead.domain}
                      </a>
                    ) : (
                      <span className="text-muted-foreground">—</span>
                    )}
                  </TableCell>
                  <TableCell className="text-xs">
                    {lead.email ? (
                      <span className="inline-flex items-center gap-1 text-success">
                        <Mail className="size-3" />
                        captured
                      </span>
                    ) : (
                      <span className="text-muted-foreground">needs FindyMail</span>
                    )}
                  </TableCell>
                  <TableCell>
                    {isFiltered ? (
                      <Badge variant="outline" className="border-danger/30 bg-danger/10 text-danger">
                        filtered
                      </Badge>
                    ) : isExcluded ? (
                      <Badge variant="outline" className="border-warning/30 bg-warning/10 text-warning">
                        excluded
                      </Badge>
                    ) : (
                      <Badge variant="outline" className="border-success/30 bg-success/10 text-success">
                        ready
                      </Badge>
                    )}
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run the test — confirm it passes**

Run:
```bash
cd frontend && bun run test:e2e tests/e2e/results.spec.ts
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/
git commit -m "Phase 1.9: results preview table with row-exclude and cost panel"
```

---

## Task 10: Final verification, screenshots, push

**Files:**
- Create: `docs/brand/mockups/*.png` (Playwright screenshots)
- Modify: `docs/frontend-plan.md` (mark Phase 1 status complete in §8)

- [ ] **Step 1: Run the full e2e suite**

Run:
```bash
cd frontend && bun run test:e2e
```
Expected: ALL specs PASS. If any fail, debug before continuing — do not skip.

- [ ] **Step 2: TypeScript pass**

Run:
```bash
cd frontend && bunx tsc --noEmit -p tsconfig.json
```
Expected: zero errors.

- [ ] **Step 3: Add a screenshot spec at `frontend/tests/e2e/screenshots.spec.ts`**

```ts
import { test } from "@playwright/test";
import path from "node:path";

const OUT = path.resolve(__dirname, "../../../docs/brand/mockups");

const ROUTES: Array<[string, string]> = [
  ["/campaigns", "01-campaigns-list.png"],
  ["/campaigns/new", "02-new-campaign.png"],
  ["/campaigns/20260502-153012-a1b2c3", "03-live-run.png"],
  ["/campaigns/20260502-103940-d4e5f6/results", "04-results.png"],
];

for (const [route, file] of ROUTES) {
  test(`screenshot ${route}`, async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(route);
    await page.waitForLoadState("networkidle");
    await page.screenshot({ path: path.join(OUT, file), fullPage: true });
  });
}
```

- [ ] **Step 4: Generate screenshots**

Run (from repo root):
```bash
mkdir -p docs/brand/mockups && cd frontend && bun run test:e2e tests/e2e/screenshots.spec.ts
```
Expected: 4 PASS, files written under `docs/brand/mockups/`. Verify via `ls docs/brand/mockups/` — should show all 4 PNGs.

- [ ] **Step 5: Update `docs/frontend-plan.md` §8 sequencing table**

Edit the sequencing table row for Phase 1: change Status from `Not started` to `Complete (mocks landed; auth + API are Phase 2)`.

Also append to §9 Decisions log:

```markdown
| 2026-05-02 | Phase 1 mocks landed: campaigns list, new-campaign form, live run view, results table | Built static, no-auth, no-data Next.js + shadcn pages on `phase1-frontend-skeleton`; Playwright smoke tests cover each route; screenshots in `docs/brand/mockups/` |
```

- [ ] **Step 6: Final commit + push**

```bash
git add frontend/tests/e2e/screenshots.spec.ts docs/brand/mockups docs/frontend-plan.md
git commit -m "Phase 1.10: e2e screenshots + plan status update"
git push -u origin phase1-frontend-skeleton
```

Expected: branch live on origin. Operator can review via screenshots and `bun dev` locally.

---

## Self-review

**Spec coverage check:**

- ✅ Phase 1 row of `docs/frontend-plan.md` §8: "Next.js + shadcn scaffold on Vercel + auth + niche catalog UI + new-campaign form (mocked API)" — covered. Auth (Clerk) is Phase 2 per the plan; this task delivers everything else.
- ✅ §5 UX patterns — run view layout (left rail + event stream), event tone (terse system messages), niche selector (preset + custom), result review (Clay-style row exclude), cost visibility, monochrome + accent aesthetic — all reflected.
- ✅ §2 brand — Geist font, electric blue accent (`#2563EB`), confident voice in copy, wordmark in header.
- ✅ §6 niche catalog — all 12 presets present.

**Placeholder scan:** No "TBD", "TODO", "implement later", "add appropriate error handling", or vague step descriptions. Every step has the actual code or command needed.

**Type consistency:** `Lead`, `Campaign`, `RunEvent`, `StepProgress`, `NichePreset`, `CampaignStatus`, `StepName`, `StepStatus`, `EventLevel` are defined once in `lib/types.ts` and referenced consistently. The `id` field is used identically across mocks and pages. No name drift.

**Cross-task references:** Each task lists exact file paths and code. Components used in multiple pages (`AppHeader`) are extracted to `components/`. Page-specific UI fragments (StepRail, EventCard, NicheCombobox, LeadRow, CostPanel) live inline in their page file as agreed in the file-structure section — keeps tasks self-contained without an over-engineered component tree.

---

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-02-phase1-frontend-mocks.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task; review between tasks; fast iteration. Best when tasks are mostly independent (this plan's Tasks 6–9 are; Tasks 1–5 are foundation that must serialize).

**2. Inline Execution** — Execute tasks in this session using executing-plans; batch execution with checkpoints for review. Slower but gives the operator more visibility into each step.

Which approach?
