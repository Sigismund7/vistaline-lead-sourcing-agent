# Plan: Sourcing Tool Tightening v1

**Source-of-truth design doc:** `docs/office-hours-renovation.md`
**Status:** APPROVED (2026-05-02)
**Scope:** Sourcing pipeline only. Tool stops at FindyMail-ready CSV. Operator workflow downstream of that (Instantly variants, PRR tracking, decision gate) is explicitly out of scope.

## Locked Constraints

These are non-negotiable. Tasks that violate any of these must STOP and escalate:

1. Premises 1–5 from the design doc.
2. Approach A only (no Approach B/C work).
3. Files in Scope list (design doc, "Files in Scope for Approach A" section).
4. `run.py` stays deterministic Python — no LLM-decision logic, no agentic branching.
5. PRR threshold default: 2% (operator-side concern, not relevant to engineering tasks).
6. No new paid surfaces. Current: Anthropic API, Google Places API. A third requires founder approval before any task is generated.
7. Companion PRR-outreach to operator network is human-only — never a Superpowers task.

## Cross-Cutting Rules (every task, every phase)

- Files touched must be a subset of in-scope-modifiable list.
- `run.py` modifications limited to bug fixes on existing CLI surface.
- TDD on every Phase 2 source change: failing test → implement → green test.
- Code review subagent passes before merge.
- Worktree branch per Phase 2 task; merge after review.
- Smoke findings → Phase 2 tasks is 1:1. No fixes for hypothetical issues.
- Cost-discipline check before generating any task: would this fix add a new external API/library/service requiring payment? If yes → STOP and escalate.

## Division of Labor

- **Claude executes:** all code-running, file-writing, git operations, test scaffolding, source modifications.
- **Operator (human) executes:** browser-based spot-checks of website + BBB per row (Tasks 1.2, 1.4, 3.1 verification half), Day 0 Instantly tier check (operator-side, out of plan scope), companion PRR outreach (out of plan scope).

---

## PHASE 0 — Prerequisites

### Task 0.1 — Verify environment is runnable

- Confirm `.env` exists with required keys (Google Places, Anthropic at minimum). If missing → STOP and ask operator.
- Confirm dependencies installed: `pip install -r requirements.txt` (in active venv).
- Run a smoke import: `python -c "from agents import sourcer, lead_filter, owner_researcher, csv_assembler; print('OK')"`. Must print OK.
- No code changes in this task.

### Task 0.2 — Scaffold `tests/` directory

- Create `tests/` with an `__init__.py` (empty) so pytest/unittest can discover it later.
- Add a placeholder `tests/test_smoke.py`:
  ```python
  """Placeholder — real tests added in Phase 2 per finding."""
  def test_imports():
      from agents import sourcer, lead_filter, owner_researcher, csv_assembler
      assert sourcer and lead_filter and owner_researcher and csv_assembler
  ```
- Verify: `python -m pytest tests/ -q` passes (or `python -m unittest discover tests/` if pytest not available).

### Task 0.3 — Confirm git is initialized with sane `.gitignore`

- Verify `.git/` exists at project root. If not → `git init`.
- Verify `.gitignore` includes at minimum: `.env`, `__pycache__/`, `*.pyc`, `output/`, `state/`, `.venv/`, `venv/`, `.DS_Store`.
- Initial commit (if not yet made) of the existing source.

---

## PHASE 1 — Smoke Test (Day 1–2)

**Goal:** Generate a real-world failure list. No source changes in this phase.

### Task 1.1 — Execute count=5 smoke run

- Command: `python run.py --city "Orlando" --state FL --count 5`
- Capture: stdout/stderr to `output/smoke-5-stdout.log`; the master CSV path; any state files in `state/`.
- If the run crashes before producing a master CSV: the crash message becomes the first finding. Do not iterate.

### Task 1.2 — Operator spot-check protocol on count=5 (HUMAN)

- For each of the 5 rows, operator opens website URL + BBB listing in browser.
- Records per row: owner-name accuracy (YES/NO/partial), email accuracy (YES/NO/partial), notes.
- Output: scratch notes to be folded into Task 1.4's deliverable. NOT yet written to `docs/smoke-orlando-20.md`.

### Task 1.3 — Resume contract verification on count=20

