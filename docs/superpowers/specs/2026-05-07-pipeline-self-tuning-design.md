# Pipeline Self-Tuning — Design Spec

**Date:** 2026-05-07
**Author:** Daschel + Claude (office hours)
**Status:** DRAFT
**Mode:** Builder (intrapreneurship — Vistaline internal tool)
**Branch context:** drafted while on `yelp-owner-profile`; intended to land after that branch merges to `main`

---

## Problem

The sourcing pipeline runs the same way every time. Keyword variants are weighted equally, owner-research phases run in fixed order, and the filter prompt is static. Every campaign produces ground truth — kept-by-filter, owner-found-by-phase, cost — but that data is never read back. Hit rates plateau at whatever the initial keyword/phase/prompt choices happened to produce on day one.

## Goal

Three independent self-tuning loops, all driven by data the pipeline already produces. No new paid APIs. No model training. No separate "learning service." Each loop ships as a small addition to an existing agent.

## Non-goals (v1)

- Conversion-based learning (reply rate, booked calls, closed deals)
- Model fine-tuning or RL
- Cross-niche transfer learning
- Cross-tenant learning when this becomes a multi-client agency product
- A separate ML service or training pipeline
- Real-time online learning (rewards arrive at end-of-campaign, not per-action)

## Constraints

From `CLAUDE.md`:
- Orchestrator stays deterministic Python. No LLM-decision-loop at `run.py` level.
- Each agent has one job, writes to `CampaignState`, checks `state.is_done(...)` at the top.
- `tools.py` only holds API clients. No business logic. No LLM calls.
- No new paid API surfaces without explicit approval.
- `MAX_PARALLEL = 8` default for parallel work.
- Type hints, dataclasses for structured data, `pathlib.Path`, bounded HTTP timeouts.

From the architecture:
- State persists after every step. Resumability is sacred — every loop must tolerate a crash mid-campaign.
- Agents never share LLM clients across threads.

## Premises

1. The signal we need (kept-rate, owner-found-by-phase, cost) is already produced. No external data source required.
2. Action spaces are small (10-30 keyword variants per niche, 3-4 phase orderings). Scoring + exploration beats any trained model at this scale.
3. Per-niche learning is required. Cross-niche transfer is a v2 concern.
4. Cold start is bounded. First 2-3 campaigns per niche run on defaults; learning kicks in after.
5. Stats live in Supabase alongside `leads` and `campaigns`. No new infrastructure.
6. Loops are independently observable. Each one's effect must be visible on the results page or it's a black box.

---

## Loop A — Keyword scoring in sourcer

**Where:** `agents/sourcer.py` (+ new `agents/keyword_proposer.py` for quarterly review)

**What it does:** Per (niche, keyword_variant), tracks lifetime stats. Each campaign samples keywords weighted by performance, with reserved exploration budget.

### Schema

New Supabase table `keyword_stats`:

```sql
CREATE TABLE keyword_stats (
  niche TEXT NOT NULL,
  keyword TEXT NOT NULL,
  campaigns_used INT NOT NULL DEFAULT 0,
  leads_returned INT NOT NULL DEFAULT 0,   -- raw count from Places
  kept_by_filter INT NOT NULL DEFAULT 0,   -- survived lead_filter
  owner_found INT NOT NULL DEFAULT 0,      -- owner via any phase
  cost_usd NUMERIC(10,4) NOT NULL DEFAULT 0,
  last_used_at TIMESTAMPTZ,
  PRIMARY KEY (niche, keyword)
);
```

New column on `leads`:
- `source_keyword TEXT` — which variant returned this business. Populated by sourcer at insertion time. Required for attribution.

### Scoring

```
score = (kept_by_filter + 0.5 * owner_found) / max(cost_usd, 0.01)
```

Both signals matter: `kept_by_filter` is the cheap proximate signal; `owner_found` is the deeper one. Owner is half-weighted because owner success also depends on Loop B — don't reward keywords for things the researcher did.

### Sampling rule per campaign

1. **80% of Places budget → top-N variants by score**, Thompson-sampled: add `Beta(α, β)` noise where `α = kept`, `β = leads_returned - kept`. Variants with similar scores rotate naturally; high-confidence winners dominate.
2. **20% exploration budget**, split:
   - Half on low-data variants (`campaigns_used < 5`)
   - Half on retired variants (high score historically but unused for ≥10 campaigns — niches drift)

### Cold start

New niche with no history: use the existing keyword bank, all variants equally weighted. Switch to scored sampling after 3 campaigns of accumulated data.

### Quarterly variant generation

After every 10 campaigns in a niche, run `agents/keyword_proposer.py`:

