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
          <h1 className="text-2xl font-semibold tracking-tight">
            Results · {campaign.city}, {campaign.stateAbbr}
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Review and trim before exporting to FindyMail. Unchecked rows won&apos;t be included.
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