- Start: `python run.py --city "Orlando" --state FL --count 20` in the background.
- Wait until at least 5 leads are written to state (poll `state/` dir).
- Send `SIGINT` to the process.
- Capture campaign-id from state.
- Resume: `python run.py --resume <campaign-id>`.
- Verify: (a) resume continues from prior position, not from scratch; (b) no duplicate rows in final master CSV; (c) run completes to count=20.
- If resume fails or duplicates: record as finding with `state.py` as suspected file. Do NOT fix here.

### Task 1.4 — Spot-check count=20 + write findings (HUMAN spot-check, Claude writes findings file)

- Operator: apply per-row protocol from 1.2 to all 20 rows.
- Claude: tally failure categories: `name-wrong`, `email-wrong`, `email-missing`, `name-missing`, `js-rendered-page` (HTTP+BS4 returned <500 chars OR text contained zero owner-page keywords AND a manual browser visit confirms the page renders correctly), `bbb-rate-limited`, `bbb-no-record`, `findymail-column-malformed`, `crash-or-exception`, `other`.
- Claude: write `docs/smoke-orlando-20.md`:
  - Header: total rows, accurate-owner-name count (target ≥16/20 = 80%), Phase 1 hit-rate (target ≥40%), resume contract verdict (PASS/FAIL).
  - Body: one line per failure, format `<symptom> | <suspected file> | <fix sketch> | <count>`, grouped by symptom, sorted by frequency desc.

**Phase 1 deliverables:** `docs/smoke-orlando-20.md`, `output/smoke-5-stdout.log`, count=20 master CSV.

**Phase 1 → Phase 2 gate:** `docs/smoke-orlando-20.md` exists with header populated. If zero failures and resume contract holds, Phase 2 is empty; jump to Phase 3.

---

## PHASE 2 — Tightening (Day 3–5, conditional)

**Goal:** Fix every reproducible failure in `docs/smoke-orlando-20.md`, frequency-ordered. No speculative fixes.

### Task generation rule (executor applies)

For each unique row in `docs/smoke-orlando-20.md`:
- Title: `tightening: <symptom>`
- Worktree branch: `tightening/<short-symptom-slug>`
- TDD: write failing test in `tests/` first → implement fix → green test.
- Files touched: must subset in-scope-modifiable list. If fix requires out-of-scope file → STOP, escalate.
- Code review subagent pass before merge.
- Order: most-frequent finding first.

### Conditional sub-block 2.PW — Playwright fallback (gated)

**Trigger:** `js-rendered-page` finding count ≥ `0.30 * total_findings`.

If triggered:
- Task 2.PW-1: Add `playwright` to `requirements.txt`. Cost-discipline check: Playwright is open-source, no new paid surface — proceed.
- Task 2.PW-2: Implement fallback in `agents/website_crawler.py` — invoked only when HTTP+BS4 returns the JS-rendered-page signature. Default off via `config.py` flag `WEBSITE_CRAWLER_PLAYWRIGHT_ENABLED = False` initially, flipped on in this same task.
- Task 2.PW-3: TDD test with a fixture URL captured from Phase 1.
- Timeline: extend Phase 2 budget by ~2 days (~4–5 days total).

If NOT triggered: write to `docs/smoke-orlando-20.md` "Deferred to v2" section: `Playwright fallback: deferred — only X% of findings were JS-rendering, threshold is 30%.`

### Conditional sub-block 2.AD — Adaptability hooks (each gated independently)

Each hook is generated **only if** smoke surfaces the underlying problem. Pure agent-level threshold logic — never `run.py`.

**2.AD-1: Sourcer overflow early-exit (`agents/sourcer.py`)**
- Trigger: smoke output shows sourcer produced more than `target * 1.3` candidate businesses before downstream filtering AND wasted Google Places calls >5 in count=20.
- Implementation: threshold check using `SOURCER_OVERFLOW_FACTOR = 1.3` from `config.py`. Early-exit when buffer exceeds.
- TDD: test confirms early-exit fires at `target * 1.3 + 1`.
- If NOT triggered: document as deferred, no task.

