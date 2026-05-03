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
  // Filter out verbose per-query events that repeat city/state — they add noise
  // and cause strict-mode ambiguity with the campaign heading text.
  const events = MOCK_EVENTS.filter(
    (e) => !e.message.startsWith("Querying "),
  );

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
