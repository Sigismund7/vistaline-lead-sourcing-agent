"""Vistaline Lead Sourcer — FastAPI service.

All routes require X-Api-Key header matching VISTALINE_API_SECRET.
"""
from __future__ import annotations
import csv
import io
from datetime import date
from typing import Annotated

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agents.csv_agency import AGENCY_COLUMNS
from agents.cost_estimator import estimate as _cost_estimate
from api.deps import get_supabase, verify_api_key
from api.runner import run_pipeline
from api.runner_personalize import run_personalization
from state import CampaignState


def _normalise_domain(raw: str) -> str:
    """Strip protocol, www., and trailing slash; lowercase. Used to match enriched CSV to leads."""
    d = (raw or "").strip().lower()
    for prefix in ("https://", "http://"):
        if d.startswith(prefix):
            d = d[len(prefix):]
    if d.startswith("www."):
        d = d[4:]
    return d.rstrip("/")

app = FastAPI(title="Vistaline Lead Sourcer API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten to Vercel URL in production
    allow_methods=["*"],
    allow_headers=["*"],
)

AuthDep = Annotated[None, Depends(verify_api_key)]


# ---------------------------------------------------------------------------
# Campaigns
# ---------------------------------------------------------------------------

class CampaignCreate(BaseModel):
    city: str
    state_abbr: str
    niche: str
    target_count: int = 50
    triggered_by: str = "DG"
    use_registry: bool = True
    use_websearch: bool = True


@app.get("/campaigns")
def list_campaigns(_: AuthDep):
    db = get_supabase()
    rows = (
        db.table("campaigns")
        .select("*")
        .order("created_at", desc=True)
        .execute()
        .data
    )
    return rows


@app.get("/estimate")
def get_estimate(_: AuthDep, count: int = 50, keep_rate: float = 0.45):
    """Return projected Anthropic API cost for a planned run."""
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


@app.post("/campaigns", status_code=201)
def create_campaign(body: CampaignCreate, background_tasks: BackgroundTasks, _: AuthDep):
    state = CampaignState.new(triggered_by=body.triggered_by)
    state.city = body.city
    state.state_abbr = body.state_abbr.upper()
    state.niche = body.niche
    state.target_count = body.target_count
    state.use_registry = body.use_registry
    state.use_websearch = body.use_websearch
    state.status = "running"
    state.save()
    background_tasks.add_task(run_pipeline, state.campaign_id)
    return {
        "id": state.campaign_id,
        "city": state.city,
        "state_abbr": state.state_abbr,
        "niche": state.niche,
        "target_count": state.target_count,
        "triggered_by": state.triggered_by,
        "status": "running",
        "created_at": state.created_at,
        "use_registry": state.use_registry,
        "use_websearch": state.use_websearch,
    }


@app.get("/campaigns/{campaign_id}")
def get_campaign(campaign_id: str, _: AuthDep):
    db = get_supabase()
    row = db.table("campaigns").select("*").eq("id", campaign_id).single().execute().data
    if not row:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return row


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

@app.get("/campaigns/{campaign_id}/events")
def list_events(campaign_id: str, _: AuthDep):
    db = get_supabase()
    rows = (
        db.table("events")
        .select("*")
        .eq("campaign_id", campaign_id)
        .order("ts")
        .execute()
        .data
    )
    return rows


# ---------------------------------------------------------------------------
# Leads
# ---------------------------------------------------------------------------

@app.get("/campaigns/{campaign_id}/leads")
def list_leads(campaign_id: str, _: AuthDep):
    db = get_supabase()
    rows = (
        db.table("leads")
        .select("*")
        .eq("campaign_id", campaign_id)
        .execute()
        .data
    )
    return rows


class LeadPatch(BaseModel):
    excluded_by_user: bool


@app.patch("/campaigns/{campaign_id}/leads/{lead_id}")
def patch_lead(campaign_id: str, lead_id: str, body: LeadPatch, _: AuthDep):
    db = get_supabase()
    db.table("leads").update({"excluded_by_user": body.excluded_by_user}).eq(
        "id", lead_id
    ).eq("campaign_id", campaign_id).execute()
    return {"ok": True}


@app.get("/campaigns/{campaign_id}/leads.csv")
def download_findymail_csv(campaign_id: str, _: AuthDep):
    """FindyMail upload CSV: first_name, last_name, domain, phone."""
    db = get_supabase()
    rows = (
        db.table("leads")
        .select("*")
        .eq("campaign_id", campaign_id)
        .eq("kept", True)
        .eq("excluded_by_user", False)
        .execute()
        .data
    )
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["first_name", "last_name", "domain", "phone"])
    for r in rows:
        writer.writerow([r["owner_first"], r["owner_last"], r["domain"], r["phone"]])
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="findymail-{campaign_id}.csv"'},
    )


