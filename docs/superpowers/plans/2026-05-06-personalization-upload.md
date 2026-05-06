# Personalization Upload Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let operators upload a FindyMail-enriched CSV on the campaign results page, which writes emails onto existing leads and automatically runs X/Y personalization and LinkedIn lookup, then makes an agency-format CSV available for download.

**Architecture:** Two new FastAPI endpoints (`POST /campaigns/{id}/enrich` and `GET /campaigns/{id}/leads/agency.csv`) backed by a new background runner module. The frontend adds an upload button and a conditional agency CSV download button to the existing results page, plus polling when the campaign is personalizing.

**Tech Stack:** FastAPI (BackgroundTasks, UploadFile), Python csv module, existing `agents/personalizer.py` + `agents/linkedin_finder.py`, Next.js 16 (React 19), shadcn/ui Button, Lucide icons.

---

## File map

| File | Change |
|------|--------|
| `api/runner_personalize.py` | **Create** — async wrapper that runs personalizer + linkedin_finder in a thread |
| `api/main.py` | **Modify** — add two new endpoints after existing leads endpoints |
| `tests/test_enrich_domain_matching.py` | **Create** — unit tests for domain normalisation helper |
| `frontend/lib/types.ts` | **Modify** — add `"personalizing"` to `CampaignStatus`; add personalization fields to `Lead` |
| `frontend/lib/api.ts` | **Modify** — add `uploadEnrichedCsv()` and `agencyCsvUrl()` |
| `frontend/app/campaigns/[id]/results/page.tsx` | **Modify** — upload button, polling, agency CSV download button |

---

### Task 1: Agency CSV endpoint

**Files:**
- Modify: `api/main.py` (after line 192, the end of the file)

- [ ] **Step 1: Write the test**

Create `tests/test_agency_csv_columns.py`:

```python
"""Smoke-check that the agency CSV column list matches csv_agency.AGENCY_COLUMNS."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from agents.csv_agency import AGENCY_COLUMNS

EXPECTED = [
    "Total", "Lead Sourcer", "Business", "Owner Full Name",
    "First", "Last", "Owner Email", "LinkedIn", "Website",
    "Phone", "Date", "X Project", "Y Detail",
]

assert AGENCY_COLUMNS == EXPECTED, f"Column mismatch: {AGENCY_COLUMNS}"
print("OK — agency CSV columns match")
```

- [ ] **Step 2: Run it to verify it passes (columns already exist)**

```bash
python tests/test_agency_csv_columns.py
```

Expected: `OK — agency CSV columns match`

- [ ] **Step 3: Add the agency CSV endpoint to `api/main.py`**

Add at the top of `api/main.py`, alongside the existing import:
```python
from datetime import date
```

Then append after the `download_master_csv` function (after line 192):

```python
@app.get("/campaigns/{campaign_id}/leads/agency.csv")
def download_agency_csv(campaign_id: str, _: AuthDep):
    """Agency-format CSV: 13 columns, Instantly-ready."""
    db = get_supabase()
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
    writer = csv.DictWriter(buf, fieldnames=[
        "Total", "Lead Sourcer", "Business", "Owner Full Name",
        "First", "Last", "Owner Email", "LinkedIn", "Website",
        "Phone", "Date", "X Project", "Y Detail",
    ])
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
```

- [ ] **Step 4: Smoke-test imports**

