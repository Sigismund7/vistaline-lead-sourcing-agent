# Smoke Test: Orlando, FL — kitchen remodelers — count=20

**Date:** 2026-05-02  
**Campaign ID:** 20260503-021309-091414 (primary clean run)  
**Resume campaign:** 20260503-021832-c8d369 (interrupt/resume verification)  
**Branch:** phase1-frontend-skeleton (all Phase 0 cycles merged to main)

---

## Header Metrics

| Metric | Value | Target |
|--------|-------|--------|
| Total sourced | 20 | 20 |
| Business-fit accuracy (filter correct) | 11/11 rejections correct | — |
| Kept after filter | 9/20 (45%) | — |
| Owner-name found (clean run) | 9/9 kept (100%) | ≥80% |
| Owner-name found (resume run) | 3/9 kept (33%) | — |
| Email pre-found | 0/9 | — |
| Website-finder hit rate | 17/21 checked (81%) | — |
| Azure leads | 9 | — |
| Yelp leads | 20 | — |
| Cross-source dedup rate | 0/29 (0%) | — |
| Azure rate-limit incidents | 0 | — |
| Yelp rate-limit incidents | 0 | — |
| Resume contract | ✅ holds | pass |

---

## Per-Source Contribution

| Source | Raw count | After dedup cut to target |
|--------|-----------|--------------------------|
| azure_maps | 9 | 9 |
| yelp_fusion | 20 | 11 |
| azure_maps+yelp_fusion | 0 | 0 |

Zero cross-source dedup merges — Azure and Yelp returned entirely distinct result sets for "kitchen remodelers" in Orlando. Either the POI categories don't overlap, or the same businesses appear under different names/addresses across the two APIs. Worth monitoring at count=50.

---

## Findings

Frequency-sorted. Each row: `symptom | suspected file | fix sketch | count`

| # | Symptom | File | Fix sketch | Count |
|---|---------|------|------------|-------|
| 1 | `wrong-business-fit` — food/restaurant noise from "kitchen" keyword | `agents/sources/azure_maps.py`, `agents/sources/yelp_fusion.py` | Rotate to more specific terms: "kitchen cabinet installation", "kitchen remodel contractor", "bath and kitchen renovation"; add pre-filter in sourcer dropping names containing restaurant/café/food bank | 7 |
| 2 | `wrong-business-fit` — geo bleed (904 Jacksonville, 786 Miami) | `agents/lead_filter.py` | Filter is already catching these correctly. Consider adding a known-bad area-code blocklist per city to the sourcer pre-filter to save API calls | 2 |
| 3 | `wrong-business-fit` — directory-only website (bisprofiles.com, business.winterpark.org) | `agents/lead_filter.py` | Filter correctly rejecting. website_finder's directory blocklist doesn't include these; add `bisprofiles.com`, `business.winterpark.org` to `_DIRECTORY_DOMAINS` in `agents/website_finder.py` | 2 |
| 4 | `website-finder-miss` — press release URL returned instead of business website | `agents/website_finder.py` | I-4 Kitchen Bath resolved to `markets.businessinsider.com`. Add news/press-release domains to directory blocklist: `businessinsider.com`, `prnewswire.com`, `prweb.com`, `globenewswire.com` | 1 |
| 5 | `name-wrong` (potential) — owner name sourced from press release, not verified against BBB | `agents/owner_researcher.py` | Junior Malafaia found via Business Insider article. Phase 2 BBB cross-check (currently skipped when Phase 1 succeeds) would catch this | 1 |
| 6 | `name-missing` on resume — owner researcher re-runs from scratch after interrupt, BBB web_search non-determinism yields 3/9 vs 9/9 | `agents/owner_researcher.py` | Add per-lead checkpointing to owner_researcher so individual results survive an interrupt | 1 |

---

## Kept Leads (clean run)

| Business | Owner | Source | Notes |
|----------|-------|--------|-------|
| MJ Renovation | Jeniffer Salas | bbb_search | Clean |
| JCP Construction | JC Peterson | bbb_search | Clean |
| Hosanna Building Contractors | Dean Blankenship | website | Clean |
| I-4 Kitchen Bath | Junior Malafaia | website | Website field is a Business Insider URL — real site likely `i4kitchenbath.com` |
| TEK Construction Group | Eriberto Lopez | website | Clean |
| American Kitchens | Tom Vravis | bbb_search | Clean |
| KBF Design Gallery | Keith Vellequette | website | Clean |
| S&W Kitchens | Joe Steenbeke Sr. | website | Clean |
| Nu Kitchen Designs | Josh Torres | website | Clean |

---

## Resume Contract Verification

- **Interrupted:** after `[sourcer] done` / mid `[lead_filter]`
- **Sourcer on resume:** `already complete, skipping (20 leads)` ✅
- **Lead_filter on resume:** `already complete, skipping (9 kept)` ✅
- **Owner_researcher on resume:** re-ran 9 leads (not checkpointed at lead level)
- **No duplicates:** confirmed (CSV has same 20 rows, same place_ids)
- **Completed:** ✅

**Verdict:** Resume contract holds for sourcer and lead_filter. Owner_researcher correctly re-runs after an interrupt (not marked done mid-run), but non-determinism in BBB web_search means a resumed run may produce fewer names than an uninterrupted run.

---

## Phase 2 Task Priorities (frequency ≥ 1)

1. **Keyword noise tightening** — 7 occurrences. Rotate search terms away from bare "kitchen" in both Azure and Yelp adapters. Add cheap pre-filter in sourcer to drop obvious non-contractors before lead_filter burns API calls. ← highest priority
2. **Expand directory blocklist** — 2 occurrences. Add `bisprofiles.com`, `business.winterpark.org`, `markets.businessinsider.com`, `prnewswire.com` to `_DIRECTORY_DOMAINS` in `agents/website_finder.py`. Quick fix.
3. **BBB cross-validation for website-sourced names** — 1 occurrence (potential). Run Phase 2 always as a confidence check, not only on Phase 1 failure. Cost: ~9 extra web_search calls per count=20 run. Low priority.
4. **Per-lead checkpointing in owner_researcher** — 1 occurrence. Saves re-work on interrupted runs. Medium complexity.

---

## Gate Assessment

**Gate to Phase 2:** findings populated. ✅  
**Zero-failure path (jump to Phase 3):** ❌ — keyword noise (7 occurrences) warrants at least one Phase 2 tightening pass before count=50 validation.
