"use client";

import { use, useEffect, useState } from "react";
import Link from "next/link";
import { CheckCircle2, CircleDashed, CircleSlash, Loader2, XCircle, ArrowUpRight } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { ScrollArea } from "@/components/ui/scroll-area";
import { getCampaign, getEvents } from "@/lib/api";
import { supabase } from "@/lib/supabase";
import type { Campaign, EventLevel, RunEvent, StepName, StepProgress, StepStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

const STEP_ORDER: StepName[] = ["sourcer", "lead_filter", "owner_researcher", "csv_assembler"];
const STEP_LABELS: Record<StepName, string> = {
  sourcer: "Sourcer",
  lead_filter: "Lead Filter",
  owner_researcher: "Owner Research",
  csv_assembler: "CSV Assembler",
};

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

function deriveSteps(completedSteps: string[], status: Campaign["status"]): StepProgress[] {
  const firstNotDone = STEP_ORDER.findIndex((s) => !completedSteps.includes(s));
  return STEP_ORDER.map((step, i) => {
    const isDone = completedSteps.includes(step);
    const isRunning = status === "running" && i === firstNotDone;
    const hasFailed = status === "failed" && i === firstNotDone;
    return {
      step,
      label: STEP_LABELS[step],
      status: isDone ? "done" : isRunning ? "running" : hasFailed ? "failed" : "queued",
    };
  });
}

function formatDuration(ms: number | undefined): string {
  if (!ms) return "";
  return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`;
}

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString(undefined, {
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
  });
}

export default function LiveRunPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);

  const [campaign, setCampaign] = useState<Campaign | null>(null);
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    Promise.all([getCampaign(id), getEvents(id)])
      .then(([c, evts]) => {
        if (cancelled) return;
        setCampaign(c);
        setEvents(evts.filter((e) => !e.message.startsWith("Querying ")));
      })
      .catch(() => {})
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [id]);

  // Realtime: new events
  useEffect(() => {
    const channel = supabase
      .channel(`events-${id}`)
      .on(
        "postgres_changes",
        { event: "INSERT", schema: "public", table: "events", filter: `campaign_id=eq.${id}` },
        (payload) => {
          const r = payload.new as Record<string, unknown>;
          const evt: RunEvent = {
            id: r.id as string,
            step: r.step as StepName,
            level: (r.level as EventLevel) ?? "info",
            message: r.message as string,
            detail: r.detail as string | undefined,
            durationMs: r.duration_ms as number | undefined,
            ts: r.ts as string,
          };
          if (!evt.message.startsWith("Querying ")) {
            setEvents((prev) => [...prev, evt]);
          }
        },
      )
      .subscribe();
    return () => { supabase.removeChannel(channel); };
  }, [id]);

  // Realtime: campaign row updates (status, completed_steps, counts)
  useEffect(() => {
    const channel = supabase
      .channel(`campaign-${id}`)
      .on(
        "postgres_changes",
        { event: "UPDATE", schema: "public", table: "campaigns", filter: `id=eq.${id}` },
        (payload) => {
          const r = payload.new as Record<string, unknown>;
          setCampaign((prev) =>
            prev
              ? {
                  ...prev,
                  status: r.status as Campaign["status"],
                  keptLeads: (r.kept_leads as number) ?? prev.keptLeads,
                  totalLeads: (r.total_leads as number) ?? prev.totalLeads,
                  withOwner: (r.with_owner as number) ?? prev.withOwner,
                  withEmail: (r.with_email as number) ?? prev.withEmail,
                  completedAt: r.completed_at as string | undefined,
                  completedSteps: (r.completed_steps as string[]) ?? prev.completedSteps,
                }
              : prev,
          );
        },
      )
      .subscribe();
    return () => { supabase.removeChannel(channel); };
  }, [id]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-32 text-muted-foreground">
        <Loader2 className="mr-2 size-5 animate-spin" /> Loading campaign…
      </div>
    );
  }

  if (!campaign) {
    return (
      <div className="mx-auto max-w-7xl px-6 py-10 text-muted-foreground">
        Campaign not found.
      </div>
    );
  }

  const steps = deriveSteps(campaign.completedSteps ?? [], campaign.status);
  const isLive = campaign.status === "running";

  return (
    <div className="mx-auto max-w-7xl px-6 py-10">
      <div className="flex flex-wrap items-end justify-between gap-4 pb-8">
        <div>
          <div className="flex items-center gap-2 pb-1">
            <Link href="/campaigns" className="text-sm text-muted-foreground hover:text-foreground">
              Campaigns
            </Link>
            <span className="text-muted-foreground">/</span>
            <span className="text-sm font-mono text-muted-foreground">{id.slice(0, 14)}</span>
          </div>
          <h1 className="text-2xl font-semibold tracking-tight">
            {campaign.city}, {campaign.stateAbbr}
            <span className="ml-2 text-base font-normal text-muted-foreground">
              · {campaign.niche}
            </span>
          </h1>
          <div className="mt-2 flex items-center gap-3 text-sm text-muted-foreground">
            <Badge
              variant="outline"
              className={cn(
                "capitalize",
                campaign.status === "running" && "border-info/30 bg-info/10 text-info",
                campaign.status === "completed" && "border-success/30 bg-success/10 text-success",
                campaign.status === "failed" && "border-danger/30 bg-danger/10 text-danger",
              )}
            >
              {campaign.status}
            </Badge>
            <span>target {campaign.targetCount}</span>
            <span>·</span>
            <span>started by {campaign.triggeredBy}</span>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {campaign.status === "completed" && (
            <Button asChild variant="outline" size="sm">
              <Link href={`/campaigns/${id}/results`}>
                View results <ArrowUpRight className="ml-1 size-3.5" />
              </Link>
            </Button>
          )}
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
                    </div>
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
                {isLive && <span className="size-2 animate-pulse rounded-full bg-info" />}
                <span className="font-medium">Event stream</span>
                <span className="text-xs text-muted-foreground">{events.length} events</span>
              </div>
              <span className="font-mono text-xs text-muted-foreground">
                {isLive ? "Supabase Realtime · live" : campaign.status}
              </span>
            </div>
            <ScrollArea className="h-[560px]">
              <CardContent className="space-y-2 p-4">
                {events.length === 0 && (
                  <p className="py-8 text-center text-sm text-muted-foreground">
                    Waiting for first event…
                  </p>
                )}
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
                {isLive && (
                  <>
                    <Separator className="my-3" />
                    <p className="text-center text-xs text-muted-foreground">
                      Streaming live via Supabase Realtime.
                    </p>
                  </>
                )}
              </CardContent>
            </ScrollArea>
          </Card>
        </section>
      </div>
    </div>
  );
}
