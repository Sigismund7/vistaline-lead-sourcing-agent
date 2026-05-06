# Cost Estimator + Quota Fulfillment Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** (1) Show real Anthropic API cost projections before each run; (2) Loop the sourcer/filter/researcher until `target_count` leads with owner first names are found or the geographic area is exhausted, reusing `leads_cache.db` to skip already-seen businesses.

**Architecture:**
- **Cost estimator** (`agents/cost_estimator.py`): pure-math module, no API calls. Sourced by CLI banner and a new `GET /estimate` API route.
- **Quota loop**: `sourcer.run()` gains `round_n` / `batch_size` kwargs and returns new-lead count. `lead_filter` adds a `filter_done: bool` field to `Lead` so it only processes new unfiltered leads each call. `owner_researcher` already targets `kept and not owner_full_name` — just remove its single-run guard. `run.py` and `api/runner.py` replace the 4-step linear pipeline with a `for round_n in range(MAX_SOURCING_ROUNDS)` loop.
- **DB migration**: adds `filter_done BOOLEAN NOT NULL DEFAULT TRUE` to the `leads` table.

**Tech Stack:** Python 3.9+, Anthropic SDK (claude-sonnet-4-20250514), Supabase (existing), SQLite leads_cache (existing), FastAPI (existing).

---

## File Map

| Action | Path |
|--------|------|
| Create | `agents/cost_estimator.py` |
| Create | `tests/test_cost_estimator.py` |
| Modify | `agents/lead_filter.py` |
| Modify | `agents/owner_researcher.py` |
| Modify | `agents/sourcer.py` |
| Modify | `state.py` (`Lead` dataclass + `save_leads` + `load`) |
| Modify | `run.py` |
| Modify | `api/main.py` |
| Modify | `api/runner.py` |
| Create | `supabase/migrations/20260506_add_filter_done.sql` |

---

## Part A — Cost Estimator (Tasks 1–5)

### Task 1: Write failing tests for cost_estimator

**Files:**
- Create: `tests/test_cost_estimator.py`

- [ ] **Step 1.1: Write the tests**

```python
# tests/test_cost_estimator.py
"""Unit tests for agents/cost_estimator.py — pure math, no API calls."""
from agents.cost_estimator import estimate, CostEstimate


def test_estimate_returns_dataclass():
    result = estimate(target_named=30)
    assert isinstance(result, CostEstimate)


def test_estimate_raw_leads_formula():
    # raw = ceil(30 / (0.45 * 0.65)) = ceil(102.56) = 103
    result = estimate(target_named=30, keep_rate=0.45, total_hit_rate=0.65)
    assert result.estimated_raw_to_source == 103


def test_estimate_kept_formula():
    result = estimate(target_named=30, keep_rate=0.45, total_hit_rate=0.65)
    # kept = ceil(103 * 0.45) = ceil(46.35) = 47
    assert result.estimated_kept == 47


def test_total_is_sum_of_parts():
    result = estimate(target_named=30)
    parts = result.lead_filter_usd + result.owner_phase1_usd + result.owner_phase3_usd
    assert abs(result.total_usd - parts) < 0.001


def test_zero_target_returns_zero_cost():
    result = estimate(target_named=0)
    assert result.total_usd == 0.0
    assert result.estimated_raw_to_source == 0


def test_larger_target_costs_more():
    small = estimate(target_named=20)
    large = estimate(target_named=60)
    assert large.total_usd > small.total_usd


def test_higher_keep_rate_lowers_cost():
    # Higher keep rate → fewer raw leads needed → lower filter cost
    low_keep = estimate(target_named=30, keep_rate=0.30)
    high_keep = estimate(target_named=30, keep_rate=0.70)
    assert high_keep.total_usd < low_keep.total_usd


def test_summary_contains_dollar_sign():
    result = estimate(target_named=30)
    assert "$" in result.summary()
```

- [ ] **Step 1.2: Run tests to confirm they fail (module not yet created)**

```bash
cd "/Users/daschelgorgenyi/Desktop/Vistaline-Lead Sourcing Agent" && \
python -m pytest tests/test_cost_estimator.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'agents.cost_estimator'`

---

### Task 2: Implement agents/cost_estimator.py

**Files:**
- Create: `agents/cost_estimator.py`

- [ ] **Step 2.1: Write the module**

