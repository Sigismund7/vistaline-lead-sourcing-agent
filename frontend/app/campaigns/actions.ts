"use server";

import { redirect } from "next/navigation";
import { currentUser } from "@clerk/nextjs/server";

export async function startCampaign(formData: {
  city: string;
  stateAbbr: string;
  niche: string;
  targetCount: number;
}) {
  const user = await currentUser();
  const triggeredBy =
    user?.firstName ??
    user?.emailAddresses?.[0]?.emailAddress?.split("@")[0] ??
    "User";

  const base = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
  const res = await fetch(`${base}/campaigns`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Api-Key": process.env.VISTALINE_API_SECRET ?? "",
    },
    body: JSON.stringify({
      city: formData.city,
      state_abbr: formData.stateAbbr,
      niche: formData.niche,
      target_count: formData.targetCount,
      triggered_by: triggeredBy,
    }),
  });

  if (!res.ok) {
    const body = await res.text().catch(() => res.statusText);
    throw new Error(`Failed to create campaign: ${res.status} ${body}`);
  }

  const { id } = await res.json();
  redirect(`/campaigns/${id}`);
}
