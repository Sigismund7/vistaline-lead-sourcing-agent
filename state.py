"""Campaign state — single object that flows through every agent.

State persists to Supabase after each step. Resume a crashed run:
    python run.py --resume <campaign_id>
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
import uuid
import os

from supabase import create_client, Client as SupabaseClient


def _db() -> SupabaseClient:
    """New Supabase client per call — safe to use from multiple threads."""
    return create_client(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_SERVICE_ROLE_KEY"],
    )


@dataclass
class Lead:
    """One lead as it evolves through the pipeline.

    Sourcer fills:          business_name, phone, website, address, area_code, domain, place_id
    Lead filter fills:      kept, reject_reason
    Owner researcher fills: owner_full_name, owner_first, owner_last, owner_source, email
    """
    business_name: str = ""
    phone: str = ""
    website: str = ""
    address: str = ""
    area_code: str = ""
    domain: str = ""
    place_id: str = ""
    kept: bool = True
    reject_reason: str = ""
    owner_full_name: str = ""
    owner_first: str = ""
    owner_last: str = ""
    owner_source: str = ""
    email: str = ""
    # Personalization (post-FindyMail). Empty string means "not run yet".
    x_project: str = ""
    y_detail: str = ""
    y_source: str = ""               # "website_gallery" | "yelp_photo" | ""
    linkedin_url: str = ""
    linkedin_source: str = ""        # "web_search" | ""
    personalization_status: str = "" # "ok" | "no_gallery" | "vision_failed" | "no_email_skip"


@dataclass
class CampaignState:
    campaign_id: str
    city: str = ""
    state_abbr: str = ""
    niche: str = ""
    target_count: int = 50
    triggered_by: str = "DG"
    status: str = "running"
    leads: list[Lead] = field(default_factory=list)
    log: list[dict] = field(default_factory=list)
    completed_steps: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def save(self) -> None:
        """Upsert the campaign summary row to Supabase.

        Non-fatal when Supabase credentials are not configured — lets local
        runs proceed without a database connection.
        """
        kept = [l for l in self.leads if l.kept]
        payload: dict = {
            "id": self.campaign_id,
            "city": self.city,
            "state_abbr": self.state_abbr,
            "niche": self.niche,
            "target_count": self.target_count,
            "triggered_by": self.triggered_by,
            "status": self.status,
            "total_leads": len(self.leads),
            "kept_leads": len(kept),
            "with_owner": sum(1 for l in kept if l.owner_first),
            "with_email": sum(1 for l in kept if l.email),
            "completed_steps": self.completed_steps,
            "created_at": self.created_at,
        }
        if self.status == "completed":
            payload["completed_at"] = datetime.utcnow().isoformat()
        try:
            _db().table("campaigns").upsert(payload).execute()
        except Exception as exc:
            print(f"[state] save failed (non-fatal): {exc}")

    def save_leads(self) -> None:
        """Replace all leads for this campaign in Supabase. Call after pipeline completes.

        Non-fatal when Supabase credentials are not configured.
        """
        if not self.leads:
            return
        rows = [
            {
                "campaign_id": self.campaign_id,
                "business_name": l.business_name,
                "phone": l.phone,
                "website": l.website,
                "address": l.address,
                "area_code": l.area_code,
                "domain": l.domain,
                "place_id": l.place_id,
                "kept": l.kept,
                "reject_reason": l.reject_reason,
                "owner_full_name": l.owner_full_name,
                "owner_first": l.owner_first,
                "owner_last": l.owner_last,
                "owner_source": l.owner_source,
                "email": l.email,
                "x_project": l.x_project,
                "y_detail": l.y_detail,
                "y_source": l.y_source,
                "linkedin_url": l.linkedin_url,
                "linkedin_source": l.linkedin_source,
                "personalization_status": l.personalization_status,
            }
            for l in self.leads
        ]
        try:
            db = _db()
            db.table("leads").delete().eq("campaign_id", self.campaign_id).execute()
            db.table("leads").insert(rows).execute()
        except Exception as exc:
            print(f"[state] save_leads failed (non-fatal): {exc}")

    @classmethod
    def load(cls, campaign_id: str) -> "CampaignState":
        db = _db()
        row = db.table("campaigns").select("*").eq("id", campaign_id).single().execute().data
        lead_rows = db.table("leads").select("*").eq("campaign_id", campaign_id).execute().data
        leads = [
            Lead(
                business_name=r["business_name"],
                phone=r["phone"],
                website=r["website"],
                address=r["address"],
                area_code=r["area_code"],
                domain=r["domain"],
                place_id=r["place_id"],
                kept=r["kept"],
                reject_reason=r["reject_reason"],
                owner_full_name=r["owner_full_name"],
                owner_first=r["owner_first"],
                owner_last=r["owner_last"],
                owner_source=r["owner_source"],
                email=r["email"],
                x_project=r.get("x_project", "") or "",
                y_detail=r.get("y_detail", "") or "",
                y_source=r.get("y_source", "") or "",
                linkedin_url=r.get("linkedin_url", "") or "",
                linkedin_source=r.get("linkedin_source", "") or "",
                personalization_status=r.get("personalization_status", "") or "",
            )
            for r in lead_rows
        ]
        return cls(
            campaign_id=row["id"],
            city=row["city"],
            state_abbr=row["state_abbr"],
            niche=row["niche"],
            target_count=row["target_count"],
            triggered_by=row.get("triggered_by", "DG"),
            status=row.get("status", "running"),
            leads=leads,
            completed_steps=row.get("completed_steps") or [],
            created_at=row["created_at"],
        )

    @classmethod
    def new(cls, triggered_by: str = "DG") -> "CampaignState":
        return cls(
            campaign_id=datetime.utcnow().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6],
            triggered_by=triggered_by,
        )

    def info(self, agent: str, message: str, **fields) -> None:
        entry = {"ts": datetime.utcnow().isoformat(), "agent": agent, "msg": message, **fields}
        self.log.append(entry)
        print(f"[{agent}] {message}" + (f"  {fields}" if fields else ""))
        try:
            _db().table("events").insert({
                "campaign_id": self.campaign_id,
                "step": agent,
                "level": fields.get("level", "info"),
                "message": message,
                "detail": fields.get("detail"),
                "duration_ms": fields.get("duration_ms"),
            }).execute()
        except Exception as exc:
            print(f"[state] event insert failed (non-fatal): {exc}")

    def mark_done(self, step: str) -> None:
        if step not in self.completed_steps:
            self.completed_steps.append(step)
        self.save()

    def is_done(self, step: str) -> bool:
        return step in self.completed_steps