1. Pull top-10 and bottom-10 variants for the niche from `keyword_stats`.
2. One Claude call: "Here's what worked, here's what didn't. Propose 5 new variants and flag 3 to retire. Explain why."
3. Write proposals to `keyword_proposals` table for user review.
4. User approves/rejects via a small CLI command (`python run.py --review-keywords <niche>`). Approved variants land in the bank; rejected proposals get logged to avoid re-proposing.

This is the only new LLM call. ~$0.05 per niche per quarter.

### Implementation notes

- Sourcer already knows which variant returned which business; persist as `leads.source_keyword` at insert time.
- After campaign completion, an aggregator job reads new leads + filter outcomes + owner outcomes and updates `keyword_stats` in one transaction. Avoids hot-row contention during the run.
- The aggregator runs in `csv_assembler.py` after CSV write — pipeline is already done, race-free.

---

## Loop B — Phase ordering in owner researcher

**Where:** `agents/owner_researcher.py`

**What it does:** Per (niche, phase), tracks success rate and cost. For each lead, runs phases in descending expected-value order; short-circuits on owner found.

This is the **highest-leverage loop** because Phase 3 (BBB/Google `web_search`) is the most expensive surface. Even small reductions in Phase 3 attempts compound across every lead in every campaign.

### Schema

New Supabase table `phase_stats`:

```sql
CREATE TABLE phase_stats (
  niche TEXT NOT NULL,
  phase TEXT NOT NULL,        -- "yelp_profile" | "website_crawl" | "bbb_google" | future phases
  attempts INT NOT NULL DEFAULT 0,
  successes INT NOT NULL DEFAULT 0,
  cost_usd NUMERIC(10,4) NOT NULL DEFAULT 0,
  PRIMARY KEY (niche, phase)
);
```

### Ordering rule per lead

```
expected_value(phase) = (successes / attempts) / (cost_usd / attempts + 0.001)
                      = successes / (cost_usd + 0.001 * attempts)
```

Run phases in descending EV order. Short-circuit when owner is found.

### Bayesian shrinkage for low-data phases

If a phase has fewer than 10 attempts in a niche, treat its EV as `0.7 * niche_specific + 0.3 * global_average`. Prevents one lucky early hit from locking in a phase order forever.

### Guard rails

- **Never drop a phase entirely.** Even a 5%-success phase runs occasionally — distribution shifts, niches evolve.
- **Cost normalization matters more than attempt counts.** Free phases (website crawl) and paid phases (`web_search`) are not comparable on raw success rate.
- **Per-niche, not global.** Roofing → BBB-heavy. Kitchen remodelers → Yelp-heavy. HVAC → website crawl rarely yields owner. Don't pool.

### Cold start

Use the current fixed order (Yelp → website → BBB/Google) until 50 leads of data per niche. Then switch to learned ordering.

### Implementation notes

- The existing agent already runs phases sequentially. The change: a `phase_order(niche)` helper that consults `phase_stats` and returns an ordered list.
- Each phase invocation logs `(niche, phase, succeeded, cost)` to a per-campaign log; aggregator rolls up at end of campaign.
- Idempotency check (`state.is_done(...)`) is unchanged — we're reordering phases, not changing the per-lead contract.

---

## Loop C — Filter few-shot injection

**Where:** `agents/lead_filter.py`

**What it does:** Augments the static SOP rules with recent niche-specific exemplars.

### Exemplar selection (per filter batch)

- 5 most recent leads in this niche where `kept = true` AND `owner_found = true`
- 5 most recent leads in this niche where `kept = false`, with the rejection reason

Pulled fresh each campaign. No caching needed at this scale.

### Prompt structure

```
[existing SOP rules verbatim]

Recent KEPT leads in this niche (these passed filter and got an owner):
1. <name> | <city> | <category> | <why kept>
...

Recent REJECTED leads in this niche:
1. <name> | <city> | <category> | <reject_reason>
...

Apply the same judgment to:
[new batch of 25]
```

### Cold start

Falls back to static SOP rules when the niche has fewer than 10 classified leads. Identical to current behavior.

### Open question (real one)

When SOP rules are already crisp, does few-shot help or hurt? It can drift the model toward niche-local patterns that don't generalize, or it can catch regional variations the SOPs miss.

**Resolution:** A/B on the next 5 campaigns. Same niche, same city, alternating with/without exemplars. Compare kept-rate and the human review of borderline rejections. If no clear win, pull Loop C.

---

## Schema summary

