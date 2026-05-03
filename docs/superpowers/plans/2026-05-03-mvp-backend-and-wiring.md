# MVP Backend + Live Wiring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the Vistaline Lead Sourcer frontend to a real Supabase database and FastAPI backend so the team can launch campaigns from the browser, watch them run live, and download results — no SSH, no CSV hunting.

**Architecture:** Supabase (Postgres + Realtime pub/sub) replaces JSON-on-disk state. FastAPI on Railway wraps the existing `run.py` pipeline without changing any agent code. Next.js on Vercel fetches via REST and subscribes to Supabase Realtime for live event streaming. Clerk handles team auth with a single org login.

**Tech Stack:** Python 3.12, FastAPI 0.115, supabase-py 2.9, Next.js 16 (App Router), @clerk/nextjs, @supabase/supabase-js, Supabase (hosted Postgres + Realtime), Railway (API), Vercel (frontend)

---

## File Map

**Create (Python):**
- `api/__init__.py` — makes api/ a package
- `api/main.py` — FastAPI app, all routes
- `api/deps.py` — Supabase client singleton, API-key auth dependency
- `api/runner.py` — async wrapper that runs sync pipeline in thread executor
- `Procfile` — Railway start command

**Create (Frontend):**
- `frontend/lib/supabase.ts` — browser Supabase client (Realtime subscriptions only)
- `frontend/lib/api.ts` — typed fetch wrapper pointing at FastAPI
- `frontend/middleware.ts` — Clerk middleware, protects all routes

**Modify (Python):**
- `state.py` — Supabase backend; adds `status` field, `save_leads()` method
- `config.py` — adds `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `VISTALINE_API_SECRET`
- `requirements.txt` — adds `supabase>=2.9`, `fastapi>=0.115`, `uvicorn>=0.32`, `python-multipart>=0.0.9`
- `.env.example` — documents all env vars (create if missing)
- `run.py` — threads `triggered_by` through, calls `state.save_leads()` after csv_assembler

**Modify (Frontend):**
- `frontend/package.json` — adds `@clerk/nextjs`, `@supabase/supabase-js`
- `frontend/app/layout.tsx` — wraps with `<ClerkProvider>`
- `frontend/components/app-header.tsx` — swaps static "DG" avatar for Clerk `<UserButton />`
- `frontend/app/campaigns/page.tsx` — fetches from FastAPI (server component + async fetch)
- `frontend/app/campaigns/new/page.tsx` — POSTs to FastAPI, gets `triggered_by` from Clerk
- `frontend/app/campaigns/[id]/page.tsx` — convert to client component, Supabase Realtime live events
- `frontend/app/campaigns/[id]/results/page.tsx` — fetches real leads, real CSV download buttons

---

### Task 1: Supabase Schema

**Files:**
- Create: `supabase/migrations/001_initial.sql` (reference — run in Supabase SQL editor)

- [ ] **Step 1: Create a Supabase project**

  Go to https://supabase.com → New project → name it "vistaline-lead-sourcer" → note the Project URL and service_role key from Settings → API.

- [ ] **Step 2: Run the schema SQL**

  Open Supabase Dashboard → SQL Editor → New query → paste and run:

```sql
-- campaigns
CREATE TABLE campaigns (
  id             TEXT        PRIMARY KEY,
  city           TEXT        NOT NULL,
  state_abbr     TEXT        NOT NULL,
  niche          TEXT        NOT NULL,
  target_count   INTEGER     NOT NULL DEFAULT 50,
  triggered_by   TEXT        NOT NULL DEFAULT 'DG',
  status         TEXT        NOT NULL DEFAULT 'queued',  -- queued | running | completed | failed
  total_leads    INTEGER     NOT NULL DEFAULT 0,
  kept_leads     INTEGER     NOT NULL DEFAULT 0,
  with_owner     INTEGER     NOT NULL DEFAULT 0,
  with_email     INTEGER     NOT NULL DEFAULT 0,
  spend_usd      NUMERIC(8,4) NOT NULL DEFAULT 0,
  completed_steps TEXT[]     NOT NULL DEFAULT '{}',
  created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  completed_at   TIMESTAMPTZ,
  error_message  TEXT
);

-- leads (populated after owner_researcher completes)
CREATE TABLE leads (
  id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  campaign_id     TEXT        NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
  business_name   TEXT        NOT NULL DEFAULT '',
  phone           TEXT        NOT NULL DEFAULT '',
  website         TEXT        NOT NULL DEFAULT '',
  address         TEXT        NOT NULL DEFAULT '',
  area_code       TEXT        NOT NULL DEFAULT '',
  domain          TEXT        NOT NULL DEFAULT '',
  place_id        TEXT        NOT NULL DEFAULT '',
  kept            BOOLEAN     NOT NULL DEFAULT TRUE,
  reject_reason   TEXT        NOT NULL DEFAULT '',
  owner_full_name TEXT        NOT NULL DEFAULT '',
  owner_first     TEXT        NOT NULL DEFAULT '',
  owner_last      TEXT        NOT NULL DEFAULT '',
  owner_source    TEXT        NOT NULL DEFAULT '',
  email           TEXT        NOT NULL DEFAULT '',
  excluded_by_user BOOLEAN    NOT NULL DEFAULT FALSE
);