```bash
python -c "from api.main import app; print('OK')"
```

Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add api/main.py tests/test_agency_csv_columns.py
git commit -m "feat: GET /campaigns/{id}/leads/agency.csv endpoint"
```

---

### Task 2: Domain matching helper + enrich endpoint + background runner

**Files:**
- Create: `api/runner_personalize.py`
- Create: `tests/test_enrich_domain_matching.py`
- Modify: `api/main.py`

- [ ] **Step 1: Write domain normalisation tests**

Create `tests/test_enrich_domain_matching.py`:

```python
"""Unit tests for _normalise_domain — the key to matching enriched CSV rows to leads."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def _normalise_domain(raw: str) -> str:
    """Strip protocol, www., and trailing slashes. Lowercase. Copy of api/main.py helper."""
    d = (raw or "").strip().lower()
    for prefix in ("https://", "http://"):
        if d.startswith(prefix):
            d = d[len(prefix):]
    if d.startswith("www."):
        d = d[4:]
    return d.rstrip("/")


cases = [
    ("andrewroby.com",          "andrewroby.com"),
    ("www.andrewroby.com",      "andrewroby.com"),
    ("https://andrewroby.com",  "andrewroby.com"),
    ("https://www.andrewroby.com/", "andrewroby.com"),
    ("ANDREWROBY.COM",          "andrewroby.com"),
    ("",                        ""),
    (None,                      ""),  # type: ignore[arg-type]
]

for raw, expected in cases:
    result = _normalise_domain(raw)  # type: ignore[arg-type]
    assert result == expected, f"_normalise_domain({raw!r}) = {result!r}, want {expected!r}"

print("OK — all domain normalisation cases pass")
```

- [ ] **Step 2: Run test to verify it passes**

```bash
python tests/test_enrich_domain_matching.py
```

Expected: `OK — all domain normalisation cases pass`

- [ ] **Step 3: Create `api/runner_personalize.py`**

```python
"""Background runner for the post-FindyMail personalization flow.

