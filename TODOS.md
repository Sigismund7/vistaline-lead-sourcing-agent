# Vistaline TODOs

Pending work, ordered by what's blocking what.

## Now (action required)

- [ ] **Vercel re-deploy.** Two frontend commits on `main` (`c37556e` mobile table scroll, `cc687ec` logout redirect) landed after the last deploy and aren't live. Run `cd frontend && npx vercel --prod --yes`.
- [ ] **BBB compare-mode analysis & winner lock-in** (queued after Phase 0 reshape ships). After 3 campaigns run with `bbb_compare_mode=True`, analyze the master CSVs to pick between `bbb_direct` and `bbb_websearch`.
  - **Why:** compare mode burns ~$0.49 extra per campaign in Claude web_search calls. Must not stay on indefinitely.
  - **Where the data is:** `output/*master.csv` columns `bbb_direct_name`, `bbb_direct_url`, `bbb_websearch_name`, `bbb_websearch_url`, `bbb_conflict`.
  - **Decision rule:** direct hit rate ≥ websearch → keep direct, delete `bbb_websearch.py`. Websearch wins by >40% → swap to websearch as Phase 0. Both lose narrowly to today's Phase 3 BBB strategy → revert entire Phase 0 reshape.
  - **Action:** one-off analysis script (not committed), flip `bbb_compare_mode = False`, delete losing module, update `CLAUDE.md`.
  - **Depends on:** 3 compare-mode campaigns committed to main and run.

## In flight (branches needing attention)

- [ ] **Prune dead branches.** `mvp-backend-and-wiring`, `phase0-azure-stack`, `phase0-brave-stack`, `phase0-sourcer-router`, `phase0-yelp-stack`, `phase1-frontend-skeleton`, `tightening`, `yelp-owner-profile` (merged 2026-05-07) — review and delete if dead.

## Specced, not built

- [ ] **Pipeline self-tuning loops** — `docs/superpowers/specs/2026-05-07-pipeline-self-tuning-design.md`
  - Loop A: per-niche keyword scoring in sourcer
  - Loop B: per-niche phase ordering in owner researcher (highest cost-savings, build first) — now unblocked (`yelp-owner-profile` merged 2026-05-07). Likely subsumed/redirected by the BBB Phase 0 reshape currently in design; revisit after compare-mode winner is locked in.
  - Loop C: filter few-shot exemplar injection (A/B test before committing)
  - Build order: B → A → C.
- [ ] **Lead stage tracking** — `docs/superpowers/specs/2026-05-04-lead-stage-tracking-design.md` (researched → exported → processed). Unblocks "don't re-export the same lead twice" workflows.
- [ ] **Target qualified leads pipeline loop — frontend half** — `docs/superpowers/specs/2026-05-04-target-qualified-leads-design.md`. Backend quota loop landed on `main`; UI to expose "find me 50 qualified, however many rounds it takes" still pending.

## Verify when data exists

- [ ] **End-to-end personalization upload test.** Feature shipped, but needs a real FindyMail-returned CSV with emails to verify the full flow: upload → match by domain → personalize → agency CSV download.