```python
# agents/cost_estimator.py
"""Pre-run Anthropic API cost projector for the Vistaline lead pipeline.

Projects spend (USD) given a target number of named leads.
Uses empirical token counts calibrated from real runs. No API calls — pure math.
"""
from __future__ import annotations
import math
from dataclasses import dataclass

# claude-sonnet-4-20250514 pricing (May 2026)
_SONNET_INPUT_PER_MTOK: float = 3.00    # USD per million input tokens
_SONNET_OUTPUT_PER_MTOK: float = 15.00  # USD per million output tokens

# Lead filter: system ~500t + 80t/lead × 25-lead batch. Output ~20t/lead.
_FILTER_SYSTEM_TOKENS: int = 500
_FILTER_TOKENS_PER_LEAD: int = 80
_FILTER_OUTPUT_TOKENS_PER_LEAD: int = 20
_FILTER_BATCH_SIZE: int = 25

# Owner researcher Phase 1 (website crawl + Claude parse): ~2500t input, ~300t output per lead
_OWNER_P1_INPUT_TOKENS: int = 2500
_OWNER_P1_OUTPUT_TOKENS: int = 300

# Owner researcher Phase 3 (web_search with max_uses=7): ~$0.04/lead per codebase docstring
_OWNER_P3_COST_PER_LEAD: float = 0.04

# Default empirical rates (calibrated from smoke-test observations)
_DEFAULT_KEEP_RATE: float = 0.45        # fraction of raw leads passing lead_filter
_DEFAULT_PHASE1_HIT_RATE: float = 0.55  # fraction of kept leads found via website crawl
_DEFAULT_PHASE2_HIT_RATE: float = 0.20  # fraction of phase-1 misses found by OpenCorporates
_DEFAULT_TOTAL_HIT_RATE: float = 0.65   # all phases combined


@dataclass
class CostEstimate:
    """Projected cost breakdown for one pipeline run."""
    target_named_leads: int
    estimated_raw_to_source: int
    estimated_kept: int
    keep_rate: float
    total_owner_hit_rate: float
    lead_filter_usd: float
    owner_phase1_usd: float
    owner_phase3_usd: float
    total_usd: float

    def summary(self) -> str:
        """Human-readable multi-line cost breakdown for CLI banner."""
        return (
            f"  est. raw to source:   {self.estimated_raw_to_source} businesses\n"
            f"  est. kept after filter:{self.estimated_kept}\n"
            f"  lead filter cost:      ${self.lead_filter_usd:.3f}\n"
            f"  owner phase-1 cost:    ${self.owner_phase1_usd:.3f}\n"
            f"  owner phase-3 cost:    ${self.owner_phase3_usd:.3f}\n"
            f"  ── projected total:    ${self.total_usd:.3f}\n"
        )


def estimate(
    target_named: int,
    *,
    keep_rate: float = _DEFAULT_KEEP_RATE,
    total_hit_rate: float = _DEFAULT_TOTAL_HIT_RATE,
    phase1_hit_rate: float = _DEFAULT_PHASE1_HIT_RATE,
    phase2_hit_rate: float = _DEFAULT_PHASE2_HIT_RATE,
) -> CostEstimate:
    """Project Anthropic API spend for a run targeting target_named owner-name leads.

    Args:
        target_named: desired count of leads with owner_first populated.
        keep_rate: fraction of raw sourced leads that pass lead_filter.
        total_hit_rate: fraction of kept leads that get an owner name across all phases.
        phase1_hit_rate: fraction of kept leads found by website crawl phase.
        phase2_hit_rate: fraction of phase-1 misses found by OpenCorporates (free tier).
    """
    if target_named <= 0:
        return CostEstimate(
            target_named_leads=0, estimated_raw_to_source=0, estimated_kept=0,
            keep_rate=keep_rate, total_owner_hit_rate=total_hit_rate,
            lead_filter_usd=0.0, owner_phase1_usd=0.0, owner_phase3_usd=0.0, total_usd=0.0,
        )

    raw = math.ceil(target_named / (keep_rate * total_hit_rate))
    kept = math.ceil(raw * keep_rate)

    # Lead filter: ceil(raw / 25) batches, each batch = system + 25 leads in + decisions out
    filter_batches = math.ceil(raw / _FILTER_BATCH_SIZE)
    filter_input = filter_batches * (_FILTER_SYSTEM_TOKENS + _FILTER_TOKENS_PER_LEAD * _FILTER_BATCH_SIZE)
    filter_output = filter_batches * (_FILTER_OUTPUT_TOKENS_PER_LEAD * _FILTER_BATCH_SIZE)
    filter_usd = (
        filter_input * _SONNET_INPUT_PER_MTOK + filter_output * _SONNET_OUTPUT_PER_MTOK
    ) / 1_000_000

    # Owner Phase 1: Claude runs on every kept lead (website crawl content → parse)
    p1_input = kept * _OWNER_P1_INPUT_TOKENS
    p1_output = kept * _OWNER_P1_OUTPUT_TOKENS
    p1_usd = (
        p1_input * _SONNET_INPUT_PER_MTOK + p1_output * _SONNET_OUTPUT_PER_MTOK
    ) / 1_000_000

    # Owner Phase 3: leads that phase1 and phase2 both miss
    # phase3_reach = 1 - phase1_hit - (1 - phase1_hit) × phase2_hit
    phase3_reach = 1.0 - phase1_hit_rate - (1.0 - phase1_hit_rate) * phase2_hit_rate
    p3_leads = math.ceil(kept * phase3_reach)
    p3_usd = p3_leads * _OWNER_P3_COST_PER_LEAD

    total = filter_usd + p1_usd + p3_usd
    return CostEstimate(
        target_named_leads=target_named,
        estimated_raw_to_source=raw,
        estimated_kept=kept,
        keep_rate=keep_rate,
        total_owner_hit_rate=total_hit_rate,
        lead_filter_usd=round(filter_usd, 4),
        owner_phase1_usd=round(p1_usd, 4),
        owner_phase3_usd=round(p3_usd, 4),
        total_usd=round(total, 4),
    )
```

