"""Agency CSV format — the 13-column shape used by the Vistaline VAs and
matching the Henderson_CRM_v3 example.

Two functions:
  read_enriched(path)  -> CampaignState   (parse a FindyMail-returned CSV)
  write_agency(state, path) -> None       (write the final CSV for Instantly)
"""
from __future__ import annotations
import csv
from pathlib import Path
from datetime import date

from state import CampaignState, Lead


AGENCY_COLUMNS: list[str] = [
    "Total", "Lead Sourcer", "Business", "Owner Full Name",
    "First", "Last", "Owner Email", "LinkedIn", "Website",
    "Phone", "Date", "X Project", "Y Detail",
]


def _row_get(row: dict, *keys: str) -> str:
    """Case-insensitive lookup across multiple candidate column names."""
    lower = {k.lower(): v for k, v in row.items()}
    for k in keys:
        v = lower.get(k.lower())
        if v not in (None, ""):
            return str(v).strip()
    return ""


def read_enriched(path: str | Path) -> CampaignState:
    """Read a FindyMail-returned CSV and hydrate a CampaignState."""
    state = CampaignState.new()
    path = Path(path)
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            first = _row_get(row, "First Name", "first")
            last = _row_get(row, "Last Name", "last")
            full = (first + " " + last).strip()
            lead = Lead(
                business_name=_row_get(row, "Company", "business_name", "business"),
                phone=_row_get(row, "phone"),
                website=_row_get(row, "website"),
                address=_row_get(row, "address"),
                domain=_row_get(row, "Domain", "domain"),
                owner_first=first,
                owner_last=last,
                owner_full_name=full,
                email=_row_get(row, "email", "Owner Email"),
                kept=True,
            )
            state.leads.append(lead)
    return state


def write_agency(
    state: CampaignState,
    path: str | Path,
    *,
    lead_sourcer: str = "",
) -> None:
    """Write the final agency-format CSV. One row per kept lead."""
    path = Path(path)
    today = date.today().isoformat()
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=AGENCY_COLUMNS)
        writer.writeheader()
        for i, lead in enumerate(
            (l for l in state.leads if l.kept), start=1
        ):
            writer.writerow({
                "Total": i,
                "Lead Sourcer": lead_sourcer or state.triggered_by,
                "Business": lead.business_name,
                "Owner Full Name": lead.owner_full_name,
                "First": lead.owner_first,
                "Last": lead.owner_last,
                "Owner Email": lead.email,
                "LinkedIn": lead.linkedin_url,
                "Website": lead.website,
                "Phone": lead.phone,
                "Date": today,
                "X Project": lead.x_project,
                "Y Detail": lead.y_detail,
            })
