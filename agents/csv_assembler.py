"""CSV Assembler — produces two CSVs at the end of the run.

Both CSVs share the same column schema. The difference is row filtering:

1. <city>_<state>_<niche>_<date>__findymail.csv
   Kept leads where both owner_first AND owner_last are known — the set
   ready for FindyMail bulk upload. Same columns as master.

2. <city>_<state>_<niche>_<date>__master.csv
   Every lead captured, kept or rejected, with all fields. Audit trail
   and fallback reference for leads without a confirmed owner name.
"""
from __future__ import annotations
import csv
from pathlib import Path
from datetime import date

from state import CampaignState


OUT_DIR = Path(__file__).parent.parent / "output"
OUT_DIR.mkdir(exist_ok=True)


COLUMNS = [
    "kept", "reject_reason",
    "business_name", "phone", "area_code", "website", "domain", "address",
    "owner_full_name", "owner_first", "owner_last", "owner_source",
    "email",
    "x_project", "y_detail", "y_source",
    "linkedin_url", "linkedin_source",
    "personalization_status",
    "place_id",
]

# Master CSV also captures BBB compare-mode A/B artifacts so the analysis
# script can compute per-phase hit rates without re-running campaigns.
# FindyMail CSV stays lean — operators don't need to see the compare cols.
MASTER_EXTRA_COLUMNS = [
    "bbb_direct_name", "bbb_direct_url",
    "bbb_websearch_name", "bbb_websearch_url",
    "bbb_conflict",
]
MASTER_COLUMNS = COLUMNS + MASTER_EXTRA_COLUMNS


def run(state: CampaignState) -> tuple[str, str]:
    """Writes both CSVs. Returns (findymail_path, master_path)."""
    safe_city = state.city.replace(" ", "_").replace(",", "")
    safe_niche = state.niche.replace(" ", "_")
    base = f"{safe_city}_{state.state_abbr}_{safe_niche}_{date.today().isoformat()}"

    def _row(lead, *, with_bbb_compare: bool = False) -> dict:
        row = {
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
        }
        if with_bbb_compare:
            row["bbb_direct_name"] = lead.bbb_direct_name
            row["bbb_direct_url"] = lead.bbb_direct_url
            row["bbb_websearch_name"] = lead.bbb_websearch_name
            row["bbb_websearch_url"] = lead.bbb_websearch_url
            row["bbb_conflict"] = lead.bbb_conflict
        return row

    # FindyMail-ready CSV — kept leads with a confirmed owner first + last name
    findymail_ready = [
        l for l in state.leads
        if l.kept and l.owner_first and l.owner_last
    ]
    findymail_path = OUT_DIR / f"{base}__findymail.csv"
    with findymail_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        for lead in findymail_ready:
            w.writerow(_row(lead))

    # Master CSV — every lead captured, plus BBB compare-mode A/B artifacts.
    master_path = OUT_DIR / f"{base}__master.csv"
    with master_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=MASTER_COLUMNS)
        w.writeheader()
        for lead in state.leads:
            w.writerow(_row(lead, with_bbb_compare=True))

    state.info("csv_assembler", f"wrote FindyMail CSV ({len(findymail_ready)} rows): {findymail_path}")
    state.info("csv_assembler", f"wrote master CSV ({len(state.leads)} rows): {master_path}")
    state.mark_done("csv_assembler")
    return str(findymail_path), str(master_path)