---

### Task 3: Run cost estimator tests

**Files:** (no changes)

- [ ] **Step 3.1: Run tests**

```bash
cd "/Users/daschelgorgenyi/Desktop/Vistaline-Lead Sourcing Agent" && \
python -m pytest tests/test_cost_estimator.py -v
```

Expected: `8 passed` in green.

- [ ] **Step 3.2: Commit**

```bash
git add agents/cost_estimator.py tests/test_cost_estimator.py
git commit -m "feat(cost): add cost_estimator module with unit tests"
```

---

### Task 4: Add GET /estimate endpoint to api/main.py

**Files:**
- Modify: `api/main.py`

- [ ] **Step 4.1: Add import and route**

After the existing `from api.runner import run_pipeline` import line, add:

```python
from agents.cost_estimator import estimate as _cost_estimate
```

After the `GET /campaigns` route (around line 55), add:

```python
@app.get("/estimate")
def get_estimate(count: int = 50, keep_rate: float = 0.45, _: AuthDep = None):
    """Return projected Anthropic API cost for a planned run. No auth required for reads."""
    est = _cost_estimate(target_named=count, keep_rate=keep_rate)
    return {
        "target_named_leads": est.target_named_leads,
        "estimated_raw_to_source": est.estimated_raw_to_source,
        "estimated_kept": est.estimated_kept,
        "lead_filter_usd": est.lead_filter_usd,
        "owner_phase1_usd": est.owner_phase1_usd,
        "owner_phase3_usd": est.owner_phase3_usd,
        "total_usd": est.total_usd,
    }
```

- [ ] **Step 4.2: Verify import chain**

```bash
cd "/Users/daschelgorgenyi/Desktop/Vistaline-Lead Sourcing Agent" && \
python -c "from api.main import app; print('OK')"
```

Expected: `OK`

- [ ] **Step 4.3: Commit**

```bash
git add api/main.py
git commit -m "feat(api): add GET /estimate endpoint for pre-run cost projection"
```

---

### Task 5: Show cost estimate in run.py banner

**Files:**
- Modify: `run.py` (`banner` function only, lines 106-113)

- [ ] **Step 5.1: Update the banner function**

Replace the entire `banner` function with:

```python
def banner(state: CampaignState) -> None:
    from agents.cost_estimator import estimate as _estimate
    est = _estimate(target_named=state.target_count)
    raw_str = f"~{est.estimated_raw_to_source} businesses"
    cost_str = f"~${est.total_usd:.2f} (Anthropic API est.)"
    print()
    print("┌" + "─" * 58 + "┐")
    print(f"│  Vistaline Lead-Gen — {state.campaign_id:<33}│")
    print(f"│  city:   {state.city + ', ' + state.state_abbr:<48}│")
    print(f"│  niche:  {state.niche:<48}│")
    print(f"│  target: {str(state.target_count) + ' leads with owner names':<48}│")
    print(f"│  raw:    {raw_str:<48}│")
    print(f"│  cost:   {cost_str:<48}│")
    print("└" + "─" * 58 + "┘")
```

- [ ] **Step 5.2: Verify import**

```bash
cd "/Users/daschelgorgenyi/Desktop/Vistaline-Lead Sourcing Agent" && \
python -c "from run import banner; print('OK')"
```

Expected: `OK`

- [ ] **Step 5.3: Commit**

```bash
git add run.py
git commit -m "feat(cli): show projected cost in run.py banner"
```

---

## Part B — Quota Fulfillment Loop (Tasks 6–16)

### Task 6: Run Supabase migration — add filter_done column

**Files:**
- Create: `supabase/migrations/20260506_add_filter_done.sql`

- [ ] **Step 6.1: Create the migration file**

```sql
-- supabase/migrations/20260506_add_filter_done.sql
-- Adds filter_done to leads so the quota loop can process new leads incrementally.
-- DEFAULT TRUE: all pre-migration rows (from completed campaigns) are treated as
-- already filtered, preventing re-processing on any resumed run.
ALTER TABLE leads ADD COLUMN IF NOT EXISTS filter_done BOOLEAN NOT NULL DEFAULT TRUE;
```

- [ ] **Step 6.2: Run the migration in Supabase dashboard**

Open Supabase dashboard → SQL Editor → paste and run the contents of `supabase/migrations/20260506_add_filter_done.sql`.

Expected: `Success. No rows returned.`

- [ ] **Step 6.3: Commit the migration file**

```bash
git add supabase/migrations/20260506_add_filter_done.sql
git commit -m "db: add filter_done column to leads table (DEFAULT TRUE for existing rows)"
```