@app.get("/campaigns/{campaign_id}/leads/master.csv")
def download_master_csv(campaign_id: str, _: AuthDep):
    """Full audit CSV: all columns, all leads including filtered."""
    db = get_supabase()
    rows = (
        db.table("leads")
        .select("*")
        .eq("campaign_id", campaign_id)
        .execute()
        .data
    )
    buf = io.StringIO()
    writer = csv.DictWriter(
        buf,
        fieldnames=[
            "business_name", "phone", "website", "address", "area_code", "domain",
            "place_id", "kept", "reject_reason", "owner_full_name", "owner_first",
            "owner_last", "owner_source", "email", "excluded_by_user",
        ],
    )
    writer.writeheader()
    writer.writerows([{k: r.get(k, "") for k in writer.fieldnames} for r in rows])
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="master-{campaign_id}.csv"'},
    )


@app.get("/campaigns/{campaign_id}/leads/agency.csv")
def download_agency_csv(campaign_id: str, _: AuthDep):
    """Agency-format CSV: 13 columns, Instantly-ready."""
    db = get_supabase()
    campaign_row = db.table("campaigns").select("id").eq("id", campaign_id).execute().data
    if not campaign_row:
        raise HTTPException(status_code=404, detail="Campaign not found")
    rows = (
        db.table("leads")
        .select("*")
        .eq("campaign_id", campaign_id)
        .eq("kept", True)
        .execute()
        .data
    )
    today = date.today().isoformat()
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=AGENCY_COLUMNS)
    writer.writeheader()
    for i, r in enumerate(rows, start=1):
        writer.writerow({
            "Total": i,
            "Lead Sourcer": r.get("triggered_by") or "DG",
            "Business": r.get("business_name") or "",
            "Owner Full Name": r.get("owner_full_name") or "",
            "First": r.get("owner_first") or "",
            "Last": r.get("owner_last") or "",
            "Owner Email": r.get("email") or "",
            "LinkedIn": r.get("linkedin_url") or "",
            "Website": r.get("website") or "",
            "Phone": r.get("phone") or "",
            "Date": today,
            "X Project": r.get("x_project") or "",
            "Y Detail": r.get("y_detail") or "",
        })
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="agency-{campaign_id}.csv"'},
    )


@app.post("/campaigns/{campaign_id}/enrich", status_code=202)
async def enrich_campaign(
    campaign_id: str,
    file: UploadFile,
    background_tasks: BackgroundTasks,
    _: AuthDep,
):
    """Accept a FindyMail-returned CSV, write emails onto leads by domain, start personalizer."""
    db = get_supabase()

    campaign_row = db.table("campaigns").select("id").eq("id", campaign_id).execute().data
    if not campaign_row:
        raise HTTPException(status_code=404, detail="Campaign not found")

    try:
        content = (await file.read()).decode("utf-8")
        reader = csv.DictReader(io.StringIO(content))
        enriched_rows = list(reader)
    except Exception:
        raise HTTPException(status_code=422, detail="Could not parse CSV — check encoding and format")

    if not enriched_rows:
        raise HTTPException(status_code=422, detail="CSV is empty")

    # Build domain → email lookup from the enriched CSV.
    domain_to_email: dict[str, str] = {}
    for r in enriched_rows:
        lower = {k.lower().strip(): v for k, v in r.items()}
        domain = _normalise_domain(lower.get("domain", ""))
        email = (lower.get("email") or lower.get("owner email") or "").strip()
        if domain and email:
            domain_to_email[domain] = email

    if not domain_to_email:
        raise HTTPException(
            status_code=422,
            detail="No email+domain pairs found — wrong file or FindyMail returned no results",
        )

    # Load campaign leads and match by domain.
    lead_rows = (
        db.table("leads")
        .select("id, domain")
        .eq("campaign_id", campaign_id)
        .execute()
        .data
    )

    matched = 0
    for lead in lead_rows:
        norm = _normalise_domain(lead.get("domain") or "")
        email = domain_to_email.get(norm)
        if email:
            db.table("leads").update({"email": email}).eq("id", lead["id"]).execute()
            matched += 1

    if matched == 0:
        raise HTTPException(
            status_code=422,
            detail="No leads matched by domain — is this the right campaign or file?",
        )

    db.table("campaigns").update({"status": "personalizing"}).eq("id", campaign_id).execute()
    background_tasks.add_task(run_personalization, campaign_id)

    return {"ok": True, "matched": matched, "unmatched": len(enriched_rows) - matched}