-- events (pipeline log entries, streamed live via Realtime)
CREATE TABLE events (
  id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  campaign_id TEXT        NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
  step        TEXT        NOT NULL,
  level       TEXT        NOT NULL DEFAULT 'info',  -- info | warn | error | success
  message     TEXT        NOT NULL,
  detail      TEXT,
  duration_ms INTEGER,
  ts          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for common queries
CREATE INDEX leads_campaign_id ON leads (campaign_id);
CREATE INDEX events_campaign_id_ts ON events (campaign_id, ts);

-- Enable Realtime on the tables the frontend subscribes to
ALTER PUBLICATION supabase_realtime ADD TABLE campaigns;
ALTER PUBLICATION supabase_realtime ADD TABLE events;
```

- [ ] **Step 3: Verify in Table Editor**

  Supabase Dashboard → Table Editor — confirm three tables exist with correct columns.

- [ ] **Step 4: Commit the SQL file**

```bash
mkdir -p supabase/migrations
# (file already written at supabase/migrations/001_initial.sql)
git add supabase/migrations/001_initial.sql
git commit -m "feat: add Supabase schema SQL"
```

---

### Task 2: Python Deps + Config

**Files:**
- Modify: `requirements.txt`
- Modify: `config.py`
- Create: `.env.example` (if not present)

- [ ] **Step 1: Write the failing smoke test**

```bash
# tests/test_deps_import.py
cat > tests/test_deps_import.py << 'EOF'
"""Smoke test: new deps importable after pip install."""
import importlib, sys

for mod in ["supabase", "fastapi", "uvicorn"]:
    try:
        importlib.import_module(mod)
        print(f"OK  {mod}")
    except ImportError as e:
        print(f"FAIL {mod}: {e}")
        sys.exit(1)

print("All deps OK")
EOF
python tests/test_deps_import.py
```
Expected: FAIL (modules not yet installed)

- [ ] **Step 2: Update requirements.txt**

Replace the content of `requirements.txt` with:

```
anthropic>=0.40.0
requests>=2.31.0
python-dotenv>=1.0.0
beautifulsoup4>=4.12.0
rapidfuzz>=3.0.0
supabase>=2.9.0
fastapi>=0.115.0
uvicorn>=0.32.0
python-multipart>=0.0.9
```

- [ ] **Step 3: Install deps**

```bash
source .venv/bin/activate && pip install -r requirements.txt
```
Expected: packages install without errors

- [ ] **Step 4: Run smoke test to verify pass**

```bash
source .venv/bin/activate && python tests/test_deps_import.py
```
Expected: `All deps OK`

- [ ] **Step 5: Update config.py**

Add three new fields to the `Config` dataclass and their readers in `CONFIG`:

```python
# In the Config dataclass, after brave_search_key:
supabase_url: str = ""
supabase_service_role_key: str = ""
vistaline_api_secret: str = ""
```

```python
# In CONFIG = Config(...), add:
supabase_url=_require("SUPABASE_URL"),
supabase_service_role_key=_require("SUPABASE_SERVICE_ROLE_KEY"),
vistaline_api_secret=_require("VISTALINE_API_SECRET"),
```

- [ ] **Step 6: Create .env.example**

```bash
cat > .env.example << 'EOF'
# Anthropic
ANTHROPIC_API_KEY=sk-ant-...

# Google Places
GOOGLE_PLACES_KEY=AIza...

# Optional sourcing layers
AZURE_MAPS_KEY=
YELP_FUSION_KEY=
BRAVE_SEARCH_KEY=

# Supabase
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_SERVICE_ROLE_KEY=eyJ...

# API auth (shared secret between FastAPI and frontend)
# Generate with: python -c "import secrets; print(secrets.token_hex(32))"
VISTALINE_API_SECRET=

# Optional
DEFAULT_NICHE=bathroom remodeling
EOF
```

- [ ] **Step 7: Commit**

```bash
git add requirements.txt config.py .env.example tests/test_deps_import.py
git commit -m "feat: add supabase + fastapi deps, config keys"
```

---

### Task 3: state.py Rewrite — Supabase Backend

**Files:**
- Modify: `state.py`

The public interface must stay identical (same `Lead` dataclass fields, same `CampaignState` methods) so agents require zero changes. New additions: `status: str = "running"` field, `save_leads()` method. The `path` property is removed (no more JSON).

- [ ] **Step 1: Write the failing smoke test**

```bash
cat > tests/test_state_interface.py << 'EOF'
"""Verify CampaignState public interface is intact after Supabase rewrite."""
from state import CampaignState, Lead
import inspect

# Check Lead fields
lead = Lead(business_name="Acme Remodeling", phone="4075550100")
assert lead.business_name == "Acme Remodeling"
assert lead.kept == True
assert lead.email == ""

# Check CampaignState interface
state = CampaignState.__new__(CampaignState)
required_methods = ["save", "load", "new", "info", "mark_done", "is_done", "save_leads"]
for m in required_methods:
    assert hasattr(CampaignState, m), f"Missing method: {m}"

# Check status field exists
import dataclasses
fields = {f.name for f in dataclasses.fields(CampaignState)}
assert "status" in fields, "Missing status field"

print("Interface OK")
EOF
python tests/test_state_interface.py
```
Expected: FAIL (`save_leads` and `status` not yet added)

- [ ] **Step 2: Rewrite state.py**

Replace the entire file:

```python
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
        """Upsert the campaign summary row to Supabase."""
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
        _db().table("campaigns").upsert(payload).execute()

    def save_leads(self) -> None:
        """Replace all leads for this campaign in Supabase. Call after pipeline completes."""
        if not self.leads:
            return
        db = _db()
        db.table("leads").delete().eq("campaign_id", self.campaign_id).execute()
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
            }
            for l in self.leads
        ]
        db.table("leads").insert(rows).execute()

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
```

- [ ] **Step 3: Run interface smoke test**

```bash
source .venv/bin/activate && python tests/test_state_interface.py
```
Expected: `Interface OK`

- [ ] **Step 4: Verify agents still import cleanly**

```bash
source .venv/bin/activate && python -c "from agents import sourcer, lead_filter, owner_researcher, csv_assembler; print('OK')"
```
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add state.py tests/test_state_interface.py
git commit -m "feat: rewrite state.py to persist to Supabase"
```

---

### Task 4: FastAPI Service

**Files:**
- Create: `api/__init__.py`
- Create: `api/deps.py`
- Create: `api/runner.py`
- Create: `api/main.py`
- Create: `Procfile`

- [ ] **Step 1: Write the failing smoke test**

