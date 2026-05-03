"""CSV Assembler — produces two CSVs at the end of the run.

1. <city>_<state>_<niche>_<date>__findymail.csv
   The 4-column FindyMail bulk upload format (per SOP step 7):
       First Name, Last Name, Company, Domain
   Filtered to leads that have BOTH first name AND domain. These are the
   leads that have a real chance of being enriched.

2. <city>_<state>_<niche>_<date>__master.csv
   Everything captured — kept and rejected, with all fields. Useful for
   audit, for the VA's reference, and for any manual fallback work on
   leads that didn't have an owner found.
"""
from __future__ import annotations
import csv
from pathlib import Path
from datetime import date

from state import CampaignState


OUT_DIR = Path(__file__).parent.parent / "output"
OUT_DIR.mkdir(exist_ok=True)


FINDYMAIL_COLUMNS = ["First Name", "Last Name", "Company", "Domain"]

MASTER_COLUMNS = [
    "kept", "reject_reason",
    "business_name", "phone", "area_code", "website", "domain", "address",
    "owner_full_name", "owner_first", "owner_last", "owner_source",
    "email",
    "x_project", "y_detail", "y_source",
    "linkedin_url", "linkedin_source",
    "personalization_status",
    "place_id",
]


def run(state: CampaignState) -> tuple[str, str]:
    """Writes both CSVs. Returns (findymail_path, master_path)."""
    safe_city = state.city.replace(" ", "_").replace(",", "")
    safe_niche = state.niche.replace(" ", "_")
    base = f"{safe_city}_{state.state_abbr}_{safe_niche}_{date.today().isoformat()}"

    # FindyMail-ready CSV
    findymail_ready = [
        l for l in state.leads
        if l.kept and l.owner_first and l.domain
    ]
    findymail_path = OUT_DIR / f"{base}__findymail.csv"
    with findymail_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FINDYMAIL_COLUMNS)
        w.writeheader()
        for lead in findymail_ready:
            w.writerow({
                "First Name": lead.owner_first,
                "Last Name": lead.owner_last,
                "Company": lead.business_name,
                "Domain": lead.domain,
            })

    # Master CSV — everything we captured
    master_path = OUT_DIR / f"{base}__master.csv"
    with master_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=MASTER_COLUMNS)
        w.writeheader()
        for lead in state.leads:
            w.writerow({
                "kept": lead.kept,
                "reject_reason": lead.reject_reason,
                "business_name": lead.business_name,
                "phone": lead.phone,
                "area_code": lead.area_code,
                "website": lead.website,
                "domain": lead.domain,
                "address": lead.address,
                "owner_full_name": lead.owner_full_name,
                "owner_first": lead.owner_first,
                "owner_last": lead.owner_last,
                "owner_source": lead.owner_source,
                "email": lead.email,
                "x_project": lead.x_project,
                "y_detail": lead.y_detail,
                "y_source": lead.y_source,
                "linkedin_url": lead.linkedin_url,
                "linkedin_source": lead.linkedin_source,
                "personalization_status": lead.personalization_status,
                "place_id": lead.place_id,
            })

    state.info("csv_assembler", f"wrote FindyMail CSV ({len(findymail_ready)} rows): {findymail_path}")
    state.info("csv_assembler", f"wrote master CSV ({len(state.leads)} rows): {master_path}")
    state.mark_done("csv_assembler")
    return str(findymail_path), str(master_path)