---

### Task 7: Write failing tests for filter_done behavior

**Files:**
- Create: `tests/test_filter_done_field.py`

- [ ] **Step 7.1: Write tests**

```python
# tests/test_filter_done_field.py
"""Tests for Lead.filter_done and lead_filter incremental behavior.
No Supabase connection required — tests use in-memory state only.
"""
from state import Lead, CampaignState


def _make_state(n_leads: int = 3) -> CampaignState:
    state = CampaignState(campaign_id="test-filter-done")
    state.city = "Orlando"
    state.state_abbr = "FL"
    state.niche = "bathroom remodeling"
    state.target_count = 10
    for i in range(n_leads):
        state.leads.append(Lead(
            business_name=f"Test Co {i}",
            phone="4075550100",
            website=f"https://testco{i}.com",
        ))
    return state


def test_lead_filter_done_defaults_false():
    lead = Lead(business_name="Test Co")
    assert lead.filter_done is False


def test_new_leads_start_as_filter_done_false():
    state = _make_state(3)
    assert all(not l.filter_done for l in state.leads)


def test_lead_filter_only_processes_unfiltered(monkeypatch):
    """lead_filter.run() must skip leads already marked filter_done=True."""
    from agents import lead_filter

    state = _make_state(4)
    # Pre-mark 2 leads as already filtered
    state.leads[0].filter_done = True
    state.leads[0].kept = True
    state.leads[1].filter_done = True
    state.leads[1].kept = False
    state.leads[1].reject_reason = "franchise"

    calls = []

    def mock_create(**kwargs):
        batch_items = kwargs["messages"][0]["content"]
        calls.append(batch_items)
        # Return minimal valid JSON for the 2 unfiltered leads
        class FakeContent:
            text = '{"decisions": [{"index": 0, "kept": true, "reason": "ok"}, {"index": 1, "kept": true, "reason": "ok"}]}'
        class FakeResp:
            content = [FakeContent()]
        return FakeResp()

    monkeypatch.setattr("agents.lead_filter.Anthropic", lambda api_key: type("C", (), {"messages": type("M", (), {"create": staticmethod(mock_create)})()})())
    lead_filter.run(state, "fake-key")

    # Only 2 leads were unfiltered — Claude was called once (batch of 2)
    assert len(calls) == 1
    # All 4 leads are now filter_done
    assert all(l.filter_done for l in state.leads)
    # The 2 pre-marked leads are unchanged
    assert state.leads[0].kept is True
    assert state.leads[1].kept is False


def test_lead_filter_noop_when_all_filtered():
    """lead_filter.run() returns immediately when all leads are already filtered."""
    from agents import lead_filter

    state = _make_state(2)
    for l in state.leads:
        l.filter_done = True

    # Should not raise (no Anthropic client constructed)
    lead_filter.run(state, "fake-key")
    # No change
    assert all(l.filter_done for l in state.leads)
```

- [ ] **Step 7.2: Run tests to confirm they fail**

```bash
cd "/Users/daschelgorgenyi/Desktop/Vistaline-Lead Sourcing Agent" && \
python -m pytest tests/test_filter_done_field.py -v 2>&1 | head -25
```

Expected: `AttributeError: Lead has no attribute 'filter_done'` or `ImportError`

---

### Task 8: Add filter_done to Lead and update state.py

**Files:**
- Modify: `state.py` (`Lead` dataclass, `save_leads`, `load`)

- [ ] **Step 8.1: Add filter_done field to Lead dataclass**

In `state.py`, after the `email: str = ""` field (line 44), add:

```python
    filter_done: bool = False   # set to True after lead_filter processes this lead
```

The Lead dataclass block should now read (showing context lines):

```python
    email: str = ""
    # Personalization (post-FindyMail). Empty string means "not run yet".
    x_project: str = ""
    ...
```

becomes:

```python
    email: str = ""
    filter_done: bool = False   # set to True after lead_filter processes this lead
    # Personalization (post-FindyMail). Empty string means "not run yet".
    x_project: str = ""
    ...
```

- [ ] **Step 8.2: Add filter_done to save_leads()**

In `save_leads()`, add `"filter_done": l.filter_done,` to the rows dict, after the `"email"` entry:

```python
                "email": l.email,
                "filter_done": l.filter_done,
                "x_project": l.x_project,
```

- [ ] **Step 8.3: Add filter_done to load()**

In `load()`, add `filter_done=r.get("filter_done", True),` after the `email` entry in the Lead constructor. Using `True` as default means pre-migration rows (which lack the column) are treated as already filtered:

```python
                email=r["email"],
                filter_done=r.get("filter_done", True),
                x_project=r.get("x_project", "") or "",
```

---

### Task 9: Run state tests + filter_done tests

**Files:** (no changes)

- [ ] **Step 9.1: Run existing state tests to check for regressions**

```bash
cd "/Users/daschelgorgenyi/Desktop/Vistaline-Lead Sourcing Agent" && \
python -m pytest tests/test_state_interface.py tests/test_state_toggle_fields.py tests/test_state_personalization_fields.py -v
```

