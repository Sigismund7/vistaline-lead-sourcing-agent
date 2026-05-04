"use client";

import { useState } from "react";
import Link from "next/link";
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
import { startCampaign } from "@/app/campaigns/actions";

const STATES = [
  "AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","HI","ID","IL","IN","IA","KS","KY","LA","ME","MD","MA","MI","MN","MS","MO","MT","NE","NV","NH","NJ","NM","NY","NC","ND","OH","OK","OR","PA","RI","SC","SD","TN","TX","UT","VT","VA","WA","WV","WI","WY",
];

const CUSTOM_SLUG = "__custom__";

export default function NewCampaignPage() {
  const [city, setCity] = useState("");
  const [stateAbbr, setStateAbbr] = useState("FL");
  const [count, setCount] = useState(50);
  const [radius, setRadius] = useState(15);
  const [open, setOpen] = useState(false);
  const [nicheSlug, setNicheSlug] = useState<string | null>(null);
  const [customNiche, setCustomNiche] = useState("");
  const [keywordVariants, setKeywordVariants] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [useRegistry, setUseRegistry] = useState(true);
  const [useWebsearch, setUseWebsearch] = useState(true);

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

  async function handleStart(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const niche = selected?.displayName ?? (isCustom ? customNiche : "");
    if (!city.trim()) { setError("City is required."); return; }
    if (!niche) { setError("Please select a niche."); return; }
    setSubmitting(true);
    try {
      await startCampaign({ city: city.trim(), stateAbbr, niche, targetCount: count, useRegistry, useWebsearch });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start campaign. Try again.");
      setSubmitting(false);
    }
  }

  return (
    <div className="mx-auto max-w-3xl px-6 py-10">
      <div className="pb-8">
        <p className="text-sm text-muted-foreground">Step 1 of 1 · configure your run</p>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight">New campaign</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Pick a city, niche, and lead count. The pipeline sources, filters, and researches owners — you&apos;ll watch each step in real time.
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
                    aria-expanded={open}
                    aria-haspopup="listbox"
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

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Research phases</CardTitle>
            <CardDescription>
              Toggle off to skip a phase. Phase 1 (website crawl) always runs.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {[
              {
                id: "use-registry",
                label: "Business registry",
                desc: "Free — OpenCorporates officer lookup (50/day free tier).",
                value: useRegistry,
                set: setUseRegistry,
              },
              {
                id: "use-websearch",
                label: "Web search fallback",
                desc: "~$0.05/lead — BBB, Houzz, Google, review responses via AI search.",
                value: useWebsearch,
                set: setUseWebsearch,
              },
            ].map(({ id, label, desc, value, set }) => (
              <div key={id} className="flex items-start gap-3">
                <input
                  id={id}
                  type="checkbox"
                  checked={value}
                  onChange={(e) => set(e.target.checked)}
                  className="mt-0.5 h-4 w-4 rounded border-border accent-brand"
                />
                <label htmlFor={id} className="cursor-pointer">
                  <span className="text-sm font-medium">{label}</span>
                  <p className="text-xs text-muted-foreground">{desc}</p>
                </label>
              </div>
            ))}
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

        {error && (
          <p className="rounded-md border border-destructive/40 bg-destructive/10 px-4 py-3 text-sm text-destructive">
            {error}
          </p>
        )}

        <div className="flex items-center justify-end gap-3">
          <Button type="button" variant="ghost" asChild>
            <Link href="/campaigns">Cancel</Link>
          </Button>
          <Button type="submit" disabled={submitting}>
            {submitting ? "Starting…" : "Start campaign"}
          </Button>
        </div>
      </form>
    </div>
  );
}
