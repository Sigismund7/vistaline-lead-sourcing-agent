import Link from "next/link";
import { ArrowUpRight, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { CampaignStatus, Campaign } from "@/lib/types";
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

async function fetchCampaigns(): Promise<Campaign[]> {
  const base = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
  const secret = process.env.VISTALINE_API_SECRET ?? "";
  try {
    const res = await fetch(`${base}/campaigns`, {
      headers: { "X-Api-Key": secret },
      next: { revalidate: 10 },
    });
    if (!res.ok) return [];
    const rows: Record<string, unknown>[] = await res.json();
    return rows.map((r) => ({
      id: r.id as string,
      city: r.city as string,
      stateAbbr: r.state_abbr as string,
      niche: r.niche as string,
      targetCount: r.target_count as number,
      status: r.status as CampaignStatus,
      createdAt: r.created_at as string,
      completedAt: r.completed_at as string | undefined,
      totalLeads: (r.total_leads as number) ?? 0,
      keptLeads: (r.kept_leads as number) ?? 0,
      withOwner: (r.with_owner as number) ?? 0,
      withEmail: (r.with_email as number) ?? 0,
      spendUsd: Number(r.spend_usd ?? 0),
      triggeredBy: (r.triggered_by as string) ?? "DG",
      completedSteps: (r.completed_steps as string[]) ?? [],
    }));
  } catch {
    return [];
  }
}

export default async function CampaignsPage() {
  const campaigns = await fetchCampaigns();
  const running = campaigns.filter((c) => c.status === "running");
  const recent = campaigns.filter((c) => c.status !== "running");

  const totalLeads = campaigns.reduce((sum, c) => sum + c.keptLeads, 0);
  const totalSpend = campaigns.reduce((sum, c) => sum + c.spendUsd, 0);

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
        {recent.length === 0 ? (
          <p className="py-8 text-center text-sm text-muted-foreground">
            No completed campaigns yet. <Link href="/campaigns/new" className="underline">Start one.</Link>
          </p>
        ) : (
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
                  <TableHead><span className="sr-only">Actions</span></TableHead>
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
        )}
      </section>
    </div>
  );
}