Expected: all pass.

- [ ] **Step 9.2: Run filter_done tests**

```bash
cd "/Users/daschelgorgenyi/Desktop/Vistaline-Lead Sourcing Agent" && \
python -m pytest tests/test_filter_done_field.py::test_lead_filter_done_defaults_false tests/test_filter_done_field.py::test_new_leads_start_as_filter_done_false -v
```

Expected: both pass. (The monkeypatched tests may still fail — fixed in Task 10.)

- [ ] **Step 9.3: Commit**

```bash
git add state.py
git commit -m "feat(state): add filter_done field to Lead for incremental pipeline processing"
```

---

### Task 10: Modify lead_filter.py for incremental processing

**Files:**
- Modify: `agents/lead_filter.py`

- [ ] **Step 10.1: Replace the run() function**

Replace the entire `run()` function (lines 41–103) with:

```python
def run(state: CampaignState, anthropic_key: str, batch_size: int = 25) -> None:
    """Filter leads that have not yet been processed (filter_done=False).

    Idempotent: if all leads are already filtered, returns immediately.
    Designed to be called multiple times in the quota loop — each call
    processes only the new unfiltered leads added since the last call.
    """
    targets = [l for l in state.leads if not l.filter_done]
    if not targets:
        return

    client = Anthropic(api_key=anthropic_key)
    state.info("lead_filter", f"filtering {len(targets)} new leads in batches of {batch_size}")

    for batch_start in range(0, len(targets), batch_size):
        batch = targets[batch_start : batch_start + batch_size]
        items = [
            {
                "index": i,
                "business_name": lead.business_name,
                "phone": lead.phone,
                "area_code": lead.area_code,
                "website": lead.website,
                "address": lead.address,
            }
            for i, lead in enumerate(batch)
        ]

        user_msg = (
            f"Target city: {state.city}, {state.state_abbr}\n"
            f"Niche: {state.niche}\n\n"
            f"Leads to evaluate:\n{json.dumps(items, indent=2)}"
        )

        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )
        text = response.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()

        try:
            parsed = json.loads(text)
            for d in parsed.get("decisions", []):
                local_idx = d.get("index")
                if local_idx is None or local_idx >= len(batch):
                    continue
                lead = batch[local_idx]
                lead.kept = bool(d.get("kept", True))
                lead.reject_reason = d.get("reason", "") if not lead.kept else ""
        except json.JSONDecodeError as e:
            state.info("lead_filter", f"WARN: bad JSON in batch {batch_start}, keeping all", error=str(e))

        # Mark all leads in this batch as processed regardless of JSON parse outcome.
        # Unprocessed leads default to kept=True (set at Lead construction).
        for lead in batch:
            lead.filter_done = True

        kept_in_batch = sum(1 for l in batch if l.kept)
        state.info("lead_filter", f"batch {batch_start}: {kept_in_batch}/{len(batch)} kept")

    total_kept = sum(1 for l in state.leads if l.kept)
    state.info("lead_filter", f"done: {total_kept}/{len(state.leads)} kept overall")
```

- [ ] **Step 10.2: Run all filter_done tests**

```bash
cd "/Users/daschelgorgenyi/Desktop/Vistaline-Lead Sourcing Agent" && \
python -m pytest tests/test_filter_done_field.py -v
```

Expected: all 4 tests pass.

- [ ] **Step 10.3: Run smoke import**

```bash
cd "/Users/daschelgorgenyi/Desktop/Vistaline-Lead Sourcing Agent" && \
python -c "from agents import sourcer, lead_filter, owner_researcher, csv_assembler; print('OK')"
```

Expected: `OK`

- [ ] **Step 10.4: Commit**

```bash
git add agents/lead_filter.py
git commit -m "feat(lead_filter): process only unfiltered leads (filter_done=False), remove single-run guard"
```

---

### Task 11: Modify owner_researcher.py — remove single-run guard

**Files:**
- Modify: `agents/owner_researcher.py` (`run` function only)

The owner researcher already targets `[l for l in state.leads if l.kept and not l.owner_full_name]` — it is naturally incremental. The only change is removing the `is_done` / `mark_done` calls that prevented multi-round use.

- [ ] **Step 11.1: Remove the guard block and mark_done call**

In `agents/owner_researcher.py`, remove lines 120-123:

```python
    if state.is_done("owner_researcher"):
        found = sum(1 for l in state.leads if l.owner_full_name)
        state.info("owner_researcher", f"already complete, skipping ({found} found)")
        return
```

And remove the final `state.mark_done("owner_researcher")` call (currently the last line of `run()`).

The `run()` signature and body otherwise stay identical.

- [ ] **Step 11.2: Verify smoke import**

```bash
cd "/Users/daschelgorgenyi/Desktop/Vistaline-Lead Sourcing Agent" && \
python -c "from agents import owner_researcher; print('OK')"
```

Expected: `OK`

