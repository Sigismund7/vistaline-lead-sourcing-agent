"""Lead Filter — runs every lead through Claude with the SOP filter rules.

Pure LLM, no external tools. Batches of 25 to keep prompts focused.
"""
from __future__ import annotations
import json
from anthropic import Anthropic

from state import CampaignState


SYSTEM_PROMPT = """You are a lead qualification specialist for a remodeling-contractor cold email campaign.

Apply these filter rules from the SOP. For each lead, decide KEEP or REJECT.

REJECT if any of these apply:
- National franchise: Re-Bath, Bath Fitter, Bath Planet, Power Home Remodeling, Renuity, or any other national brand.
- Phone is a 1-800 / 1-888 / 1-877 / 1-866 number (toll-free indicates franchise or call center).
- Area code does not match the target city's metro area (use general US area code knowledge).
- Single-service supplier: shower doors only, tile supply, flooring wholesale, countertop slab yard.
- Handyman / general handyman service.
- Retail chain or big-box reference (Home Depot, Lowe's listings).
- Lead-generation directory (Angi, Thumbtack, Yelp directory entries).
- No real website (only a Facebook page, Instagram link, or Google Business listing).

KEEP if:
- Independent owner-operated remodeling contractor.
- Kitchen and bath specialty company.
- General remodeling company with a local phone and a working website.

Respond with valid JSON only — no markdown, no commentary. Format:
{
  "decisions": [
    {"index": 0, "kept": true, "reason": "independent kitchen/bath company"},
    {"index": 1, "kept": false, "reason": "1-800 number, franchise pattern"}
  ]
}
"""


def run(state: CampaignState, anthropic_key: str, batch_size: int = 25) -> None:
    """Filter leads that have not yet been processed (filter_done=False).

    Idempotent: if all leads are already filtered, returns immediately.
    Designed to be called multiple times in the quota loop — each call
    processes only the new unfiltered leads added since the last call.
    """
    targets = [l for l in state.leads if not l.filter_done]
    if not targets:
        return

    # max_retries=10 so the SDK rides out 429s by honoring retry-after.
    # Org input-tokens-per-minute cap (30k) can be hit when owner_researcher's
    # parallel phase calls land in the same window as a lead_filter batch.
    client = Anthropic(api_key=anthropic_key, max_retries=10)
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
        # Unprocessed leads remain at their default kept=True.
        for lead in batch:
            lead.filter_done = True

        kept_in_batch = sum(1 for l in batch if l.kept)
        state.info("lead_filter", f"batch {batch_start}: {kept_in_batch}/{len(batch)} kept")

    total_kept = sum(1 for l in state.leads if l.kept)
    state.info("lead_filter", f"done: {total_kept}/{len(state.leads)} kept overall")
