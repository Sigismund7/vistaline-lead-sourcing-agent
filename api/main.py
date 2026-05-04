"""Vistaline Lead Sourcer — FastAPI service.

All routes require X-Api-Key header matching VISTALINE_API_SECRET.
"""
from __future__ import annotations
import csv
import io
from typing import Annotated

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from api.deps import get_supabase, verify_api_key
from api.runner import run_pipeline
from state import CampaignState

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
