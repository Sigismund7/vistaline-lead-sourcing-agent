# Vistaline TODOs

Pending work, ordered by what's blocking what.

## Now (action required)

- [ ] **Upgrade OpenCorporates to paid tier.** Free tier caps at 50 lookups/day; campaigns >50 leads silently fall through to paid `web_search`. Sign up at opencorporates.com/api_accounts/new, set `OPENCORPORATES_API_KEY` in Railway env + `frontend/.env.local`. Committed to 2026-05-05; still open.
- [ ] **Vercel re-deploy.** Two frontend commits on `main` (`c37556e` mobile table scroll, `cc687ec` logout redirect) landed after the last deploy and aren't live. Run `cd frontend && npx vercel --prod --yes`.

## In flight (branches needing attention)

- [ ] **Merge `yelp-owner-profile` to `main`.** Substantial unmerged work: Yelp Phase 0 owner lookup, personalization upload backend, runner quota loop, CSV unification. Needs Supabase migration `ALTER TABLE leads ADD COLUMN IF NOT EXISTS yelp_id TEXT NOT NULL DEFAULT ''`, smoke campaign run, conflict resolution. Longer it sits, harder it gets.
- [ ] **Prune dead branches.** `mvp-backend-and-wiring`, `phase0-azure-stack`, `phase0-brave-stack`, `phase0-sourcer-router`, `phase0-yelp-stack`, `phase1-frontend-skeleton`, `tightening` — review and delete if dead.

## Specced, not built

- [ ] **Pipeline self-tuning loops** — `docs/superpowers/specs/2026-05-07-pipeline-self-tuning-design.md`
  - Loop A: per-niche keyword scoring in sourcer
  - Loop B: per-niche phase ordering in owner researcher (highest cost-savings, build first)
  - Loop C: filter few-shot exemplar injection (A/B test before committing)
  - Build order: B → A → C. Loop B blocked on `yelp-owner-profile` merge.
- [ ] **Lead stage tracking** — `docs/superpowers/specs/2026-05-04-lead-stage-tracking-design.md` (researched → exported → processed). Unblocks "don't re-export the same lead twice" workflows.
- [ ] **Target qualified leads pipeline loop — frontend half** — `docs/superpowers/specs/2026-05-04-target-qualified-leads-design.md`. Backend quota loop landed on `main`; UI to expose "find me 50 qualified, however many rounds it takes" still pending.

## Verify when data exists

- [ ] **End-to-end personalization upload test.** Feature shipped, but needs a real FindyMail-returned CSV with emails to verify the full flow: upload → match by domain → personalize → agency CSV download.
