# Target Qualified Leads — Design Spec

**Date:** 2026-05-04
**Author:** Daschel + Claude (brainstorming pair)
**Status:** Approved, not yet implemented

---

## Problem

The `--count` / `target_count` field is currently interpreted as "how many raw businesses to source." After filtering and owner research, the operator gets a fraction of that — often a fifth or less. A request for 50 leads in Charlotte produced 50 raw businesses → 28 kept after filter → 3 with owner names. Three usable leads is not 50 leads.

A lead, fundamentally, is a business we can pitch — meaning a business with both a kept-after-filter status *and* a confident owner full name. The pipeline should hunt until it has that many, or until we hit a sane spend ceiling.

## Goal

Reframe the pipeline so `target_count` means **qualified leads delivered** — kept businesses with `owner_full_name` and at least medium confidence. The sourcer iterates over progressively wider search strategies until the target is hit, the strategy ladder is exhausted, or a cost cap is reached.

## Non-goals (v1)

- Multi-city campaigns (still one city per campaign)
- Predictive yield models ("this city will yield 12 leads") — we'll learn from data later
- Re-running a completed campaign to top up leads (separate workflow)
- Changing what counts as "qualified" beyond `kept AND owner_full_name AND confidence in (high, medium)`
- Real-time UI progress showing the iteration ladder (text logs are enough)

## Definition of "qualified lead"

```
Lead.kept == True
AND Lead.owner_full_name != ""
AND Lead.owner_confidence in ("high", "medium")
```