- [ ] **Step 11.3: Commit**

```bash
git add agents/owner_researcher.py
git commit -m "feat(owner_researcher): remove single-run guard — now callable per-round in quota loop"
```

---

### Task 12: Modify sourcer.py for round-based operation

**Files:**
- Modify: `agents/sourcer.py` (`run` function only)

- [ ] **Step 12.1: Replace the run() signature and guards**

Replace the current `run()` function signature and early-return block (lines 245–266):

```python
def run(state: CampaignState, _unused_places_key: str | None = None) -> None:
    ...
    if state.is_done("sourcer"):
        state.info("sourcer", f"already complete, skipping ({len(state.leads)} leads)")
        return
    ...
```

With:

```python
def run(
    state: CampaignState,
    _unused_places_key: str | None = None,
    *,
    round_n: int = 0,
    batch_size: int | None = None,
) -> int:
    """Source contractor leads via Azure Maps + Yelp Fusion in parallel.

    Returns the count of new leads added in this round. Returns 0 if this
    round was already completed (resume case) or if the area is exhausted
    (no unseen leads returned from sources).

    round_n: which sourcing round this is (0-indexed). Step name is
        ``sourcer_round_{round_n}`` so resume works across multiple rounds.
    batch_size: max new leads to add this round. Defaults to state.target_count.
    """
    step = f"sourcer_round_{round_n}"
    if state.is_done(step):
        state.info("sourcer", f"round {round_n} already complete, skipping")
        return 0

    effective_batch = batch_size if batch_size is not None else state.target_count

    state.info(
        "sourcer",
        f"round {round_n} starting",
        target=effective_batch,
        niche=state.niche,
        location=f"{state.city}, {state.state_abbr}",
    )
```

- [ ] **Step 12.2: Replace the lead-append block (step 5 in the original)**

Replace lines 322–328 (the `new_leads: list[dict] = []` block):

```python
    new_leads: list[dict] = []
    for normalized in deduped:
        if len(state.leads) >= state.target_count:
            break
        state.leads.append(_to_lead(normalized))
        new_leads.append(normalized)
```

With:

```python
    new_leads: list[dict] = []
    for normalized in deduped:
        if len(new_leads) >= effective_batch:
            break
        state.leads.append(_to_lead(normalized))
        new_leads.append(normalized)
```

- [ ] **Step 12.3: Replace the final info + mark_done block**

Replace lines 330–338:

```python
    leads_cache.mark_seen(new_leads, state.city, state.state_abbr, state.campaign_id)

    if len(new_leads) < state.target_count:
        state.info(
            "sourcer", "cache filtered short",
            found=len(new_leads), target=state.target_count,
        )

    state.info("sourcer", "done", final_count=len(state.leads))
    state.mark_done("sourcer")
```

With:

```python
    leads_cache.mark_seen(new_leads, state.city, state.state_abbr, state.campaign_id)

    state.info(
        "sourcer",
        f"round {round_n} done",
        new_this_round=len(new_leads),
        total_leads=len(state.leads),
    )
    state.mark_done(step)
    return len(new_leads)
```

- [ ] **Step 12.4: Verify smoke import**

```bash
cd "/Users/daschelgorgenyi/Desktop/Vistaline-Lead Sourcing Agent" && \
python -c "from agents import sourcer; print('OK')"
```

Expected: `OK`

- [ ] **Step 12.5: Commit**

```bash
git add agents/sourcer.py
git commit -m "feat(sourcer): add round_n/batch_size kwargs, return new-lead count for quota loop"
```

---

### Task 13: Replace linear pipeline with quota loop in run.py

**Files:**
- Modify: `run.py`

- [ ] **Step 13.1: Add import and constants**

Add `import math` to the top-level imports.

After the existing imports block, add these module-level constants:

```python
MAX_SOURCING_ROUNDS = 5    # safety cap: prevents runaway spend if area has many businesses
_KEEP_EST = 0.45           # estimated keep rate, used only to size per-round batch
_HIT_EST = 0.65            # estimated owner-name hit rate, used only to size per-round batch


def _named_count(state: CampaignState) -> int:
    """Count leads that passed the filter and have an owner first name."""
    return sum(1 for l in state.leads if l.kept and l.owner_first)


def _leads_per_round(target: int) -> int:
    """Raw leads to source per round so MAX_SOURCING_ROUNDS rounds at expected rates fills quota."""
    return max(50, math.ceil(target / (_KEEP_EST * _HIT_EST) / MAX_SOURCING_ROUNDS * 1.2))
```

- [ ] **Step 13.2: Replace the try block in main()**

Replace the current pipeline block in `main()` (lines 144–178):