**New tables:** `keyword_stats`, `phase_stats`, `keyword_proposals` (small, for Loop A's quarterly review queue)

**New columns:**
- `leads.source_keyword TEXT` (Loop A attribution)
- `campaigns.keyword_strategy JSONB` (snapshot of which variants ran with what weights — debugging only)

All migrations additive, default-nullable, no downtime.

---

## Build order

Each loop ships as its own PR with its own smoke test (`python run.py --count 5` on a small city, inspect master CSV).

1. **Loop B first.** Highest cost savings. Smallest surface (one agent + one table). Easy to A/B against fixed ordering. Cleanest win.
2. **Loop A second.** Bigger code surface (sourcer + aggregator + proposer + two tables). Bigger long-term upside.
3. **Loop C third.** Smallest change but biggest unknown. Run the A/B test, decide on evidence.

**Branch sequencing:** Land `yelp-owner-profile` first. Loop B touches `owner_researcher.py` and the Yelp branch already changes that file — building B on top of an unmerged Yelp branch is a merge headache. Don't start Loop B until Yelp is on `main`.

---

## Observability

Without UI, the loops are black boxes and you can't tell whether they're helping.

Add to the campaign results page (`frontend/app/campaigns/[id]/results/page.tsx`), small expandable "Self-tuning" panel:

- **Loop A:** Top 5 keywords by score for this niche, with `kept-rate` and `cost-per-kept-lead` deltas vs niche average.
- **Loop B:** Phase hit rates for this niche, in execution order. Highlight which phase resolved each owner.
- **Loop C:** Whether exemplars were active for this campaign, and which exemplar leads were used.

Without these panels, the loops are unfalsifiable. With them, you can see exactly why the system made each choice and override when wrong.

---

## Cost discipline

- Loop A: zero new paid API calls. Pure scoring of existing Places usage. The keyword proposer is one Claude call per niche per quarter — call it $0.05.
- Loop B: zero new paid API calls. Reorders existing phase invocations and may *reduce* `web_search` spend.
- Loop C: zero new paid API calls. Just adds context to existing Claude filter calls (slightly higher input token cost — ~$0.001 extra per filter batch).

Compatible with the no-new-paid-APIs rule in `CLAUDE.md`.

---

## Success criteria

Measured after 20 campaigns per niche on a niche that has been live since launch:

1. **Kept-rate up:** average `kept / leads_returned` rises ≥10% comparing first 5 campaigns to last 5.
2. **Phase 3 down:** `web_search` calls per lead drop ≥20%, attributable to Loop B.
3. **Cost-per-kept-lead down:** ≥15% reduction in mature niches.
4. **Full traceability:** for any lead in the master CSV, you can read off which keyword sourced it and which phase resolved its owner.

**Kill criterion:** if after 20 campaigns no measurable improvement appears, pull the loops. Action spaces would be smaller than the noise floor and the bandit shape would be wrong for the problem.

---

## Open questions

1. **Niche normalization.** Where does niche live in the current schema? `campaigns.niche` exists, but is it free-text or a controlled vocabulary? Loops require consistent keys. May need a small enum migration.
2. **Niche count.** How many distinct niches will Vistaline run? If <5, learning converges fast. If >50, cold-start cost dominates and the design needs cross-niche priors.
3. **Auto-apply or manual review on keyword proposals?** Lean toward manual review — generated keywords can be subtly wrong (over-broad, regionally weird, brand-name conflicts). Cost of one CLI command per quarter is low.
4. **Multi-tenant future.** When this becomes an agency product, do clients share keyword learnings or stay isolated? Default: isolated. Cross-client transfer is v2.
5. **Backfill.** Should existing leads be retroactively used to seed `keyword_stats` and `phase_stats`? Yes for `phase_stats` (the data is recoverable from existing lead rows). No for `keyword_stats` (we don't have `source_keyword` on historical leads — too expensive to reconstruct).

---

## What I noticed about how you think

- "Like is this something worth training?" — you correctly identified the meta-question most builders skip. Asking *whether* the heavy machinery is right, before reaching for it, is the move.
- "I think A and B are the most useful by far" — you ranked by leverage immediately. Phase ordering being the highest-cost-savings loop isn't obvious without thinking about which API surface is most expensive; you got there in one beat.
- "Nah maybe make a plan for AB and C for now" — committed to all three after deciding training was overkill. Conviction-after-debate, not indecision. The casualness of "nah" is doing real work — you're saying "stop deliberating, ship the simple version."

---

## Next steps

If approved:
- Move to `/writing-plans` to break this into tasks (estimated 8-12 tasks across the three loops + observability panel)
- First implementation sub-skill recommendation: `superpowers:subagent-driven-development` for Loop B (smallest surface, easiest to verify)

Loop B is buildable on `main` today once `yelp-owner-profile` merges. Loops A and C don't depend on the Yelp branch.
