"use server";

import { redirect } from "next/navigation";
import { cookies } from "next/headers";

export async function startCampaign(formData: {
  city: string;
  stateAbbr: string;
  niche: string;
  targetCount: number;
  useRegistry: boolean;
  useWebsearch: boolean;
}) {
  const jar = await cookies();
  const triggeredBy = jar.get("username")?.value ?? process.env.AUTH_USERNAME ?? "User";

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
      use_registry: formData.useRegistry,
      use_websearch: formData.useWebsearch,
    }),
  });

  if (!res.ok) {
    const detail = res.status >= 500
      ? "The backend is unavailable. Try again in a moment."
      : await res.text().catch(() => res.statusText);
    throw new Error(detail);
  }

  const { id } = await res.json();
  redirect(`/campaigns/${id}`);
}