(Today the pipeline doesn't store `owner_confidence` on the Lead — see Schema changes below.)

## Pipeline as an iteration loop

The orchestrator becomes a loop instead of a one-shot:

```
iteration = 0
while qualified_count < target_count and iteration < max_iterations and raw_sourced < raw_cap:
    iteration += 1
    strategy = strategy_ladder[iteration - 1]
    sourcer.run(state, strategy)         # adds *new* businesses to state.leads
    lead_filter.run(state)               # only filters the new ones
    owner_researcher.run(state)          # only researches the new kept ones
```

After each iteration we recompute `qualified_count`. If we hit the target, we stop and assemble CSVs from `state.leads`. If we exhaust strategies or the cap, we stop and ship what we have, with a clear log entry naming the reason.

## Strategy ladder

A small ordered list of progressively wider search strategies. Each strategy is a `dict` of parameters the sourcer can read. Stops at the first one that pushes us over `target_count`.

| # | Strategy | Radius | Keywords | Notes |
|---|---|---|---|---|
| 1 | Tight | 15 km | Default (3–4 niche variants) | Current behavior |
| 2 | Wide | 25 km | Default | Same keywords, more area |
| 3 | Wider | 40 km | Default | Pulls in suburbs and adjacent towns |
| 4 | Wider + extra keywords | 40 km | Default + 2 niche-adjacent variants | e.g. "remodeling contractor", "home renovation" |
| 5 | Maximum | 60 km | All variants | Last resort |

Each strategy is constrained by what Azure Maps and Yelp Fusion actually support — both cap at ~50 results per query, so adding keyword variants is the real lever, not just bigger radii.

The dedup cache (`agents/leads_cache.py`) is the safety net here: each iteration pulls fresh businesses because already-seen ones are filtered out before they reach the LLM. Without that cache this design would re-pay for the same businesses repeatedly.

## Stop conditions

The loop stops when *any* of these become true:

1. **Target hit:** `qualified_count >= target_count` — happy path.
2. **Strategy ladder exhausted:** All strategies attempted, no more to try.
3. **Raw cap hit:** Total raw businesses sourced this campaign hits `raw_cap` (default `4 × target_count`, max 400). Prevents runaway in markets that simply don't have the supply.
4. **Cost cap hit (optional):** Per-campaign spend approaches a soft ceiling (default $5). Tracked via approximate token counting against the Anthropic price card.

The orchestrator logs the stop reason with structured fields so the campaign event stream is honest about what happened: `target_hit`, `ladder_exhausted`, `raw_cap_hit`, `cost_cap_hit`.

## Schema changes

### `Lead`

Add one field:

```python
owner_confidence: str = ""  # "high" | "medium" | "low" | "none" | ""
```

Today's owner researcher already produces a confidence value but only uses it transiently for short-circuit logic — it's never persisted on the lead. We need it persisted so we can correctly count qualified leads on resume and on the campaigns list.

### `CampaignState`

Add two fields:

```python
target_count: int = 50              # already exists — semantics changes
raw_cap: int = 200                  # new — hard ceiling on businesses sourced
cost_cap_usd: float = 5.0           # new — soft ceiling, advisory
strategy_index: int = 0             # new — for resume
```

`target_count` keeps its name but now means qualified leads, not raw businesses. The frontend label changes accordingly.

### `campaigns` table

```sql
ALTER TABLE campaigns ADD COLUMN raw_cap        INTEGER NOT NULL DEFAULT 200;
ALTER TABLE campaigns ADD COLUMN cost_cap_usd   NUMERIC(6,2) NOT NULL DEFAULT 5.00;
ALTER TABLE campaigns ADD COLUMN strategy_index INTEGER NOT NULL DEFAULT 0;
ALTER TABLE campaigns ADD COLUMN stop_reason    TEXT;  -- target_hit | ladder_exhausted | raw_cap_hit | cost_cap_hit | error
```

### `leads` table

```sql
ALTER TABLE leads ADD COLUMN owner_confidence TEXT NOT NULL DEFAULT '';
```

Migration goes in `supabase/migrations/005_qualified_lead_targets.sql`.

## Sourcer changes

### Strategy parameter, not magic

Today the sourcer reads radius and keywords from `CONFIG`. v1 of this feature passes a `strategy: dict` argument from the orchestrator, defaulting to the current behavior (strategy 1) so single-iteration campaigns are unchanged in shape.

```python
def run(state: CampaignState, strategy: dict | None = None) -> None:
    radius = strategy.get("radius_m", CONFIG.azure_maps_default_radius_m) if strategy else CONFIG.azure_maps_default_radius_m
    extra_keywords = strategy.get("extra_keywords", []) if strategy else []
    ...
```

### Idempotency

The sourcer needs to be safe to call multiple times in the same campaign. Today it short-circuits via `state.is_done("sourcer")` — that has to change to a per-strategy checkpoint, e.g. `state.is_done(f"sourcer/strategy_{i}")`. The dedup cache already prevents re-adding already-seen businesses, so even without the checkpoint correctness is preserved; the checkpoint is for skipping API spend on resume.

## Lead filter and owner researcher changes

Both already handle "only process leads that haven't been processed yet" correctly. `lead_filter.py` filters leads with `kept` in its initial state; `owner_researcher.py` skips leads that already have `owner_full_name`. No semantic changes needed — they just get called again with new leads in `state.leads`.

The one tweak: `owner_researcher.py` should write `owner_confidence` onto the lead alongside `owner_full_name`. One-line change.

## Orchestrator (`run.py`)

This is the meaningful new code. Pseudocode:

```python
def run_pipeline(state: CampaignState, anthropic_key: str) -> None:
    while True:
        i = state.strategy_index
        if i >= len(STRATEGY_LADDER):
            state.stop_reason = "ladder_exhausted"; break

        strategy = STRATEGY_LADDER[i]
        sourcer.run(state, strategy)
        lead_filter.run(state, anthropic_key)
        owner_researcher.run(state, anthropic_key)

        qualified = sum(
            1 for l in state.leads
            if l.kept and l.owner_full_name and l.owner_confidence in ("high", "medium")
        )

        if qualified >= state.target_count:
            state.stop_reason = "target_hit"; break
        if len(state.leads) >= state.raw_cap:
            state.stop_reason = "raw_cap_hit"; break
        if state.estimated_spend_usd >= state.cost_cap_usd:
            state.stop_reason = "cost_cap_hit"; break

        state.strategy_index = i + 1
        state.save()

    csv_assembler.run(state)
    state.status = "completed"
    state.save()
```

`estimated_spend_usd` is a rough running total maintained by the agents — Sonnet input tokens × $3/M + output × $15/M, plus Haiku, plus a flat ~$0.01 per Phase 3 web_search invocation. Doesn't need to be precise; it's a brake, not an accountant.

## UI changes

### New-campaign form

The "How many" card label changes from "Target lead count" to **"Target qualified leads"** with the helper text:

> "How many businesses with confirmed owner names you want delivered. We'll keep widening the search until we hit this — or run out of leads in the city."

Two new advanced fields, collapsed by default behind a "Sourcing limits" toggle:

- **Raw lead cap** — default `target × 4`, range 50–400
- **Spend cap (USD)** — default $5, range $1–$20

Estimated-spend card stays but updates to reflect the cap, not the target.

### Campaigns list and detail

Show two numbers next to each campaign instead of one:

```
21 qualified · 73 sourced
```

If the campaign hit a non-`target_hit` stop reason, show a small chip: `Stopped early: ladder exhausted`. Operator should know they didn't get what they asked for.

### Live event stream

The orchestrator emits one new event per iteration:

```
[orchestrator] iteration 2/5 starting  {strategy: "wide", radius_m: 25000}
[orchestrator] iteration 2 complete    {qualified: 14, sourced_so_far: 142}
[orchestrator] stopping                {reason: "target_hit", final_qualified: 50}
```

## Backwards compatibility

Existing completed campaigns are unaffected — the `strategy_index` defaults to 0, no migration backfill needed. Existing in-flight campaigns (none expected, since campaigns finish in <10 minutes) would see new fields default to safe values.

The CLI flag `--count` keeps its name but means qualified leads now. Document this in the README's "Running" section. The behavioral change is visible: a `--count 50` run that used to deliver 10 will now deliver 30–50, taking longer and costing more.

## Edge cases

1. **Niche city with low supply.** A target of 50 in a town with only 30 remodelers total means we hit `ladder_exhausted` or `raw_cap_hit`. Campaign completes with whatever was found and a clear reason. No infinite loop.
2. **Owner researcher misses everything.** If every kept lead returns `confidence="none"` after Phase 3, the qualified count stays at zero. The loop progresses through strategies; if the ladder still runs out, we stop. The master CSV still has the rejected leads as audit.
3. **Cost cap mid-iteration.** Per-iteration cost is checked at iteration boundaries, not mid-flight. A single iteration can exceed the cap by some amount; the cap is a soft ceiling, not a hard SLA. Document that.
4. **Resume during loop.** `--resume` reads `strategy_index` from state and picks up at the next strategy. Per-iteration sourcer checkpoints prevent re-paying for completed strategies.
5. **Target = 0.** Reject at the API boundary as a validation error — no useful behavior.

## Acceptance criteria

1. A 50-lead campaign in Charlotte (current 11% conversion) sources several iterations and delivers either 50 qualified leads or hits one of the documented stop reasons. Total raw businesses sourced does not exceed `raw_cap`.
2. A 50-lead campaign in a small market (e.g. Bismarck, ND) hits `ladder_exhausted` cleanly with all leads found, no infinite loop.
3. The campaigns list distinguishes "qualified" from "sourced" counts and surfaces the stop reason for non-`target_hit` campaigns.
4. `python run.py --resume <id>` mid-iteration continues from `strategy_index`, doesn't re-source already-seen businesses (dedup cache covers this), and doesn't reset the loop.
5. The cost cap actually engages: a deliberate test with `cost_cap_usd = $0.50` on a 50-lead Charlotte target stops within one or two iterations.
6. The new-campaign form's "Estimated spend" matches reality within ±50% on a 50-lead representative campaign — wider tolerance than the current single-pass estimate because iteration count is variable.

## Why this design

1. **Output-shaped target, not input-shaped.** Operators think in deliverables, not API calls. Aligning the field name with the deliverable removes the cognitive translation step every time.
2. **Strategy ladder over magic auto-tuning.** Five hand-picked tiers are easy to reason about, easy to log, and easy to tune by tweaking constants. A blackbox optimizer would be more elegant and impossible to debug.
3. **Dedup cache as the central enabler.** Without it, the iteration loop would repay for the same businesses every round. Because the cache already exists and was load-tested in v1, we get the iteration design essentially for free at the data layer.
4. **Three independent stop conditions.** Target hit (the win), supply exhaustion (the city is small), spend cap (we're losing money). Each one fires in different real-world scenarios. Pretending one cap covers all three would silently fail in two of the three.
5. **`owner_confidence` persisted on Lead.** Today the field is computed and discarded. Persisting it makes "qualified" a definable predicate the system can compute on resume, on UI render, and in CSV assembly without re-running owner research.

## Out of scope, but worth flagging

- **Different qualification rules per campaign.** Some operators may want "qualified = kept AND owner_full_name AND has_email." Adding a `qualification_rule` enum would be straightforward but adds UI surface and isn't worth it until someone asks.
- **Showing predicted yield before launch.** "Charlotte historically yields ~30% qualified, expect ~3 iterations" — a real value-add, but requires accumulating enough completed-campaign data to be meaningful. Defer.
- **Background re-sourcing.** Marking a completed campaign and saying "find me 20 more like these" is a different workflow with different UX. Out of scope here.
- **Charging per qualified lead in any meta-budget.** That's a billing concern; we're a producer, not a meter.

## Implementation notes for whoever picks this up

- Migration: `supabase/migrations/005_qualified_lead_targets.sql`
- Strategy ladder lives as a module-level constant in `run.py` (or a new `agents/strategy_ladder.py`); not a config row, because changing it should be code review territory.
- `owner_researcher` writes `owner_confidence` on the Lead — search for the result-application block inside the `as_completed` loop and add one line.
- The estimated-spend tracker is small new code (~20 lines) keyed off Anthropic response usage fields. It's a soft brake; do not gate iterations on it being precise.
- API endpoint `POST /campaigns` accepts the new `raw_cap` and `cost_cap_usd` optional body fields with sane defaults.
- The CLI keeps `--count` as a synonym for `--target-count`. Don't break existing scripts.