```bash
cat > tests/test_api_import.py << 'EOF'
"""Smoke: FastAPI app importable and routes registered."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from api.main import app
routes = {r.path for r in app.routes}
assert "/campaigns" in routes, f"Missing /campaigns. Routes: {routes}"
assert "/campaigns/{campaign_id}" in routes, "Missing /campaigns/{campaign_id}"
assert "/campaigns/{campaign_id}/events" in routes, "Missing events route"
assert "/campaigns/{campaign_id}/leads" in routes, "Missing leads route"
assert "/campaigns/{campaign_id}/leads.csv" in routes, "Missing CSV route"
print("API routes OK")
EOF
source .venv/bin/activate && python tests/test_api_import.py
```
Expected: FAIL (api/main.py doesn't exist yet)

- [ ] **Step 2: Create api/__init__.py**

```python
```
(empty file)

- [ ] **Step 3: Create api/deps.py**

```python
"""FastAPI shared dependencies: Supabase client and API-key auth."""
from __future__ import annotations
import os
from functools import lru_cache

from fastapi import Header, HTTPException
from supabase import create_client, Client as SupabaseClient


@lru_cache(maxsize=1)
def get_supabase() -> SupabaseClient:
    return create_client(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_SERVICE_ROLE_KEY"],
    )


def verify_api_key(x_api_key: str = Header(...)) -> None:
    """Dependency: reject requests with wrong API key."""
    if x_api_key != os.environ["VISTALINE_API_SECRET"]:
        raise HTTPException(status_code=401, detail="Invalid API key")
```

- [ ] **Step 4: Create api/runner.py**

```python
"""Async wrapper that runs the synchronous pipeline in a thread pool."""
from __future__ import annotations
import asyncio

from config import CONFIG
from state import CampaignState
from agents import sourcer, lead_filter, owner_researcher, csv_assembler


async def run_pipeline(campaign_id: str) -> None:
    """Launch the pipeline for campaign_id in a thread (non-blocking)."""
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _run_sync, campaign_id)


def _run_sync(campaign_id: str) -> None:
    state = CampaignState.load(campaign_id)
    try:
        sourcer.run(state, CONFIG.google_places_key)
        lead_filter.run(state, CONFIG.anthropic_key)
        owner_researcher.run(state, CONFIG.anthropic_key)
        csv_assembler.run(state)
        state.save_leads()
        state.status = "completed"
        state.save()
    except Exception as exc:
        state.status = "failed"
        state.info("runner", f"Pipeline failed: {exc}", level="error")
        state.save()
        raise
```

- [ ] **Step 5: Create api/main.py**

```python
"""Vistaline Lead Sourcer — FastAPI service.

All routes require X-Api-Key header matching VISTALINE_API_SECRET.
"""
from __future__ import annotations
import csv
import io
from datetime import datetime
from typing import Annotated

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from api.deps import get_supabase, verify_api_key
from api.runner import run_pipeline
from config import CONFIG
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
    writer.writerows(rows)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="master-{campaign_id}.csv"'},
    )
```

- [ ] **Step 6: Create Procfile**

```
web: uvicorn api.main:app --host 0.0.0.0 --port $PORT
```

- [ ] **Step 7: Run smoke test**

```bash
source .venv/bin/activate && python tests/test_api_import.py
```
Expected: `API routes OK`

- [ ] **Step 8: Verify the server starts**

```bash
source .venv/bin/activate && SUPABASE_URL=https://placeholder.supabase.co SUPABASE_SERVICE_ROLE_KEY=placeholder VISTALINE_API_SECRET=test ANTHROPIC_API_KEY=test GOOGLE_PLACES_KEY=test uvicorn api.main:app --port 8001 &
sleep 2 && curl -s http://localhost:8001/docs | head -5
kill %1
```
Expected: HTML starting with `<!DOCTYPE html>` (FastAPI docs page)

- [ ] **Step 9: Commit**

```bash
git add api/ Procfile tests/test_api_import.py
git commit -m "feat: FastAPI service with campaigns/leads/events/CSV routes"
```

---

### Task 5: run.py — triggered_by + save_leads

**Files:**
- Modify: `run.py`

- [ ] **Step 1: Update run.py**

Add `--triggered-by` CLI argument and `save_leads()` call after csv_assembler. Locate these two sections in run.py and apply:

**In `parse_args()`** — add after the `--niche` argument:
```python
p.add_argument("--triggered-by", default="DG", help='Who launched this run (default: DG)')
```

**In the `else` branch of `main()` that creates a new state** — after `state.target_count = args.count`, add:
```python
state.triggered_by = args.triggered_by
```

**After `findymail_path, master_path = csv_assembler.run(state)`** — add:
```python
# Persist all leads to Supabase so the web UI can show and export them.
state.save_leads()
```

**In the except block** — after `traceback.print_exc()`, add:
```python
state.status = "failed"
state.save()
```

- [ ] **Step 2: Verify smoke import**

```bash
source .venv/bin/activate && python -c "from agents import sourcer, lead_filter, owner_researcher, csv_assembler; print('OK')"
```
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add run.py
git commit -m "feat: thread triggered_by through run.py, save leads to Supabase on completion"
```

---

### Task 6: Frontend Deps + Clerk Auth

**Files:**
- Modify: `frontend/package.json`
- Create: `frontend/middleware.ts`
- Modify: `frontend/app/layout.tsx`
- Modify: `frontend/components/app-header.tsx`
- Create: `frontend/.env.local` (user must fill values; gitignored)

- [ ] **Step 1: Install frontend deps**

```bash
cd frontend && bun add @clerk/nextjs @supabase/supabase-js
```
Expected: packages added to package.json

- [ ] **Step 2: Create a Clerk application**

  Go to https://clerk.com → Create application → name "Vistaline Lead Sourcer" → enable Email sign-in. Copy the Publishable Key and Secret Key.

- [ ] **Step 3: Create frontend/.env.local**

```bash
cat > frontend/.env.local << 'EOF'
# Clerk auth
NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=pk_test_...
CLERK_SECRET_KEY=sk_test_...
NEXT_PUBLIC_CLERK_SIGN_IN_URL=/sign-in
NEXT_PUBLIC_CLERK_AFTER_SIGN_IN_URL=/campaigns
NEXT_PUBLIC_CLERK_AFTER_SIGN_UP_URL=/campaigns

# FastAPI backend
NEXT_PUBLIC_API_URL=http://localhost:8000
VISTALINE_API_SECRET=same-value-as-backend

# Supabase (for Realtime subscriptions — use anon key, NOT service_role)
NEXT_PUBLIC_SUPABASE_URL=https://<project-ref>.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=eyJ...
EOF
```

  Fill in real values. This file is gitignored — never commit it.

- [ ] **Step 4: Create frontend/middleware.ts**

```typescript
import { clerkMiddleware, createRouteMatcher } from "@clerk/nextjs/server";

const isPublicRoute = createRouteMatcher(["/sign-in(.*)", "/sign-up(.*)"]);

export default clerkMiddleware((auth, req) => {
  if (!isPublicRoute(req)) auth().protect();
});

export const config = {
  matcher: [
    "/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)",
    "/(api|trpc)(.*)",
  ],
};
```

- [ ] **Step 5: Wrap layout.tsx with ClerkProvider**

Replace the entire `frontend/app/layout.tsx` with:

```typescript
import type { Metadata } from "next";
import { Cinzel, Geist, Geist_Mono } from "next/font/google";
import { ClerkProvider } from "@clerk/nextjs";
import { AppHeader } from "@/components/app-header";
import "./globals.css";

const cinzel = Cinzel({
  variable: "--font-cinzel",
  subsets: ["latin"],
  weight: ["400", "600", "700"],
});

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Vistaline Lead Sourcer",
  description: "Source FindyMail-ready leads for residential contractors.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <ClerkProvider>
      <html
        lang="en"
        className={`${cinzel.variable} ${geistSans.variable} ${geistMono.variable} h-full antialiased`}
      >
        <body className="min-h-full flex flex-col bg-background text-foreground font-sans">
          <AppHeader activePath="/campaigns" />
          <main className="flex-1">{children}</main>
        </body>
      </html>
    </ClerkProvider>
  );
}
```

- [ ] **Step 6: Add UserButton to AppHeader**

In `frontend/components/app-header.tsx`, replace the static avatar `<span>` with the Clerk UserButton.

Replace:
```typescript
import Link from "next/link";
import { cn } from "@/lib/utils";
```
With:
```typescript
import Link from "next/link";
import { UserButton } from "@clerk/nextjs";
import { cn } from "@/lib/utils";
```

Replace the avatar div (the one containing `DG`):
```typescript
        <div className="ml-auto flex items-center gap-3 text-xs text-muted-foreground">
          <span className="hidden sm:inline">$3.21 spend MTD</span>
          <span
            aria-hidden
            className="hidden h-4 w-px bg-border sm:block"
          />
          <span className="rounded-sm border border-border bg-muted px-2 py-1 font-mono text-foreground">DG</span>
        </div>
```
With:
```typescript
        <div className="ml-auto flex items-center gap-3 text-xs text-muted-foreground">
          <UserButton afterSignOutUrl="/sign-in" />
        </div>
```

- [ ] **Step 7: Verify build**

```bash
cd frontend && bun run build 2>&1 | tail -20
```
Expected: build succeeds (or only minor type warnings — no errors)

- [ ] **Step 8: Commit**

```bash
cd ..
git add frontend/package.json frontend/middleware.ts frontend/app/layout.tsx frontend/components/app-header.tsx
# .env.local is gitignored — do not add it
git commit -m "feat: add Clerk auth, protect all routes, UserButton in header"
```

---

### Task 7: Frontend API + Supabase Clients

**Files:**
- Create: `frontend/lib/supabase.ts`
- Create: `frontend/lib/api.ts`

- [ ] **Step 1: Create frontend/lib/supabase.ts**

```typescript
import { createClient } from "@supabase/supabase-js";

const url = process.env.NEXT_PUBLIC_SUPABASE_URL!;
const anon = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!;

export const supabase = createClient(url, anon);
```

- [ ] **Step 2: Create frontend/lib/api.ts**

```typescript
import type { Campaign, RunEvent, Lead } from "@/lib/types";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const SECRET = process.env.VISTALINE_API_SECRET ?? "";

async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      "X-Api-Key": SECRET,
      ...init.headers,
    },
  });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`API ${res.status}: ${text}`);
  }
  return res.json() as Promise<T>;
}

// ---- Campaigns ----

export function getCampaigns(): Promise<Campaign[]> {
  return apiFetch<Campaign[]>("/campaigns").then((rows) => rows.map(toCampaign));
}

export function getCampaign(id: string): Promise<Campaign> {
  return apiFetch<Campaign>(`/campaigns/${id}`).then(toCampaign);
}

export async function createCampaign(params: {
  city: string;
  state_abbr: string;
  niche: string;
  target_count: number;
  triggered_by: string;
}): Promise<{ id: string }> {
  return apiFetch<{ id: string }>("/campaigns", {
    method: "POST",
    body: JSON.stringify(params),
  });
}

// ---- Events ----

export function getEvents(campaignId: string): Promise<RunEvent[]> {
  return apiFetch<RunEvent[]>(`/campaigns/${campaignId}/events`).then((rows) =>
    rows.map(toEvent),
  );
}

// ---- Leads ----

