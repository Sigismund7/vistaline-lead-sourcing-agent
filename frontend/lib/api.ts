import type { Campaign, RunEvent, Lead, CampaignStatus, StepName, EventLevel } from "@/lib/types";

const IS_BROWSER = typeof window !== "undefined";
const SERVER_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const SERVER_SECRET = process.env.VISTALINE_API_SECRET ?? "";

async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  // On the server, hit FastAPI directly with the secret.
  // In the browser, hit our Next.js proxy route — the proxy injects the secret server-side.
  const url = IS_BROWSER ? `/api/proxy${path}` : `${SERVER_BASE}${path}`;
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init.headers as Record<string, string> | undefined),
  };
  if (!IS_BROWSER) headers["X-Api-Key"] = SERVER_SECRET;

  const res = await fetch(url, { ...init, headers });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`API ${res.status}: ${text}`);
  }
  return res.json() as Promise<T>;
}

// ---- Campaigns ----

export function getCampaigns(): Promise<Campaign[]> {
  return apiFetch<Record<string, unknown>[]>("/campaigns").then((rows) => rows.map(toCampaign));
}

export function getCampaign(id: string): Promise<Campaign> {
  return apiFetch<Record<string, unknown>>(`/campaigns/${id}`).then(toCampaign);
}

export function createCampaign(params: {
  city: string;
  state_abbr: string;
  niche: string;
  target_count: number;
  triggered_by: string;
}): Promise<{ id: string }> {
  return apiFetch<{ id: string }>("/campaigns", {
    method: "POST",
    body: JSON.stringify(params),
  });
}

// ---- Events ----

export function getEvents(campaignId: string): Promise<RunEvent[]> {
  return apiFetch<Record<string, unknown>[]>(`/campaigns/${campaignId}/events`).then((rows) =>
    rows.map(toEvent),
  );
}

// ---- Leads ----

export function getLeads(campaignId: string): Promise<Lead[]> {
  return apiFetch<Record<string, unknown>[]>(`/campaigns/${campaignId}/leads`).then((rows) =>
    rows.map(toLead),
  );
}

export function patchLead(
  campaignId: string,
  leadId: string,
  excluded: boolean,
): Promise<void> {
  return apiFetch(`/campaigns/${campaignId}/leads/${leadId}`, {
    method: "PATCH",
    body: JSON.stringify({ excluded_by_user: excluded }),
  });
}

export function csvUrl(campaignId: string, type: "findymail" | "master"): string {
  const path =
    type === "findymail"
      ? `/campaigns/${campaignId}/leads.csv`
      : `/campaigns/${campaignId}/leads/master.csv`;
  // Browser hits the proxy (which injects the secret server-side).
  return `/api/proxy${path}`;
}

export function agencyCsvUrl(campaignId: string): string {
  return `/api/proxy/campaigns/${campaignId}/leads/agency.csv`;
}

export async function uploadEnrichedCsv(
  campaignId: string,
  file: File,
): Promise<{ ok: boolean; matched: number; unmatched: number }> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`/api/proxy/campaigns/${campaignId}/enrich`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`API ${res.status}: ${text}`);
  }
  return res.json();
}

// ---- Transformers (snake_case DB → camelCase UI) ----

function toCampaign(r: Record<string, unknown>): Campaign {
  return {
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
  };
}

function toEvent(r: Record<string, unknown>): RunEvent {
  return {
    id: r.id as string,
    step: r.step as StepName,
    level: (r.level as EventLevel) ?? "info",
    message: r.message as string,
    detail: r.detail as string | undefined,
    durationMs: r.duration_ms as number | undefined,
    ts: r.ts as string,
  };
}

function toLead(r: Record<string, unknown>): Lead {
  return {
    id: r.id as string,
    businessName: r.business_name as string,
    phone: r.phone as string,
    website: r.website as string,
    domain: r.domain as string,
    address: r.address as string,
    areaCode: r.area_code as string,
    ownerFirst: r.owner_first as string,
    ownerLast: r.owner_last as string,
    ownerSource: (r.owner_source as Lead["ownerSource"]) ?? "",
    email: r.email as string,
    kept: r.kept as boolean,
    excludedByUser: (r.excluded_by_user as boolean) ?? false,
    rejectReason: r.reject_reason as string,
    xProject: (r.x_project as string) ?? "",
    yDetail: (r.y_detail as string) ?? "",
    personalizationStatus: (r.personalization_status as string) ?? "",
  };
}