Mirrors api/runner.py. Called by BackgroundTasks after POST /campaigns/{id}/enrich
writes emails onto leads and sets campaign status to "personalizing".
"""
from __future__ import annotations
import asyncio

from config import CONFIG
from state import CampaignState
from agents import personalizer, linkedin_finder


async def run_personalization(campaign_id: str) -> None:
    """Launch personalization for campaign_id in a thread (non-blocking)."""
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _run_sync, campaign_id)


def _run_sync(campaign_id: str) -> None:
    state = CampaignState.load(campaign_id)
    try:
        # Clear personalizer/linkedin_finder checkpoints so they re-run even if
        # a previous personalization attempt was made.
        state.completed_steps = [
            s for s in state.completed_steps
            if s not in (personalizer.STEP_NAME, linkedin_finder.STEP_NAME)
        ]
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
        state.save_leads()
        state.status = "completed"
        state.save()
    except Exception as exc:
        state.status = "failed"
        state.info("runner_personalize", f"Personalization failed: {exc}", level="error")
        state.save()
        raise
```

- [ ] **Step 4: Verify import**

```bash
python -c "from api.runner_personalize import run_personalization; print('OK')"
```

Expected: `OK`

- [ ] **Step 5: Add the enrich endpoint to `api/main.py`**

Add `UploadFile` to the fastapi imports at line 7:

```python
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, UploadFile
```

Add `from datetime import date` if not already present (added in Task 1).

Add the `_normalise_domain` helper and the import for the new runner just below the existing imports (after the `from api.runner import run_pipeline` line):

```python
from api.runner_personalize import run_personalization


def _normalise_domain(raw: str) -> str:
    """Strip protocol, www., and trailing slash; lowercase. Used to match enriched CSV to leads."""
    d = (raw or "").strip().lower()
    for prefix in ("https://", "http://"):
        if d.startswith(prefix):
            d = d[len(prefix):]
    if d.startswith("www."):
        d = d[4:]
    return d.rstrip("/")
```

Append the endpoint after `download_agency_csv`:

```python
@app.post("/campaigns/{campaign_id}/enrich", status_code=202)
async def enrich_campaign(
    campaign_id: str,
    file: UploadFile,
    background_tasks: BackgroundTasks,
    _: AuthDep,
):
    """Accept a FindyMail-returned CSV, match emails to leads by domain, start personalizer."""
    db = get_supabase()

    row = db.table("campaigns").select("id").eq("id", campaign_id).single().execute().data
    if not row:
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
```

- [ ] **Step 6: Smoke-test imports**

```bash
python -c "from api.main import app; print('OK')"
```

Expected: `OK`

- [ ] **Step 7: Commit**

```bash
git add api/runner_personalize.py api/main.py tests/test_enrich_domain_matching.py
git commit -m "feat: POST /campaigns/{id}/enrich + background personalization runner"
```

---

### Task 3: Frontend types and API client

**Files:**
- Modify: `frontend/lib/types.ts`
- Modify: `frontend/lib/api.ts`

- [ ] **Step 1: Update `CampaignStatus` and `Lead` in `frontend/lib/types.ts`**

Change line 1 from:
```typescript
export type CampaignStatus = "queued" | "running" | "completed" | "failed";
```
to:
```typescript
export type CampaignStatus = "queued" | "running" | "personalizing" | "completed" | "failed";
```

Add three fields to the `Lead` interface (after `rejectReason: string;`):
```typescript
  xProject: string;
  yDetail: string;
  personalizationStatus: string;
```

- [ ] **Step 2: Update `toLead` transformer and add new API functions in `frontend/lib/api.ts`**

In the `toLead` function, add three fields after `rejectReason`:
```typescript
    xProject: (r.x_project as string) ?? "",
    yDetail: (r.y_detail as string) ?? "",
    personalizationStatus: (r.personalization_status as string) ?? "",
```

Add `agencyCsvUrl` alongside the existing `csvUrl` function:
```typescript
export function agencyCsvUrl(campaignId: string): string {
  return `/api/proxy/campaigns/${campaignId}/leads/agency.csv`;
}
```

Add `uploadEnrichedCsv` after `agencyCsvUrl`. Note: do NOT set `Content-Type` — the browser sets the correct `multipart/form-data` boundary automatically when using `FormData`.
```typescript
export async function uploadEnrichedCsv(
  campaignId: string,
  file: File,
): Promise<{ ok: boolean; matched: number; unmatched: number }> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`/api/proxy/campaigns/${campaignId}/enrich`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`API ${res.status}: ${text}`);
  }
  return res.json();
}
```

- [ ] **Step 3: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -30
```

Expected: no errors (exit 0, no output).

- [ ] **Step 4: Commit**

```bash
git add frontend/lib/types.ts frontend/lib/api.ts
git commit -m "feat: personalization types + uploadEnrichedCsv / agencyCsvUrl API client"
```

---

### Task 4: Results page — upload button, status polling, agency CSV download

**Files:**
- Modify: `frontend/app/campaigns/[id]/results/page.tsx`

- [ ] **Step 1: Add imports**

At the top of `frontend/app/campaigns/[id]/results/page.tsx`, add `useRef` to the React import:
```typescript
import { use, useEffect, useMemo, useRef, useState } from "react";
```

Add `Upload` and `Sparkles` to the lucide-react import:
```typescript
import { Download, ExternalLink, Mail, Phone, Search, Loader2, Sparkles, Upload } from "lucide-react";
```

Add new API functions to the lib/api import:
```typescript
import { getCampaign, getLeads, patchLead, agencyCsvUrl, uploadEnrichedCsv } from "@/lib/api";
```

- [ ] **Step 2: Add upload state and file input ref**

After the existing `const [search, setSearch] = useState("");` line, add:
```typescript
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
```

- [ ] **Step 3: Add polling effect**

Add a new `useEffect` after the existing data-loading `useEffect`:
```typescript
  // Poll campaign status while personalization is running.
  useEffect(() => {
    if (!campaign || campaign.status !== "personalizing") return;
    const interval = setInterval(() => {
      getCampaign(id)
        .then((c) => {
          setCampaign(c);
          if (c.status === "completed" || c.status === "failed") {
            getLeads(id).then(setLeads).catch(() => {});
          }
        })
        .catch(() => {});
    }, 10_000);
    return () => clearInterval(interval);
  }, [campaign?.status, id]);
```

- [ ] **Step 4: Add upload handler**

Add the `handleEnrichedUpload` function after the existing `toggle` function:
```typescript
  async function handleEnrichedUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    setUploadError(null);
    try {
      await uploadEnrichedCsv(id, file);
      setCampaign((c) => (c ? { ...c, status: "personalizing" } : c));
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }
```

- [ ] **Step 5: Add hidden file input and update the button row**

Locate the existing button row (lines 114–121 of the original file):
```tsx
        <div className="flex items-center gap-2">
          <Button variant="outline" onClick={() => downloadCsv("master")}>
            <Download className="mr-2 size-4" /> Master CSV
          </Button>
          <Button onClick={() => downloadCsv("findymail")}>
            <Download className="mr-2 size-4" /> FindyMail CSV
          </Button>
        </div>
```

Replace with:
```tsx
        <div className="flex items-center gap-2">
          <Button variant="outline" onClick={() => downloadCsv("master")}>
            <Download className="mr-2 size-4" /> Master CSV
          </Button>
          <Button variant="outline" onClick={() => downloadCsv("findymail")}>
            <Download className="mr-2 size-4" /> FindyMail CSV
          </Button>
          {campaign?.status === "completed" && campaign.withEmail > 0 && (
            <a href={agencyCsvUrl(id)} download={`agency-${id}.csv`}>
              <Button>
                <Sparkles className="mr-2 size-4" /> Agency CSV
              </Button>
            </a>
          )}
          <Button
            variant="outline"
            disabled={uploading || campaign?.status === "personalizing"}
            onClick={() => fileInputRef.current?.click()}
          >
            {uploading ? (
              <><Loader2 className="mr-2 size-4 animate-spin" /> Uploading…</>
            ) : (
              <><Upload className="mr-2 size-4" /> Upload enriched CSV</>
            )}
          </Button>
          <input
            ref={fileInputRef}
            type="file"
            accept=".csv"
            className="hidden"
            onChange={handleEnrichedUpload}
          />
        </div>
```

- [ ] **Step 6: Add personalizing status banner and upload error**

Find the stats cards grid (the `<div className="grid gap-4 pb-8 sm:grid-cols-4">` block). Insert the following banner and error display directly above it:

```tsx
      {campaign?.status === "personalizing" && (
        <div className="mb-4 flex items-center gap-2 rounded-lg border border-blue-500/30 bg-blue-500/10 px-4 py-3 text-sm text-blue-400">
          <Loader2 className="size-4 animate-spin" />
          Personalization running — X Project, Y Detail, and LinkedIn being filled. Checking every 10 seconds…
        </div>
      )}
      {uploadError && (
        <div className="mb-4 rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
          {uploadError}
        </div>
      )}
```

- [ ] **Step 7: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -30
```

Expected: no errors.

- [ ] **Step 8: Commit**

```bash
git add frontend/app/campaigns/[id]/results/page.tsx
git commit -m "feat: upload enriched CSV + agency CSV download on results page"
```

---

## Smoke test (after all tasks)

Run against a real completed campaign:

```bash
# 1. Start the API locally
uvicorn api.main:app --reload

# 2. In the frontend, open a completed campaign's results page
# 3. Click "FindyMail CSV" → upload to FindyMail → download enriched CSV
# 4. Click "Upload enriched CSV" → select the enriched file
# 5. Verify the status banner appears ("Personalization running…")
# 6. Wait for status to return to "completed"
# 7. Click "Agency CSV" → verify 13-column CSV with X Project / Y Detail filled
```

Alternatively, test the enrich endpoint directly:

```bash
curl -X POST http://localhost:8000/campaigns/<id>/enrich \
  -H "X-Api-Key: $VISTALINE_API_SECRET" \
  -F "file=@path/to/enriched.csv"
# Expected: {"ok":true,"matched":N,"unmatched":M}
```