```python
    try:
        # 1. Sourcer — Google Places API
        sourcer.run(state, CONFIG.google_places_key)

        # 2. Lead filter — Claude
        lead_filter.run(state, CONFIG.anthropic_key)

        # 3. Owner researcher — Claude + web_search, parallel
        owner_researcher.run(state, CONFIG.anthropic_key)

        # 4. CSV assembler — FindyMail-ready + master
        findymail_path, master_path = csv_assembler.run(state)

        # Persist all leads to Supabase so the web UI can show and export them.
        state.save_leads()

        # Summary stats
        total = len(state.leads)
        kept = sum(1 for l in state.leads if l.kept)
        with_owner = sum(1 for l in state.leads if l.kept and l.owner_first)
        with_email = sum(1 for l in state.leads if l.kept and l.email)
        ready = sum(1 for l in state.leads if l.kept and l.owner_first and l.domain)

        print()
        print("=" * 64)
        print(f"  ✅  DONE — campaign {state.campaign_id}")
        print(f"  scraped:           {total}")
        print(f"  kept after filter: {kept}")
        print(f"  with owner name:   {with_owner}")
        print(f"  with email already: {with_email}  (saved that many FindyMail credits)")
        print(f"  ready for upload:  {ready}")
        print()
        print(f"  upload to FindyMail:  {findymail_path}")
        print(f"  full audit trail:     {master_path}")
        print("=" * 64)
        return 0

    except Exception:
        traceback.print_exc()
        state.status = "failed"
        state.save()
        print()
        print(f"💥  Crashed mid-run. Resume with:")
        print(f"    python run.py --resume {state.campaign_id}")
        return 2
```

With:

```python
    try:
        if state.is_done("pipeline_complete"):
            print("Campaign already completed — nothing to do.")
            return 0

        batch = _leads_per_round(state.target_count)
        state.info("run", f"quota loop: target={state.target_count} named, {batch} raw/round, max {MAX_SOURCING_ROUNDS} rounds")

        for round_n in range(MAX_SOURCING_ROUNDS):
            if not state.is_done(f"sourcer_round_{round_n}"):
                new = sourcer.run(state, CONFIG.google_places_key, round_n=round_n, batch_size=batch)
                if new == 0:
                    state.mark_done("sourcer_exhausted")
                    state.info("run", f"area exhausted after {round_n} sourcing rounds")
                    break

            lead_filter.run(state, CONFIG.anthropic_key)
            owner_researcher.run(state, CONFIG.anthropic_key)

            named = _named_count(state)
            state.info("run", f"round {round_n} complete", named=named, target=state.target_count)

            if named >= state.target_count or state.is_done("sourcer_exhausted"):
                break

        findymail_path, master_path = csv_assembler.run(state)
        state.save_leads()
        state.mark_done("pipeline_complete")
        state.status = "completed"
        state.save()

        total = len(state.leads)
        kept = sum(1 for l in state.leads if l.kept)
        with_owner = _named_count(state)
        with_email = sum(1 for l in state.leads if l.kept and l.email)
        exhausted_note = "  ⚠️  area exhausted before quota met\n" if state.is_done("sourcer_exhausted") else ""

        print()
        print("=" * 64)
        print(f"  ✅  DONE — campaign {state.campaign_id}")
        print(f"  scraped:           {total}")
        print(f"  kept after filter: {kept}")
        print(f"  with owner name:   {with_owner}/{state.target_count} (target)")
        print(f"  with email:        {with_email}  (saved FindyMail credits)")
        if exhausted_note:
            print(exhausted_note, end="")
        print()
        print(f"  upload to FindyMail:  {findymail_path}")
        print(f"  full audit trail:     {master_path}")
        print("=" * 64)
        return 0

    except Exception:
        traceback.print_exc()
        state.status = "failed"
        state.save()
        print()
        print(f"💥  Crashed mid-run. Resume with:")
        print(f"    python run.py --resume {state.campaign_id}")
        return 2
```

- [ ] **Step 13.3: Verify import**

```bash
cd "/Users/daschelgorgenyi/Desktop/Vistaline-Lead Sourcing Agent" && \
python -c "from run import main, _leads_per_round, _named_count; print(_leads_per_round(30))"
```

Expected: a number between 24 and 30.

- [ ] **Step 13.4: Commit**

```bash
git add run.py
git commit -m "feat(run): replace linear pipeline with quota-fulfillment loop — sources until target named leads found or area exhausted"
```

---

### Task 14: Update api/runner.py to use the quota loop

**Files:**
- Modify: `api/runner.py`

- [ ] **Step 14.1: Replace _run_sync**

Replace the entire file contents with:

