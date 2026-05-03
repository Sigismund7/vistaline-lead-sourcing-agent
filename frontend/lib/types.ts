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