export function getLeads(campaignId: string): Promise<Lead[]> {
  return apiFetch<Lead[]>(`/campaigns/${campaignId}/leads`).then((rows) =>
    rows.map(toLead),
  );
}

export function patchLead(
  campaignId: string,
  leadId: string,
  excluded: boolean,
): Promise<void> {
  return apiFetch(`/campaigns/${campaignId}/leads/${leadId}`, {
    method: "PATCH",
    body: JSON.stringify({ excluded_by_user: excluded }),
  });
}

export function csvUrl(campaignId: string, type: "findymail" | "master"): string {
  const path =
    type === "findymail"
      ? `/campaigns/${campaignId}/leads.csv`
      : `/campaigns/${campaignId}/leads/master.csv`;
  return `${BASE}${path}?x-api-key=${SECRET}`;
}

// ---- Transformers (snake_case DB → camelCase UI) ----

function toCampaign(r: Record<string, unknown>): Campaign {
  return {
    id: r.id as string,
    city: r.city as string,
    stateAbbr: r.state_abbr as string,
    niche: r.niche as string,
    targetCount: r.target_count as number,
    status: r.status as Campaign["status"],
    createdAt: r.created_at as string,
    completedAt: r.completed_at as string | undefined,
    totalLeads: (r.total_leads as number) ?? 0,
    keptLeads: (r.kept_leads as number) ?? 0,
    withOwner: (r.with_owner as number) ?? 0,
    withEmail: (r.with_email as number) ?? 0,
    spendUsd: (r.spend_usd as number) ?? 0,
    triggeredBy: (r.triggered_by as string) ?? "DG",
  };
}

function toEvent(r: Record<string, unknown>): RunEvent {
  return {
    id: r.id as string,
    step: r.step as RunEvent["step"],
    level: (r.level as RunEvent["level"]) ?? "info",
    message: r.message as string,
    detail: r.detail as string | undefined,
    durationMs: r.duration_ms as number | undefined,
    ts: r.ts as string,
  };
}

