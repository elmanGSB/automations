"""
VM API — central HTTP interface for Paperclip VM services.

Runs on port 3101. Consolidates:
  - /api/leads          — demo form submissions from broccolli.ai
  - /api/pipeline/run   — full discovery pipeline (Windmill calls this on Fireflies events)
  - /api/digest/run     — weekly aggregate patterns analysis for all NLM notebooks
  - /health, /health/full — liveness + dependency checks
  - /api/interviews     — read recent interviews

Deploy:
  gcloud compute scp --recurse /Users/elmanamador/coding/vm-api \
    paperclip-vm:~/ --zone=us-central1-f
  gcloud compute ssh paperclip-vm --zone=us-central1-f \
    -- 'sudo systemctl restart vm-api'
"""

import asyncio
import logging
import os
import re
from contextlib import asynccontextmanager
from typing import Any

import asyncpg
import httpx
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field

from analyzer import analyze_patterns
from config import NLM_ENABLED_CATEGORIES
from emailer import send_patterns_report
from pipeline_runner import run_meeting_pipeline
from state import get_all_notebooks

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://paperclip:paperclip@127.0.0.1:5432/discovery",
)
FIREFLIES_API_KEY = os.environ.get("FIREFLIES_API_KEY", "")
VM_API_SECRET = os.environ.get("VM_API_SECRET", "")

pool: asyncpg.Pool | None = None
app_event_loop: asyncio.AbstractEventLoop | None = None

_UUID_RE = re.compile(r'^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$')


@asynccontextmanager
async def lifespan(app: FastAPI):
    global pool, app_event_loop
    app_event_loop = asyncio.get_running_loop()
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
    yield
    await pool.close()


app = FastAPI(title="VM API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://broccolli.ai",
        "http://localhost:4321",
        "https://app.windmill.dev",
    ],
    allow_methods=["POST", "PATCH", "GET", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

async def require_auth(authorization: str = Header(default="")):
    """Bearer token guard for internal endpoints called by Windmill."""
    if not VM_API_SECRET:
        raise HTTPException(status_code=500, detail="VM_API_SECRET not configured")
    if authorization != f"Bearer {VM_API_SECRET}":
        raise HTTPException(status_code=401, detail="Unauthorized")


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/health/full", dependencies=[Depends(require_auth)])
async def health_full():
    checks: dict[str, str] = {}

    try:
        await pool.fetchval("SELECT 1")
        checks["postgres"] = "ok"
    except Exception:
        checks["postgres"] = "error: connection failed"

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.get("http://127.0.0.1:8199/health")
        checks["claude_proxy"] = "ok"  # any response means it's reachable
    except Exception:
        checks["claude_proxy"] = "error: connection failed"

    overall = "ok" if all(v == "ok" for v in checks.values()) else "degraded"
    return {"status": overall, "checks": checks}


# ---------------------------------------------------------------------------
# Pipeline endpoint (replaces black-box interview-router)
# ---------------------------------------------------------------------------

class PipelineRunRequest(BaseModel):
    meeting_id: str


@app.post("/api/pipeline/run", dependencies=[Depends(require_auth)])
def run_pipeline_endpoint(req: PipelineRunRequest):
    """Synchronous pipeline — runs in FastAPI threadpool (plain def).
    Returns structured per-step results displayed as Windmill job output.
    """
    if pool is None or app_event_loop is None:
        raise HTTPException(status_code=503, detail="App not initialized")
    return run_meeting_pipeline(req.meeting_id, pool, app_event_loop)


# ---------------------------------------------------------------------------
# Digest endpoint
# ---------------------------------------------------------------------------

@app.post("/api/digest/run", dependencies=[Depends(require_auth)])
def run_digest_endpoint() -> dict[str, Any]:
    """Run weekly aggregate patterns analysis for all NLM-enabled notebooks.

    Plain def — runs in FastAPI threadpool. Subprocess calls (nlm CLI) are safe here.
    Uses run_coroutine_threadsafe to dispatch async email via the main event loop.
    """
    if app_event_loop is None:
        raise HTTPException(status_code=503, detail="App not initialized")

    notebooks = get_all_notebooks()
    results: dict[str, Any] = {}

    for category in NLM_ENABLED_CATEGORIES:
        notebook_id = notebooks.get(category)
        if not notebook_id:
            results[category] = {"status": "skipped", "reason": "no_notebook"}
            continue
        if not _UUID_RE.match(notebook_id):
            logger.error("Invalid notebook_id format for category %s: %r", category, notebook_id)
            results[category] = {"status": "error", "error": "invalid_notebook_id"}
            continue
        try:
            patterns = analyze_patterns(notebook_id)
            asyncio.run_coroutine_threadsafe(
                send_patterns_report(category, patterns), app_event_loop
            ).result(timeout=30)
            results[category] = {"status": "ok", "patterns_char_count": len(patterns)}
        except Exception:
            logger.exception("Digest failed for category %s (non-fatal)", category)
            results[category] = {"status": "error", "error": "digest_failed"}

    return {"status": "completed", "results": results}


# ---------------------------------------------------------------------------
# Leads (migrated from leads_service.py)
# ---------------------------------------------------------------------------

class LeadCreate(BaseModel):
    name: str
    email: EmailStr
    phone: str = ""
    company: str = ""
    company_size: str = ""


class LeadPatch(BaseModel):
    pillar: str
    custom_focus: str | None = Field(None, max_length=2000)


@app.post("/api/leads", status_code=201)
async def create_lead(body: LeadCreate):
    row = await pool.fetchrow(
        """
        INSERT INTO discovery.leads (name, email, phone, company, company_size)
        VALUES ($1, $2, $3, $4, $5)
        RETURNING id
        """,
        body.name,
        body.email,
        body.phone,
        body.company,
        body.company_size,
    )
    return {"id": row["id"]}


@app.patch("/api/leads/{lead_id}", status_code=200)
async def update_lead_pillar(lead_id: int, body: LeadPatch):
    # exclude_unset: only update fields the client actually sent
    # prevents writing NULL to custom_focus for non-custom pillar selections
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=422, detail="No fields provided to update")

    set_parts = [f"{col} = ${i + 1}" for i, col in enumerate(updates)]
    params = list(updates.values()) + [lead_id]

    result = await pool.execute(
        f"UPDATE discovery.leads SET {', '.join(set_parts)} WHERE id = ${len(params)}",
        *params,
    )
    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail="Lead not found")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Interviews (read-only)
# ---------------------------------------------------------------------------

@app.get("/api/interviews", dependencies=[Depends(require_auth)])
async def list_interviews(limit: int = 20):
    rows = await pool.fetch(
        """
        SELECT id, date, participant_name, participant_role, company_name,
               interviewee_type, behavioral_segment, summary, created_at
        FROM discovery.interviews
        ORDER BY id DESC
        LIMIT $1
        """,
        limit,
    )
    return [dict(r) for r in rows]


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=3101)