**2.AD-2: Owner-researcher Phase 2 cap (`agents/owner_researcher.py`)**
- Trigger: smoke output shows Phase 1 hit rate <30% on first 20% of leads (4 of 20), causing Phase 2 fall-through inflation.
- Implementation: after first 20% of batch processed, if Phase 1 hit rate < `OWNER_RESEARCHER_PHASE1_FLOOR = 0.30`, log warning AND cap remaining Phase 2 calls at `OWNER_RESEARCHER_PHASE2_BUDGET` from `config.py`.
- TDD: test confirms cap engages when hit-rate floor crossed.
- If NOT triggered: document as deferred.

**2.AD-3: Lead-filter market-quality warning (`agents/lead_filter.py`)**
- Trigger: smoke shows >75% of count=20 leads filtered as franchise/junk.
- Implementation: emit warning (logged + appended to master CSV header comment) when junk ratio exceeds `LEAD_FILTER_JUNK_CEILING = 0.75` from `config.py`. Does NOT halt the run.
- TDD: test confirms warning fires at 76% junk.
- If NOT triggered: document as deferred.

### Cost-discipline gate (every Phase 2 task)

Before generating any task, executor confirms: does the proposed fix introduce a new external API call, paid library, or paid service not already in the dependency surface (Anthropic, Google Places, plus open-source deps in `requirements.txt`)? If yes → STOP and escalate.

**Phase 2 deliverables:** merged tightening branches, new tests under `tests/`, updated `docs/smoke-orlando-20.md` with status column (`fixed`/`deferred`/`escalated`), updated `config.py` with new threshold constants.

**Phase 2 → Phase 3 gate:** all findings ranked frequency ≥2 are merged. Playwright decision documented. Adaptability hooks documented.

---

## PHASE 3 — Validation (Day 6–7)

**Goal:** Confirm the tightening fixes hold at scale. Tool delivers a clean FindyMail-ready CSV; that is the deliverable.

### Task 3.1 — Validation run at count=50 + spot-check

- Command: `python run.py --city "Orlando" --state FL --count 50`. Capture stdout to `output/validation-50-stdout.log`.
- Generate spot-check sample (Claude executes): write `scripts/sample_check.py` (in-scope as a tests-adjacent utility, NOT a new agent):
  ```python
  import random
  random.seed(42)
  print(sorted(random.sample(range(50), 20)))
  ```
- Operator: applies per-row spot-check protocol to those 20 rows.
- Pass criterion: ≥16/20 (80%) accurate owner-name AND Phase 1 hit-rate ≥40% on the full 50-row sample.
- If fail: STOP. Generate Phase 2.5 follow-up task list from validation failures; re-validate before 3.2. Do NOT run count=500 with sub-80% accuracy.

### Task 3.2 — Production run at count=500

- Command: `python run.py --city "Orlando" --state FL --count 500`. Time the run end-to-end.
- Confirm Success Criteria timing: <2 hours compute + <1 hour operator review.
- If compute exceeds 2 hours: log a finding for follow-up but do NOT block — operator gets the CSV.
- Output: 500-lead FindyMail-ready CSV in `output/`. **This is the tool's terminal deliverable.**

### Task 3.3 — Hand-off

- Print the full path of the FindyMail CSV to stdout.
- Print summary: total leads, Phase 1 hit rate, sourcing time (compute), files modified during tightening (Phase 2 git log summary).
- Tool's job is done. Operator-side workflow (Instantly upload, variant configuration, PRR tracking, decision gate) is out of scope for this plan.

**Phase 3 deliverables:** `output/validation-50-stdout.log`, `output/<production-batch-500>.csv`, `scripts/sample_check.py`, summary printed to stdout.

---

## Plan-level success criteria

- All Phase 1 deliverables exist and `docs/smoke-orlando-20.md` is populated.
- All Phase 2 finding-derived tasks (frequency ≥2) merged with green tests.
- Phase 3 validation run passes ≥16/20 spot-check + ≥40% Phase 1 hit-rate.
- Phase 3 production CSV exists at production size with timing budget honored.
- No out-of-scope file was modified.
- No new paid surface was introduced.
- `run.py` did not gain LLM-decision logic.

## Open questions before execution starts

1. Subagent-driven-development skill upgrade? (executing-plans was invoked; subagent-driven is recommended by the skill itself for higher quality)
2. Confirm operator handles Tasks 1.2, 1.4 (visual half), 3.1 (visual half)? Default assumption: yes.
3. Phase 2.5 escalation path if validation fails: same flow as Phase 2 (one task per finding) or different?