function toLead(r: Record<string, unknown>): Lead {
  return {
    id: r.id as string,
    businessName: r.business_name as string,
    phone: r.phone as string,
    website: r.website as string,
    domain: r.domain as string,
    address: r.address as string,
    areaCode: r.area_code as string,
    ownerFirst: r.owner_first as string,
    ownerLast: r.owner_last as string,
    ownerSource: (r.owner_source as Lead["ownerSource"]) ?? "",
    email: r.email as string,
    kept: r.kept as boolean,
    excludedByUser: (r.excluded_by_user as boolean) ?? false,
    rejectReason: r.reject_reason as string,
  };
}
```

> **Note on API secret in frontend:** `VISTALINE_API_SECRET` must be available server-side only (no `NEXT_PUBLIC_` prefix). For client components calling the API, route through Next.js Server Actions or API routes so the secret never reaches the browser. See Task 8 for the new-campaign form pattern. The CSV download URLs expose the secret in the query string — for MVP this is acceptable on an internal tool; replace with short-lived signed tokens later.

- [ ] **Step 3: Verify TypeScript compiles**

```bash
cd frontend && bun run build 2>&1 | grep -E "error|Error" | head -20
```
Expected: no type errors related to api.ts or supabase.ts

- [ ] **Step 4: Commit**

```bash
cd ..
git add frontend/lib/supabase.ts frontend/lib/api.ts
git commit -m "feat: add FastAPI fetch client and Supabase browser client"
```

---

### Task 8: Wire Campaigns List Page

**Files:**
- Modify: `frontend/app/campaigns/page.tsx`

The page is already a server component. We replace `MOCK_CAMPAIGNS` with a real `fetch` to FastAPI. Because this is a server component, we use `VISTALINE_API_SECRET` directly (server-side env var, no `NEXT_PUBLIC_`).

- [ ] **Step 1: Replace campaigns/page.tsx**

Replace the entire file content. The structure (STATUS_TONE, table, cards) stays the same — only the data source changes:

```typescript
import Link from "next/link";
import { ArrowUpRight, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { CampaignStatus, Campaign } from "@/lib/types";
import { cn } from "@/lib/utils";

const STATUS_TONE: Record<CampaignStatus, string> = {
  queued: "bg-muted text-muted-foreground",
  running: "bg-info/10 text-info border-info/30",
  completed: "bg-success/10 text-success border-success/30",
  failed: "bg-danger/10 text-danger border-danger/30",
};

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function formatCurrency(value: number): string {
  return value.toLocaleString(undefined, { style: "currency", currency: "USD" });
}

async function fetchCampaigns(): Promise<Campaign[]> {
  const base = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
  const secret = process.env.VISTALINE_API_SECRET ?? "";
  const res = await fetch(`${base}/campaigns`, {
    headers: { "X-Api-Key": secret },
    next: { revalidate: 10 },
  });
  if (!res.ok) return [];
  const rows: Record<string, unknown>[] = await res.json();
  return rows.map((r) => ({
    id: r.id as string,
    city: r.city as string,
    stateAbbr: r.state_abbr as string,
    niche: r.niche as string,
    targetCount: r.target_count as number,
    status: r.status as CampaignStatus,
    createdAt: r.created_at as string,
    completedAt: r.completed_at as string | undefined,
    totalLeads: (r.total_leads as number) ?? 0,
    keptLeads: (r.kept_leads as number) ?? 0,
    withOwner: (r.with_owner as number) ?? 0,
    withEmail: (r.with_email as number) ?? 0,
    spendUsd: (r.spend_usd as number) ?? 0,
    triggeredBy: (r.triggered_by as string) ?? "DG",
  }));
}

export default async function CampaignsPage() {
  const campaigns = await fetchCampaigns();
  const running = campaigns.filter((c) => c.status === "running");
  const recent = campaigns.filter((c) => c.status !== "running");

  const totalLeads = campaigns.reduce((sum, c) => sum + c.keptLeads, 0);
  const totalSpend = campaigns.reduce((sum, c) => sum + c.spendUsd, 0);

  return (
    <div className="mx-auto max-w-7xl px-6 py-10">
      <div className="flex flex-wrap items-end justify-between gap-4 pb-8">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Campaigns</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Runs initiated by your team. Each campaign produces a FindyMail-ready CSV when it completes.
          </p>
        </div>
        <Button asChild>
          <Link href="/campaigns/new">
            <Plus className="mr-2 size-4" /> New campaign
          </Link>
        </Button>
      </div>

      <div className="grid gap-4 pb-8 sm:grid-cols-3">
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Active runs</CardDescription>
            <CardTitle className="text-2xl">{running.length}</CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Total leads kept (lifetime)</CardDescription>
            <CardTitle className="text-2xl">{totalLeads}</CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Spend (lifetime)</CardDescription>
            <CardTitle className="text-2xl">{formatCurrency(totalSpend)}</CardTitle>
          </CardHeader>
        </Card>
      </div>

      {running.length > 0 && (
        <section className="pb-10">
          <h2 className="pb-3 text-sm font-medium uppercase tracking-wider text-muted-foreground">
            In progress
          </h2>
          <div className="grid gap-3">
            {running.map((c) => (
              <Card key={c.id} className="transition-colors hover:border-brand/50">
                <CardContent className="flex flex-wrap items-center justify-between gap-4 p-4">
                  <div className="flex flex-col gap-1">
                    <div className="flex items-center gap-2">
                      <span className="font-medium">{c.city}, {c.stateAbbr}</span>
                      <Badge variant="outline" className={cn("border", STATUS_TONE[c.status])}>
                        running
                      </Badge>
                    </div>
                    <div className="text-sm text-muted-foreground">
                      {c.niche} · target {c.targetCount} · started {formatDate(c.createdAt)} · {c.triggeredBy}
                    </div>
                  </div>
                  <div className="flex items-center gap-6 text-sm">
                    <div>
                      <span className="text-muted-foreground">progress</span>{" "}
                      <span className="font-medium">{c.keptLeads} / {c.targetCount}</span>
                    </div>
                    <div>
                      <span className="text-muted-foreground">spend</span>{" "}
                      <span className="font-medium">{formatCurrency(c.spendUsd)}</span>
                    </div>
                    <Button asChild variant="outline" size="sm">
                      <Link href={`/campaigns/${c.id}`}>
                        Watch run <ArrowUpRight className="ml-1 size-3.5" />
                      </Link>
                    </Button>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        </section>
      )}

      <section>
        <h2 className="pb-3 text-sm font-medium uppercase tracking-wider text-muted-foreground">
          Recent
        </h2>
        {recent.length === 0 ? (
          <p className="py-8 text-center text-sm text-muted-foreground">
            No completed campaigns yet. <Link href="/campaigns/new" className="underline">Start one.</Link>
          </p>
        ) : (
          <div className="overflow-hidden rounded-lg border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>City</TableHead>
                  <TableHead>Niche</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="text-right">Kept / Total</TableHead>
                  <TableHead className="text-right">Owner</TableHead>
                  <TableHead className="text-right">Email</TableHead>
                  <TableHead className="text-right">Spend</TableHead>
                  <TableHead>When</TableHead>
                  <TableHead><span className="sr-only">Actions</span></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {recent.map((c) => (
                  <TableRow key={c.id}>
                    <TableCell className="font-medium">{c.city}, {c.stateAbbr}</TableCell>
                    <TableCell className="text-muted-foreground">{c.niche}</TableCell>
                    <TableCell>
                      <Badge variant="outline" className={cn("border capitalize", STATUS_TONE[c.status])}>
                        {c.status}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-right font-mono text-xs">
                      {c.keptLeads} / {c.totalLeads}
                    </TableCell>
                    <TableCell className="text-right font-mono text-xs">{c.withOwner}</TableCell>
                    <TableCell className="text-right font-mono text-xs">{c.withEmail}</TableCell>
                    <TableCell className="text-right font-mono text-xs">{formatCurrency(c.spendUsd)}</TableCell>
                    <TableCell className="text-muted-foreground">{formatDate(c.createdAt)}</TableCell>
                    <TableCell className="text-right">
                      <Button asChild variant="ghost" size="sm">
                        <Link href={`/campaigns/${c.id}/results`}>Open</Link>
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </section>
    </div>
  );
}
```

- [ ] **Step 2: Verify TypeScript**

```bash
cd frontend && bun run build 2>&1 | grep -E "^.*error" | head -10
```
Expected: no errors in campaigns/page.tsx

- [ ] **Step 3: Commit**

```bash
cd ..
git add frontend/app/campaigns/page.tsx
git commit -m "feat: wire campaigns list to FastAPI"
```

---

### Task 9: Wire New-Campaign Form

**Files:**
- Modify: `frontend/app/campaigns/new/page.tsx`

The form is already a client component. We replace the `handleStart` stub with a Server Action that POSTs to FastAPI and redirects to the new campaign's live run page. Because Server Actions run on the server, `VISTALINE_API_SECRET` stays out of the browser.

- [ ] **Step 1: Create the Server Action**

Create `frontend/app/campaigns/actions.ts`:

```typescript
"use server";

import { redirect } from "next/navigation";
import { currentUser } from "@clerk/nextjs/server";

export async function startCampaign(formData: {
  city: string;
  stateAbbr: string;
  niche: string;
  targetCount: number;
}) {
  const user = await currentUser();
  const triggeredBy =
    user?.firstName ??
    user?.emailAddresses?.[0]?.emailAddress?.split("@")[0] ??
    "User";

  const base = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
  const res = await fetch(`${base}/campaigns`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Api-Key": process.env.VISTALINE_API_SECRET ?? "",
    },
    body: JSON.stringify({
      city: formData.city,
      state_abbr: formData.stateAbbr,
      niche: formData.niche,
      target_count: formData.targetCount,
      triggered_by: triggeredBy,
    }),
  });

  if (!res.ok) {
    throw new Error(`Failed to create campaign: ${res.status}`);
  }

  const { id } = await res.json();
  redirect(`/campaigns/${id}`);
}
```

- [ ] **Step 2: Update handleStart in new/page.tsx**

Replace the `handleStart` function (and its imports):

Add this import at the top of `frontend/app/campaigns/new/page.tsx`:
```typescript
import { startCampaign } from "@/app/campaigns/actions";
```

Replace the `handleStart` function:
```typescript
  async function handleStart(e: React.FormEvent) {
    e.preventDefault();
    const niche = selected?.displayName ?? (isCustom ? customNiche : "");
    if (!city || !niche) return;
    await startCampaign({
      city,
      stateAbbr,
      niche,
      targetCount: count,
    });
  }
```

Also remove the old `useRouter` import and hook since the redirect happens server-side.

Remove this line:
```typescript
import { useRouter } from "next/navigation";
```
Remove this line in the component:
```typescript
  const router = useRouter();
```

- [ ] **Step 3: Verify TypeScript**

```bash
cd frontend && bun run build 2>&1 | grep -E "error" | grep -v "node_modules" | head -10
```
Expected: no errors

- [ ] **Step 4: Commit**

```bash
cd ..
git add frontend/app/campaigns/new/page.tsx frontend/app/campaigns/actions.ts
git commit -m "feat: wire new-campaign form to FastAPI via Server Action"
```

---

### Task 10: Wire Live Run Page (Supabase Realtime)

**Files:**
- Modify: `frontend/app/campaigns/[id]/page.tsx`

Convert from server component to client component. On mount, fetch the campaign + initial events from FastAPI. Subscribe to Supabase Realtime for live event inserts and campaign row updates. Derive step progress from `completed_steps`.

- [ ] **Step 1: Replace campaigns/[id]/page.tsx**

Replace the entire file:

```typescript
"use client";

import { use, useEffect, useState } from "react";
import Link from "next/link";
import { CheckCircle2, CircleDashed, CircleSlash, Loader2, XCircle, ArrowUpRight, Square } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { ScrollArea } from "@/components/ui/scroll-area";
import { getCampaign, getEvents } from "@/lib/api";
import { supabase } from "@/lib/supabase";
import type { Campaign, EventLevel, RunEvent, StepName, StepProgress, StepStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

const STEP_ORDER: StepName[] = ["sourcer", "lead_filter", "owner_researcher", "csv_assembler"];
const STEP_LABELS: Record<StepName, string> = {
  sourcer: "Sourcer",
  lead_filter: "Lead Filter",
  owner_researcher: "Owner Research",
  csv_assembler: "CSV Assembler",
};

const STEP_ICON: Record<StepStatus, React.ComponentType<{ className?: string }>> = {
  queued: CircleDashed,
  running: Loader2,
  done: CheckCircle2,
  failed: XCircle,
  skipped: CircleSlash,
};

const STEP_TONE: Record<StepStatus, string> = {
  queued: "text-muted-foreground",
  running: "text-info",
  done: "text-success",
  failed: "text-danger",
  skipped: "text-muted-foreground",
};

const EVENT_TONE: Record<EventLevel, string> = {
  info: "border-l-border",
  success: "border-l-success",
  warn: "border-l-warning",
  error: "border-l-danger",
};

function deriveSteps(completedSteps: string[], status: Campaign["status"]): StepProgress[] {
  const firstNotDone = STEP_ORDER.findIndex((s) => !completedSteps.includes(s));
  return STEP_ORDER.map((step, i) => {
    const isDone = completedSteps.includes(step);
    const isRunning = status === "running" && i === firstNotDone;
    const hasFailed = status === "failed" && i === firstNotDone;
    return {
      step,
      label: STEP_LABELS[step],
      status: isDone ? "done" : isRunning ? "running" : hasFailed ? "failed" : "queued",
    };
  });
}

function formatDuration(ms: number | undefined): string {
  if (!ms) return "";
  return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`;
}

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString(undefined, {
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
  });
}

export default function LiveRunPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);

  const [campaign, setCampaign] = useState<Campaign | null>(null);
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [loading, setLoading] = useState(true);

  // Initial fetch
  useEffect(() => {
    Promise.all([getCampaign(id), getEvents(id)])
      .then(([c, evts]) => {
        setCampaign(c);
        setEvents(evts.filter((e) => !e.message.startsWith("Querying ")));
      })
      .finally(() => setLoading(false));
  }, [id]);

  // Supabase Realtime — new events
  useEffect(() => {
    const channel = supabase
      .channel(`events-${id}`)
      .on(
        "postgres_changes",
        { event: "INSERT", schema: "public", table: "events", filter: `campaign_id=eq.${id}` },
        (payload) => {
          const r = payload.new as Record<string, unknown>;
          const evt: RunEvent = {
            id: r.id as string,
            step: r.step as StepName,
            level: (r.level as EventLevel) ?? "info",
            message: r.message as string,
            detail: r.detail as string | undefined,
            durationMs: r.duration_ms as number | undefined,
            ts: r.ts as string,
          };
          if (!evt.message.startsWith("Querying ")) {
            setEvents((prev) => [...prev, evt]);
          }
        },
      )
      .subscribe();
    return () => { supabase.removeChannel(channel); };
  }, [id]);

  // Supabase Realtime — campaign status / completed_steps updates
  useEffect(() => {
    const channel = supabase
      .channel(`campaign-${id}`)
      .on(
        "postgres_changes",
        { event: "UPDATE", schema: "public", table: "campaigns", filter: `id=eq.${id}` },
        (payload) => {
          const r = payload.new as Record<string, unknown>;
          setCampaign((prev) =>
            prev
              ? {
                  ...prev,
                  status: r.status as Campaign["status"],
                  keptLeads: (r.kept_leads as number) ?? prev.keptLeads,
                  totalLeads: (r.total_leads as number) ?? prev.totalLeads,
                  withOwner: (r.with_owner as number) ?? prev.withOwner,
                  withEmail: (r.with_email as number) ?? prev.withEmail,
                  completedAt: r.completed_at as string | undefined,
                }
              : prev,
          );
        },
      )
      .subscribe();
    return () => { supabase.removeChannel(channel); };
  }, [id]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-32 text-muted-foreground">
        <Loader2 className="mr-2 size-5 animate-spin" /> Loading campaign…
      </div>
    );
  }

  if (!campaign) {
    return (
      <div className="mx-auto max-w-7xl px-6 py-10 text-muted-foreground">
        Campaign not found.
      </div>
    );
  }

  const steps = deriveSteps(
    (campaign as unknown as { completed_steps?: string[] }).completed_steps ?? [],
    campaign.status,
  );
  const isLive = campaign.status === "running";

  return (
    <div className="mx-auto max-w-7xl px-6 py-10">
      <div className="flex flex-wrap items-end justify-between gap-4 pb-8">
        <div>
          <div className="flex items-center gap-2 pb-1">
            <Link href="/campaigns" className="text-sm text-muted-foreground hover:text-foreground">
              Campaigns
            </Link>
            <span className="text-muted-foreground">/</span>
            <span className="text-sm font-mono text-muted-foreground">{id.slice(0, 14)}</span>
          </div>
          <h1 className="text-2xl font-semibold tracking-tight">
            {campaign.city}, {campaign.stateAbbr}
            <span className="ml-2 text-base font-normal text-muted-foreground">
              · {campaign.niche}
            </span>
          </h1>
          <div className="mt-2 flex items-center gap-3 text-sm text-muted-foreground">
            <Badge
              variant="outline"
              className={cn(
                "capitalize",
                campaign.status === "running" && "border-info/30 bg-info/10 text-info",
                campaign.status === "completed" && "border-success/30 bg-success/10 text-success",
                campaign.status === "failed" && "border-danger/30 bg-danger/10 text-danger",
              )}
            >
              {campaign.status}
            </Badge>
            <span>target {campaign.targetCount}</span>
            <span>·</span>
            <span>started by {campaign.triggeredBy}</span>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {campaign.status === "completed" && (
            <Button asChild variant="outline" size="sm">
              <Link href={`/campaigns/${id}/results`}>
                View results <ArrowUpRight className="ml-1 size-3.5" />
              </Link>
            </Button>
          )}
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-[280px_1fr]">
        <aside className="space-y-1">
          <h2 className="px-1 pb-2 text-xs font-medium uppercase tracking-wider text-muted-foreground">
            Pipeline
          </h2>
          {steps.map((step, idx) => {
            const Icon = STEP_ICON[step.status];
            const isRunning = step.status === "running";
            return (
              <div
                key={step.step}
                className={cn(
                  "rounded-md border p-3 transition-colors",
                  isRunning ? "border-info/40 bg-info/5" : "border-transparent",
                )}
              >
                <div className="flex items-start gap-3">
                  <Icon
                    className={cn(
                      "mt-0.5 size-4 shrink-0",
                      STEP_TONE[step.status],
                      isRunning && "animate-spin",
                    )}
                  />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-sm font-medium">{step.label}</span>
                      <span className="text-xs text-muted-foreground">
                        {formatDuration(step.durationMs)}
                      </span>
                    </div>
                    {step.summary && (
                      <p className="mt-1 text-xs text-muted-foreground">{step.summary}</p>
                    )}
                    <p className="mt-1 text-xs uppercase tracking-wider text-muted-foreground">
                      step {idx + 1}/{steps.length} · {step.status}
                    </p>
                  </div>
                </div>
              </div>
            );
          })}
        </aside>

        <section>
          <Card className="overflow-hidden">
            <div className="flex items-center justify-between border-b border-border px-4 py-2.5">
              <div className="flex items-center gap-2 text-sm">
                {isLive && <span className="size-2 animate-pulse rounded-full bg-info" />}
                <span className="font-medium">Event stream</span>
                <span className="text-xs text-muted-foreground">{events.length} events</span>
              </div>
              <span className="font-mono text-xs text-muted-foreground">
                {isLive ? "Supabase Realtime · live" : campaign.status}
              </span>
            </div>
            <ScrollArea className="h-[560px]">
              <CardContent className="space-y-2 p-4">
                {events.length === 0 && (
                  <p className="py-8 text-center text-sm text-muted-foreground">
                    Waiting for first event…
                  </p>
                )}
                {events.map((evt) => (
                  <div
                    key={evt.id}
                    className={cn(
                      "flex items-start gap-3 rounded-md border-l-2 bg-muted/30 px-3 py-2 text-sm",
                      EVENT_TONE[evt.level],
                    )}
                  >
                    <span className="font-mono text-xs text-muted-foreground tabular-nums">
                      {formatTime(evt.ts)}
                    </span>
                    <Badge variant="outline" className="shrink-0 font-mono text-xs uppercase">
                      {evt.step}
                    </Badge>
                    <div className="min-w-0 flex-1">
                      <p>{evt.message}</p>
                      {evt.detail && (
                        <p className="mt-0.5 text-xs text-muted-foreground">{evt.detail}</p>
                      )}
                    </div>
                    {evt.durationMs && (
                      <span className="font-mono text-xs text-muted-foreground tabular-nums">
                        {formatDuration(evt.durationMs)}
                      </span>
                    )}
                  </div>
                ))}
                {isLive && (
                  <>
                    <Separator className="my-3" />
                    <p className="text-center text-xs text-muted-foreground">
                      Streaming live via Supabase Realtime.
                    </p>
                  </>
                )}
              </CardContent>
            </ScrollArea>
          </Card>
        </section>
      </div>
    </div>
  );
}
```

> **Note:** `campaign.completed_steps` is not in the frontend `Campaign` type (the type only has UI fields). We cast with `unknown` to access it from the raw API response. Alternatively, add `completedSteps?: string[]` to the `Campaign` type in `lib/types.ts` — that's cleaner.

- [ ] **Step 2: Add completedSteps to Campaign type**

In `frontend/lib/types.ts`, add `completedSteps?: string[]` to the `Campaign` interface after `triggeredBy`:

```typescript
export interface Campaign {
  // ... existing fields ...
  triggeredBy: string;
  completedSteps?: string[];  // populated from DB, optional for mock compat
}
```

Then update the `toCampaign` transformer in `api.ts` to include it:
```typescript
// In toCampaign(), add:
completedSteps: (r.completed_steps as string[]) ?? [],
```

And update `deriveSteps` in the live run page to use `campaign.completedSteps ?? []` directly instead of the cast.

- [ ] **Step 3: Verify TypeScript**

```bash
cd frontend && bun run build 2>&1 | grep -E "error" | grep -v "node_modules" | head -10
```
Expected: no errors

- [ ] **Step 4: Commit**

```bash
cd ..
git add frontend/app/campaigns/[id]/page.tsx frontend/lib/types.ts frontend/lib/api.ts
git commit -m "feat: live run page with Supabase Realtime event streaming"
```

---

### Task 11: Wire Results Page + CSV Download

**Files:**
- Modify: `frontend/app/campaigns/[id]/results/page.tsx`

Replace `MOCK_CAMPAIGNS` and `MOCK_LEADS` with real API calls. The `toggle()` function now PATCHes the API. The CSV download buttons link to the FastAPI CSV endpoints.

- [ ] **Step 1: Replace results/page.tsx**

Replace the entire file:

```typescript
"use client";

import { use, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Download, ExternalLink, Mail, Phone, Search, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { getCampaign, getLeads, patchLead, csvUrl } from "@/lib/api";
import type { Campaign, Lead } from "@/lib/types";
import { cn } from "@/lib/utils";

export default function ResultsPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);

  const [campaign, setCampaign] = useState<Campaign | null>(null);
  const [leads, setLeads] = useState<Lead[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");

  useEffect(() => {
    Promise.all([getCampaign(id), getLeads(id)])
      .then(([c, l]) => {
        setCampaign(c);
        setLeads(l);
      })
      .finally(() => setLoading(false));
  }, [id]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return leads;
    return leads.filter(
      (l) =>
        l.businessName.toLowerCase().includes(q) ||
        l.address.toLowerCase().includes(q) ||
        l.ownerFirst.toLowerCase().includes(q) ||
        l.ownerLast.toLowerCase().includes(q),
    );
  }, [leads, search]);

  function toggle(lead: Lead) {
    const next = !lead.excludedByUser;
    setLeads((prev) =>
      prev.map((l) => (l.id === lead.id ? { ...l, excludedByUser: next } : l)),
    );
    patchLead(id, lead.id, next).catch(() => {
      // revert on failure
      setLeads((prev) =>
        prev.map((l) => (l.id === lead.id ? { ...l, excludedByUser: lead.excludedByUser } : l)),
      );
    });
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-32 text-muted-foreground">
        <Loader2 className="mr-2 size-5 animate-spin" /> Loading results…
      </div>
    );
  }

  const kept = leads.filter((l) => l.kept);
  const ready = kept.filter((l) => !l.excludedByUser);
  const withEmail = ready.filter((l) => l.email).length;

  return (
    <div className="mx-auto max-w-7xl px-6 py-10">
      <div className="flex flex-wrap items-end justify-between gap-4 pb-8">
        <div>
          <div className="flex items-center gap-2 pb-1">
            <Link href="/campaigns" className="text-sm text-muted-foreground hover:text-foreground">
              Campaigns
            </Link>
            <span className="text-muted-foreground">/</span>
            <Link
              href={`/campaigns/${id}`}
              className="text-sm font-mono text-muted-foreground hover:text-foreground"
            >
              {id.slice(0, 14)}
            </Link>
            <span className="text-muted-foreground">/</span>
            <span className="text-sm">results</span>
          </div>
          <h1 className="text-2xl font-semibold tracking-tight">
            Results{campaign ? ` · ${campaign.city}, ${campaign.stateAbbr}` : ""}
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Review and trim before exporting to FindyMail. Unchecked rows won&apos;t be included.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button asChild variant="outline">
            <a href={csvUrl(id, "master")} download>
              <Download className="mr-2 size-4" /> Master CSV
            </a>
          </Button>
          <Button asChild>
            <a href={csvUrl(id, "findymail")} download>
              <Download className="mr-2 size-4" /> FindyMail CSV
            </a>
          </Button>
        </div>
      </div>

      <div className="grid gap-4 pb-8 sm:grid-cols-4">
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Ready for FindyMail</CardDescription>
            <CardTitle className="text-2xl">{ready.length}</CardTitle>
          </CardHeader>
          <CardContent className="text-xs text-muted-foreground">
            {withEmail} already have an email · saves that many FindyMail credits
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Kept by filter</CardDescription>
            <CardTitle className="text-2xl">{kept.length}</CardTitle>
          </CardHeader>
          <CardContent className="text-xs text-muted-foreground">of {leads.length} sourced</CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Excluded by you</CardDescription>
            <CardTitle className="text-2xl">{leads.filter((l) => l.excludedByUser).length}</CardTitle>
          </CardHeader>
          <CardContent className="text-xs text-muted-foreground">uncheck to add back</CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Total spend</CardDescription>
            <CardTitle className="text-2xl">${campaign?.spendUsd.toFixed(2) ?? "—"}</CardTitle>
          </CardHeader>
          <CardContent className="text-xs text-muted-foreground">
            Anthropic + source APIs
          </CardContent>
        </Card>
      </div>

      <div className="flex items-center justify-between pb-3">
        <div className="relative w-full max-w-sm">
          <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="Search business, owner, or address..."
            className="pl-9"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <div className="text-xs text-muted-foreground">
          showing {filtered.length} of {leads.length}
        </div>
      </div>

      <div className="overflow-hidden rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-10"><span className="sr-only">Include</span></TableHead>
              <TableHead>Business</TableHead>
              <TableHead>Owner</TableHead>
              <TableHead>Phone</TableHead>
              <TableHead>Website</TableHead>
              <TableHead>Email</TableHead>
              <TableHead>Status</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {filtered.map((lead) => {
              const isExcluded = lead.excludedByUser;
              const isFiltered = !lead.kept;
              return (
                <TableRow
                  key={lead.id}
                  className={cn((isExcluded || isFiltered) && "opacity-50")}
                >
                  <TableCell>
                    <Checkbox
                      checked={lead.kept && !isExcluded}
                      disabled={!lead.kept}
                      onCheckedChange={() => toggle(lead)}
                      aria-label={`Include ${lead.businessName}`}
                    />
                  </TableCell>
                  <TableCell>
                    <div className="font-medium">{lead.businessName}</div>
                    <div className="text-xs text-muted-foreground">{lead.address}</div>
                    {isFiltered && (
                      <div className="mt-1 text-xs text-danger">Filtered: {lead.rejectReason}</div>
                    )}
                  </TableCell>
                  <TableCell>
                    {lead.ownerFirst || lead.ownerLast ? (
                      <div>
                        <div>{lead.ownerFirst} {lead.ownerLast}</div>
                        {lead.ownerSource && (
                          <div className="text-xs text-muted-foreground">via {lead.ownerSource}</div>
                        )}
                      </div>
                    ) : (
                      <span className="text-xs text-muted-foreground">—</span>
                    )}
                  </TableCell>
                  <TableCell className="font-mono text-xs">
                    <a href={`tel:${lead.phone}`} className="inline-flex items-center gap-1 hover:text-foreground">
                      <Phone className="size-3" />
                      {lead.phone}
                    </a>
                  </TableCell>
                  <TableCell className="text-xs">
                    {lead.website ? (
                      <a href={lead.website} target="_blank" rel="noopener noreferrer"
                        className="inline-flex items-center gap-1 text-muted-foreground hover:text-foreground">
                        <ExternalLink className="size-3" />
                        {lead.domain}
                      </a>
                    ) : (
                      <span className="text-muted-foreground">—</span>
                    )}
                  </TableCell>
                  <TableCell className="text-xs">
                    {lead.email ? (
                      <span className="inline-flex items-center gap-1 text-success">
                        <Mail className="size-3" /> captured
                      </span>
                    ) : (
                      <span className="text-muted-foreground">needs FindyMail</span>
                    )}
                  </TableCell>
                  <TableCell>
                    {isFiltered ? (
                      <Badge variant="outline" className="border-danger/30 bg-danger/10 text-danger">filtered</Badge>
                    ) : isExcluded ? (
                      <Badge variant="outline" className="border-warning/30 bg-warning/10 text-warning">excluded</Badge>
                    ) : (
                      <Badge variant="outline" className="border-success/30 bg-success/10 text-success">ready</Badge>
                    )}
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verify TypeScript**

```bash
cd frontend && bun run build 2>&1 | grep -E "error" | grep -v "node_modules" | head -10
```
Expected: no errors

- [ ] **Step 3: Commit**

```bash
cd ..
git add frontend/app/campaigns/[id]/results/page.tsx
git commit -m "feat: wire results page to FastAPI — real leads, real CSV download"
```

---

### Task 12: Railway Deploy (Backend)

**Files:**
- Already created: `Procfile`
- Create: `railway.toml`

- [ ] **Step 1: Create railway.toml**

```toml
[build]
builder = "nixpacks"

[deploy]
startCommand = "uvicorn api.main:app --host 0.0.0.0 --port $PORT"
healthcheckPath = "/docs"
healthcheckTimeout = 30
restartPolicyType = "on_failure"
```

- [ ] **Step 2: Install Railway CLI and link project**

```bash
# Install Railway CLI
brew install railway

# Login
railway login

# Create project (first time) or link to existing
railway init
```

- [ ] **Step 3: Set environment variables on Railway**

```bash
railway variables set \
  ANTHROPIC_API_KEY="$(grep ANTHROPIC_API_KEY .env | cut -d= -f2-)" \
  GOOGLE_PLACES_KEY="$(grep GOOGLE_PLACES_KEY .env | cut -d= -f2-)" \
  SUPABASE_URL="$(grep SUPABASE_URL .env | cut -d= -f2-)" \
  SUPABASE_SERVICE_ROLE_KEY="$(grep SUPABASE_SERVICE_ROLE_KEY .env | cut -d= -f2-)" \
  VISTALINE_API_SECRET="$(grep VISTALINE_API_SECRET .env | cut -d= -f2-)"
```

Set optional keys if present:
```bash
railway variables set AZURE_MAPS_KEY="..." YELP_FUSION_KEY="..." BRAVE_SEARCH_KEY="..."
```

- [ ] **Step 4: Deploy**

```bash
railway up
```
Expected: build succeeds, deployment URL printed (e.g., `https://vistaline-api.up.railway.app`)

- [ ] **Step 5: Verify the deployed API**

```bash
RAILWAY_URL="https://vistaline-api.up.railway.app"
SECRET="$(grep VISTALINE_API_SECRET .env | cut -d= -f2-)"
curl -s -H "X-Api-Key: $SECRET" "$RAILWAY_URL/campaigns" | head -100
```
Expected: `[]` (empty array — no campaigns yet) or existing campaigns if any exist in Supabase

- [ ] **Step 6: Commit**

```bash
git add railway.toml
git commit -m "chore: add Railway deploy config"
```

---

### Task 13: Vercel Deploy (Frontend)

**Files:**
- No new files needed for basic Vercel deployment

- [ ] **Step 1: Install Vercel CLI**

```bash
bun add -g vercel
```

- [ ] **Step 2: Link and configure**

```bash
cd frontend && vercel link
```
Choose: new project, name it "vistaline-lead-sourcer-frontend", root directory is `frontend/`.

- [ ] **Step 3: Set environment variables on Vercel**

```bash
# Each command prompts for value and which environments (production/preview/development)
vercel env add NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY
vercel env add CLERK_SECRET_KEY
vercel env add NEXT_PUBLIC_CLERK_SIGN_IN_URL
vercel env add NEXT_PUBLIC_CLERK_AFTER_SIGN_IN_URL
vercel env add NEXT_PUBLIC_CLERK_AFTER_SIGN_UP_URL
vercel env add NEXT_PUBLIC_API_URL          # value: https://vistaline-api.up.railway.app
vercel env add VISTALINE_API_SECRET         # same as backend
vercel env add NEXT_PUBLIC_SUPABASE_URL
vercel env add NEXT_PUBLIC_SUPABASE_ANON_KEY
```

- [ ] **Step 4: Deploy to production**

```bash
cd frontend && vercel --prod
```
Expected: build succeeds, production URL printed (e.g., `https://vistaline-lead-sourcer.vercel.app`)

- [ ] **Step 5: Update CORS on Railway**

In `api/main.py`, tighten the CORS `allow_origins` to the Vercel URL:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://vistaline-lead-sourcer.vercel.app",
        "http://localhost:3000",  # local dev
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)
```

Redeploy backend:
```bash
cd .. && railway up
```

- [ ] **Step 6: Smoke test the full stack**

  1. Open the Vercel URL in a browser
  2. Sign in with Clerk
  3. The Campaigns page should load (empty state or real campaigns)
  4. Click "New campaign" → fill in Tampa, FL, Bathroom remodelers, 10 leads
  5. Click "Start campaign" → should redirect to the live run page
  6. Watch event stream populate in real time
  7. When complete, click "View results" → leads table should show
  8. Click "FindyMail CSV" → CSV should download

- [ ] **Step 7: Commit + tag**

```bash
git add api/main.py
git commit -m "chore: tighten CORS to Vercel production URL"
git tag v1.0.0-mvp
git push origin main --tags
```

---

## Self-Review

**Spec coverage:**
- ✅ Supabase Postgres replaces JSON-on-disk state
- ✅ Supabase Realtime provides live event streaming
- ✅ FastAPI wraps run.py without changing any agent code
- ✅ POST /campaigns launches pipeline in background (non-blocking)
- ✅ Leads persisted after pipeline completes
- ✅ CSV download (FindyMail + master) via API
- ✅ Exclude/include toggle persisted to DB
- ✅ Clerk auth on all frontend routes
- ✅ Railway deploy for backend
- ✅ Vercel deploy for frontend
- ✅ triggered_by comes from Clerk user

**Known gaps (acceptable for MVP):**
- `spend_usd` is always 0.00 — Anthropic token tracking not wired. Track usage callbacks from the Anthropic SDK in a future task.
- Cancel run button is UI-only — FastAPI does not expose a cancel endpoint. BackgroundTasks doesn't support cancellation natively; add a Redis/DB flag approach later.
- The API secret is in `csvUrl()` as a query parameter, visible in browser history. Acceptable for internal tool; upgrade to signed URLs later.
- E2E Playwright tests still use mocks — update to run against a staging Supabase project as a separate task.