```python
"""Async wrapper that runs the synchronous quota-fulfillment pipeline in a thread pool."""
from __future__ import annotations
import asyncio
import math

from config import CONFIG
from state import CampaignState
from agents import sourcer, lead_filter, owner_researcher, csv_assembler

MAX_SOURCING_ROUNDS = 5
_KEEP_EST = 0.45
_HIT_EST = 0.65


def _leads_per_round(target: int) -> int:
    return max(50, math.ceil(target / (_KEEP_EST * _HIT_EST) / MAX_SOURCING_ROUNDS * 1.2))


async def run_pipeline(campaign_id: str) -> None:
    """Launch the quota-fulfillment pipeline for campaign_id in a thread (non-blocking)."""
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _run_sync, campaign_id)


def _run_sync(campaign_id: str) -> None:
    state = CampaignState.load(campaign_id)
    try:
        if state.is_done("pipeline_complete"):
            return

        batch = _leads_per_round(state.target_count)
        state.info("runner", f"quota loop: target={state.target_count}, {batch} raw/round")

        for round_n in range(MAX_SOURCING_ROUNDS):
            if not state.is_done(f"sourcer_round_{round_n}"):
                new = sourcer.run(state, CONFIG.google_places_key, round_n=round_n, batch_size=batch)
                if new == 0:
                    state.mark_done("sourcer_exhausted")
                    state.info("runner", f"area exhausted after {round_n} rounds")
                    break

            lead_filter.run(state, CONFIG.anthropic_key)
            owner_researcher.run(state, CONFIG.anthropic_key)

            named = sum(1 for l in state.leads if l.kept and l.owner_first)
            state.info("runner", f"round {round_n} done", named=named, target=state.target_count)

            if named >= state.target_count or state.is_done("sourcer_exhausted"):
                break

        csv_assembler.run(state)
        state.save_leads()
        state.mark_done("pipeline_complete")
        state.status = "completed"
        state.save()
    except Exception as exc:
        state.status = "failed"
        state.info("runner", f"Pipeline failed: {exc}", level="error")
        state.save()
        raise
```

- [ ] **Step 14.2: Verify import**

```bash
cd "/Users/daschelgorgenyi/Desktop/Vistaline-Lead Sourcing Agent" && \
python -c "from api.runner import run_pipeline; print('OK')"
```

Expected: `OK`

- [ ] **Step 14.3: Commit**

```bash
git add api/runner.py
git commit -m "feat(api/runner): mirror quota-fulfillment loop from run.py"
```

---

### Task 15: Smoke import test — all agents

**Files:** (no changes)

- [ ] **Step 15.1: Run the standard smoke import**

```bash
cd "/Users/daschelgorgenyi/Desktop/Vistaline-Lead Sourcing Agent" && \
python -c "from agents import sourcer, lead_filter, owner_researcher, csv_assembler; print('OK')"
```

Expected: `OK`

- [ ] **Step 15.2: Run all pure-Python tests**

```bash
cd "/Users/daschelgorgenyi/Desktop/Vistaline-Lead Sourcing Agent" && \
python -m pytest tests/test_cost_estimator.py tests/test_filter_done_field.py tests/test_state_interface.py tests/test_leads_cache.py -v
```

Expected: all pass.

---

### Task 16: End-to-end smoke run (real APIs, small count)

**Files:** (no changes)

- [ ] **Step 16.1: Run a 5-lead smoke test**

```bash
cd "/Users/daschelgorgenyi/Desktop/Vistaline-Lead Sourcing Agent" && \
python run.py --city "Orlando" --state FL --count 5
```

Watch for:
- Banner shows `est. raw` and `cost` lines
- `[run] quota loop: target=5` in output
- `[sourcer] round 0 starting` (not the old `[sourcer] starting`)
- At least one `[run] round 0 complete` line with `named=X/5`
- `✅  DONE` summary showing `with owner name: X/5 (target)`

If named count < 5 and area is NOT exhausted, a second round should trigger automatically.

- [ ] **Step 16.2: Inspect the output CSVs**

Verify the master CSV has the `filter_done` column. (It won't appear in the CSV — it's an internal pipeline field only written to Supabase, not the output CSVs. Confirm no KeyError in the assembler.)

- [ ] **Step 16.3: Final commit**

No code changes needed. If any bugs surfaced during the smoke run, fix them and commit with `fix: ...` prefix before this step.

---

## Self-Review

### Spec coverage check

| Requirement | Task |
|-------------|------|
| Cost projection — Anthropic API credits | Tasks 1-3 |
| Cost shown before run in CLI | Task 5 |
| Cost exposed via API | Task 4 |
| Keep sourcing until target named-lead count | Tasks 12-14 |
| Use historical data from previous runs | Handled by existing `leads_cache.db` — `filter_unseen()` is called inside `sourcer.run()` each round |
| Return what it found if area exhausted | Task 13 — `sourcer_exhausted` flag + warning in summary |
| Leads without names visible for audit | Already in master CSV — unchanged |

### Placeholder scan

No TBD, TODO, or "similar to Task N" entries. All code blocks are complete.

### Type consistency

- `sourcer.run()` now returns `int` (new-lead count); callers check `new == 0` for exhaustion.
- `lead_filter.run()` return type stays `None`.
- `owner_researcher.run()` return type stays `None`.
- `filter_done: bool` is used consistently in `Lead`, `save_leads()`, `load()`, and `lead_filter.run()`.
- Step name `f"sourcer_round_{round_n}"` is used in `sourcer.run()`, `run.py`, and `api/runner.py`.
- `"sourcer_exhausted"` and `"pipeline_complete"` are the two new sentinel step names; both spelled identically across all files.
