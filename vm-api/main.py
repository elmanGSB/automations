"""
VM API — central HTTP interface for Paperclip VM services.

Runs on port 3101. Consolidates:
  - /api/leads          — demo form submissions from broccolli.ai
  - /webhook/fireflies  — Fireflies meeting extraction trigger (called by Windmill)
  - /health, /health/full — liveness + dependency checks
  - /api/interviews     — read recent interviews

Deploy:
  gcloud compute scp --recurse /Users/elmanamador/coding/vm-api \
    paperclip-vm:~/ --zone=us-central1-f
  gcloud compute ssh paperclip-vm --zone=us-central1-f \
    -- 'sudo systemctl restart vm-api'
"""

import hashlib
import hmac
import logging
import os
from contextlib import asynccontextmanager

import asyncpg
import httpx
from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr

from discovery_extractor import process_discovery_meeting
from fireflies import FirefliesClient

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://paperclip:paperclip@127.0.0.1:5432/discovery",
)
FIREFLIES_API_KEY = os.environ.get("FIREFLIES_API_KEY", "")
FIREFLIES_WEBHOOK_SECRET = os.environ.get("FIREFLIES_WEBHOOK_SECRET", "")
VM_API_SECRET = os.environ.get("VM_API_SECRET", "")

pool: asyncpg.Pool | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global pool
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

def _verify_fireflies_signature(payload: bytes, signature_header: str) -> bool:
    """Verify Fireflies HMAC-SHA256 webhook signature. Skipped if secret not set."""
    if not FIREFLIES_WEBHOOK_SECRET:
        return True  # disabled — same behaviour as current interview-router
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(
        FIREFLIES_WEBHOOK_SECRET.encode(), payload, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header)


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


@app.get("/health/full")
async def health_full():
    checks: dict[str, str] = {}

    try:
        await pool.fetchval("SELECT 1")
        checks["postgres"] = "ok"
    except Exception as e:
        checks["postgres"] = f"error: {e}"

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.get("http://127.0.0.1:8199/health")
        checks["claude_proxy"] = "ok"  # any response means it's reachable
    except Exception as e:
        checks["claude_proxy"] = f"error: {e}"

    overall = "ok" if all(v == "ok" for v in checks.values()) else "degraded"
    return {"status": overall, "checks": checks}


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
    result = await pool.execute(
        "UPDATE discovery.leads SET pillar = $1 WHERE id = $2",
        body.pillar,
        lead_id,
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


# ---------------------------------------------------------------------------
# Fireflies webhook
# ---------------------------------------------------------------------------

@app.post("/webhook/fireflies", status_code=202, dependencies=[Depends(require_auth)])
async def fireflies_webhook(request: Request, background_tasks: BackgroundTasks):
    body = await request.body()

    logger.info(
        "Webhook (%d bytes) from %s: %s",
        len(body),
        request.client.host if request.client else "unknown",
        body[:200].decode(errors="replace"),
    )

    signature = request.headers.get("x-hub-signature", "")
    if not _verify_fireflies_signature(body, signature):
        raise HTTPException(status_code=401, detail="Invalid Fireflies signature")

    payload = await request.json()
    # Fireflies sends eventType/meetingId; also accept event/meeting_id (Windmill forward)
    event = payload.get("eventType") or payload.get("event", "")
    meeting_id = payload.get("meetingId") or payload.get("meeting_id")

    # Fireflies uses "Transcription complete"; Windmill may normalise to "meeting.transcribed"
    if event not in ("Transcription complete", "meeting.transcribed"):
        return {"status": "ignored", "event": event}

    if not meeting_id:
        raise HTTPException(status_code=400, detail="Missing meeting_id")

    background_tasks.add_task(_run_extraction, meeting_id)
    return {"status": "accepted", "meeting_id": meeting_id}


async def _run_extraction(meeting_id: str) -> None:
    """Background task: fetch transcript from Fireflies + run extraction pipeline."""
    if not FIREFLIES_API_KEY:
        logger.error("FIREFLIES_API_KEY not set — cannot fetch transcript for %s", meeting_id)
        return
    if pool is None:
        logger.error("DB pool not initialised — cannot run extraction for %s", meeting_id)
        return
    client = FirefliesClient(FIREFLIES_API_KEY)
    try:
        transcript = await client.fetch_transcript(meeting_id)

        # Format sentences into plain text
        transcript_text = "\n".join(
            f"{s.speaker_name}: {s.text}" for s in transcript.sentences
        )
        # First participant is typically the interviewee
        participant_name = transcript.participants[0] if transcript.participants else "Unknown"
        meeting_date = transcript.date[:10] if transcript.date else None

        result = await process_discovery_meeting(
            pool=pool,
            transcript_text=transcript_text,
            participant_name=participant_name,
            meeting_title=transcript.title,
            meeting_date=meeting_date,
            fireflies_meeting_id=meeting_id,
        )
        logger.info("Extraction complete for %s: %s", meeting_id, result)
    except Exception:
        logger.exception("Extraction failed for meeting %s", meeting_id)
    finally:
        await client.aclose()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=3101)
