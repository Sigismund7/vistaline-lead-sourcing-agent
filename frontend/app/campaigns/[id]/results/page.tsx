"use client";

import { use, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Download, ExternalLink, Mail, Phone, Search, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { getCampaign, getLeads, patchLead } from "@/lib/api";
import type { Campaign, Lead } from "@/lib/types";
import { cn } from "@/lib/utils";

export default function ResultsPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);

  const [campaign, setCampaign] = useState<Campaign | null>(null);
  const [leads, setLeads] = useState<Lead[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");

  useEffect(() => {
    let cancelled = false;
    Promise.all([getCampaign(id), getLeads(id)])
      .then(([c, l]) => {
        if (cancelled) return;
        setCampaign(c);
        setLeads(l);
      })
      .catch(() => {})
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [id]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return leads;
    return leads.filter(
      (l) =>
        l.businessName.toLowerCase().includes(q) ||
        l.address.toLowerCase().includes(q) ||
        l.ownerFirst.toLowerCase().includes(q) ||
        l.ownerLast.toLowerCase().includes(q),
    );
  }, [leads, search]);

  async function downloadCsv(type: "findymail" | "master") {
    const url = type === "findymail"
      ? `/api/proxy/campaigns/${id}/leads.csv`
      : `/api/proxy/campaigns/${id}/leads/master.csv`;
    const filename = type === "findymail" ? `findymail-${id}.csv` : `master-${id}.csv`;
    const res = await fetch(url);
    if (!res.ok) return;
    const blob = await res.blob();
    const href = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = href;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(href);
  }

  function toggle(lead: Lead) {
    const next = !lead.excludedByUser;
    setLeads((prev) =>
      prev.map((l) => (l.id === lead.id ? { ...l, excludedByUser: next } : l)),
    );
    patchLead(id, lead.id, next).catch(() => {
      setLeads((prev) =>
        prev.map((l) => (l.id === lead.id ? { ...l, excludedByUser: lead.excludedByUser } : l)),
      );
    });
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-32 text-muted-foreground">
        <Loader2 className="mr-2 size-5 animate-spin" /> Loading results…
      </div>
    );
  }

  const kept = leads.filter((l) => l.kept);
  const ready = kept.filter((l) => !l.excludedByUser);
  const withEmail = ready.filter((l) => l.email).length;

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
              href={`/campaigns/${id}`}
              className="text-sm font-mono text-muted-foreground hover:text-foreground"
            >
              {id.slice(0, 14)}
            </Link>
            <span className="text-muted-foreground">/</span>
            <span className="text-sm">results</span>
          </div>
          <h1 className="text-2xl font-semibold tracking-tight">
            Results{campaign ? ` · ${campaign.city}, ${campaign.stateAbbr}` : ""}
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Review and trim before exporting to FindyMail. Unchecked rows won&apos;t be included.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" onClick={() => downloadCsv("master")}>
            <Download className="mr-2 size-4" /> Master CSV
          </Button>
          <Button onClick={() => downloadCsv("findymail")}>
            <Download className="mr-2 size-4" /> FindyMail CSV
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
            {withEmail} already have an email · saves that many FindyMail credits
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Kept by filter</CardDescription>
            <CardTitle className="text-2xl">{kept.length}</CardTitle>
          </CardHeader>
          <CardContent className="text-xs text-muted-foreground">of {leads.length} sourced</CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Excluded by you</CardDescription>
            <CardTitle className="text-2xl">{leads.filter((l) => l.excludedByUser).length}</CardTitle>
          </CardHeader>
          <CardContent className="text-xs text-muted-foreground">uncheck to add back</CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Total spend</CardDescription>
            <CardTitle className="text-2xl">${campaign?.spendUsd.toFixed(2) ?? "—"}</CardTitle>
          </CardHeader>
          <CardContent className="text-xs text-muted-foreground">
            Anthropic + source APIs
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
          showing {filtered.length} of {leads.length}
        </div>
      </div>

      <div className="overflow-hidden rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-10"><span className="sr-only">Include</span></TableHead>
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
              const isExcluded = lead.excludedByUser;
              const isFiltered = !lead.kept;
              return (
                <TableRow
                  key={lead.id}
                  className={cn((isExcluded || isFiltered) && "opacity-50")}
                >
                  <TableCell>
                    <Checkbox
                      checked={lead.kept && !isExcluded}
                      disabled={!lead.kept}
                      onCheckedChange={() => toggle(lead)}
                      aria-label={`Include ${lead.businessName}`}
                    />
                  </TableCell>
                  <TableCell>
                    <div className="font-medium">{lead.businessName}</div>
                    <div className="text-xs text-muted-foreground">{lead.address}</div>
                    {isFiltered && (
                      <div className="mt-1 text-xs text-danger">Filtered: {lead.rejectReason}</div>
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
                    {lead.phone ? (
                      <a href={`tel:${lead.phone}`} className="inline-flex items-center gap-1 hover:text-foreground">
                        <Phone className="size-3" />
                        {lead.phone}
                      </a>
                    ) : (
                      <span className="text-muted-foreground">—</span>
                    )}
                  </TableCell>
                  <TableCell className="text-xs">
                    {lead.website ? (
                      <a href={lead.website} target="_blank" rel="noopener noreferrer"
                        className="inline-flex items-center gap-1 text-muted-foreground hover:text-foreground">
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
                        <Mail className="size-3" /> captured
                      </span>
                    ) : (
                      <span className="text-muted-foreground">needs FindyMail</span>
                    )}
                  </TableCell>
                  <TableCell>
                    {isFiltered ? (
                      <Badge variant="outline" className="border-danger/30 bg-danger/10 text-danger">filtered</Badge>
                    ) : isExcluded ? (
                      <Badge variant="outline" className="border-warning/30 bg-warning/10 text-warning">excluded</Badge>
                    ) : (
                      <Badge variant="outline" className="border-success/30 bg-success/10 text-success">ready</Badge>
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
