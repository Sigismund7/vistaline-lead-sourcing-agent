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
import sys
import traceback

from config import CONFIG
from state import CampaignState
from agents import sourcer, lead_filter, owner_researcher, csv_assembler


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Vistaline lead-gen sourcer")
    p.add_argument("--city", help='Target city, e.g. "Orlando"')
    p.add_argument("--state", help='State abbreviation, e.g. "FL"')
    p.add_argument("--count", type=int, default=50, help="Lead count target (default: 50)")
    p.add_argument("--niche", default=None, help='Niche, e.g. "kitchen remodeling"')
    p.add_argument("--triggered-by", default="DG", help='Who launched this run (default: DG)')
    p.add_argument("--resume", default=None, help="Resume by campaign ID")
    return p.parse_args()


def banner(state: CampaignState) -> None:
    print()
    print("┌" + "─" * 58 + "┐")
    print(f"│  Vistaline Lead-Gen — {state.campaign_id:<33}│")
    print(f"│  city:   {state.city + ', ' + state.state_abbr:<48}│")
    print(f"│  niche:  {state.niche:<48}│")
    print(f"│  target: {state.target_count:<48}│")
    print("└" + "─" * 58 + "┘")


def main() -> int:
    args = parse_args()

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


if __name__ == "__main__":
    sys.exit(main())
