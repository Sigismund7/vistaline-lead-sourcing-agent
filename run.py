"""Vistaline Lead-Gen Sourcer.

Produces a FindyMail-ready leads CSV for a single city. You supply the city,
state, and lead count from the command line.

Usage:
    python run.py --city "Orlando" --state FL
    python run.py --city "Tampa" --state FL --count 75
    python run.py --city "Austin" --state TX --niche "kitchen remodeling"
    python run.py --resume 20260502-034512-a1b2c3
"""
from __future__ import annotations
import argparse
import math
import sys
import traceback

from config import CONFIG
from state import CampaignState
from agents import sourcer, lead_filter, owner_researcher, csv_assembler


MAX_SOURCING_ROUNDS = 5    # safety cap — prevents runaway spend if area has many businesses
_KEEP_EST = 0.45           # estimated keep rate, used only to size per-round batch
_HIT_EST = 0.65            # estimated owner-name hit rate, used only to size per-round batch


def _named_count(state: CampaignState) -> int:
    """Count leads that passed the filter and have an owner first name."""
    return sum(1 for l in state.leads if l.kept and l.owner_first)


def _leads_per_round(target: int) -> int:
    """Raw leads to source per round so MAX_SOURCING_ROUNDS rounds at expected rates fills quota."""
    return max(50, math.ceil(target / (_KEEP_EST * _HIT_EST) / MAX_SOURCING_ROUNDS * 1.2))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Vistaline lead-gen sourcer")
    p.add_argument("--city", help='Target city, e.g. "Orlando"')
    p.add_argument("--state", help='State abbreviation, e.g. "FL"')
    p.add_argument("--count", type=int, default=50, help="Lead count target (default: 50)")
    p.add_argument("--niche", default=None, help='Niche, e.g. "kitchen remodeling"')
    p.add_argument("--triggered-by", default="DG", help='Who launched this run (default: DG)')
    p.add_argument("--resume", default=None, help="Resume by campaign ID")
    p.add_argument(
        "--personalize",
        default=None,
        metavar="ENRICHED_CSV",
        help="Path to a FindyMail-returned CSV; runs personalizer + linkedin_finder, "
             "writes final agency CSV to output/.",
    )
    p.add_argument(
        "--triggered-by-name",
        default=None,
        help="(Personalize mode only) the Lead Sourcer name to write into the agency CSV.",
    )
    return p.parse_args()


def run_personalize(enriched_csv: str, *, triggered_by: str) -> int:
    """End-to-end post-FindyMail flow: read enriched CSV -> personalizer ->
    linkedin finder -> write final agency CSV.
    """
    from pathlib import Path
    from agents import personalizer, linkedin_finder
    from agents.csv_agency import read_enriched, write_agency

    state = read_enriched(enriched_csv)
    state.triggered_by = triggered_by or "DG"
    state.status = "personalizing"
    state.save()

    print()
    print(f"Personalize mode: {state.campaign_id}")
    print(f"  enriched CSV:       {enriched_csv}")
    print(f"  leads:              {len(state.leads)}")
    print(f"  with email:         {sum(1 for l in state.leads if l.email)}")
    print()

    try:
        personalizer.run(
            state,
            CONFIG.anthropic_key,
            yelp_key=CONFIG.yelp_fusion_key,
            model=CONFIG.personalizer_vision_model,
            max_parallel=CONFIG.personalizer_max_parallel,
            timeout_s=CONFIG.personalizer_screenshot_timeout_s,
        )
        linkedin_finder.run(
            state,
            CONFIG.anthropic_key,
            max_parallel=CONFIG.personalizer_max_parallel,
        )

        out_dir = Path(__file__).parent / "output"
        out_dir.mkdir(exist_ok=True)
        agency_path = out_dir / f"{state.campaign_id}__agency.csv"
        write_agency(state, agency_path, lead_sourcer=triggered_by)

        state.save_leads()
        state.status = "completed"
        state.save()

        ok = sum(1 for l in state.leads if l.personalization_status == "ok")
        with_li = sum(1 for l in state.leads if l.linkedin_url)
        print()
        print("=" * 64)
        print(f"  ✅ Personalization done — campaign {state.campaign_id}")
        print(f"  X/Y filled:        {ok}/{len(state.leads)}")
        print(f"  LinkedIn found:    {with_li}/{len(state.leads)}")
        print(f"  agency CSV:        {agency_path}")
        print("=" * 64)
        return 0
    except Exception:
        traceback.print_exc()
        state.status = "failed"
        state.save()
        return 2


def banner(state: CampaignState) -> None:
    from agents.cost_estimator import estimate as _estimate
    est = _estimate(target_named=state.target_count)
    raw_str = f"~{est.estimated_raw_to_source} businesses"
    cost_str = f"~${est.total_usd:.2f} (Anthropic API est.)"
    print()
    print("┌" + "─" * 58 + "┐")
    print(f"│  Vistaline Lead-Gen — {state.campaign_id:<35}│")
    print(f"│  city:   {state.city + ', ' + state.state_abbr:<48}│")
    print(f"│  niche:  {state.niche:<48}│")
    print(f"│  target: {str(state.target_count) + ' leads with owner names':<48}│")
    print(f"│  raw:    {raw_str:<48}│")
    print(f"│  cost:   {cost_str:<48}│")
    print("└" + "─" * 58 + "┘")


def main() -> int:
    args = parse_args()

    if args.personalize:
        return run_personalize(
            args.personalize,
            triggered_by=args.triggered_by_name or args.triggered_by,
        )

    if args.resume:
        state = CampaignState.load(args.resume)
        print(f"Resuming campaign {state.campaign_id}")
    else:
        if not args.city or not args.state:
            print("ERROR: --city and --state are required for a new run.")
            print("       (Or use --resume <campaign-id> to continue a stopped run.)")
            return 1
        state = CampaignState.new()
        state.city = args.city
        state.state_abbr = args.state.upper()
        state.niche = args.niche or CONFIG.default_niche
        state.target_count = args.count
        state.triggered_by = args.triggered_by
        print(f"New campaign: {state.campaign_id}")

    state.save()
    banner(state)

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
        exhausted_note = "  area exhausted before quota met\n" if state.is_done("sourcer_exhausted") else ""

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


if __name__ == "__main__":
    sys.exit(main())
