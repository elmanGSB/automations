# main.py
import hashlib
import hmac
import importlib
import logging
import sys
from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
import config as _config
from pipeline import process_meeting

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="Interview Router")

# Set the module-level secret only on first import.
# On reload (used in tests), preserve any existing value (e.g. from unittest.mock.patch).
if not hasattr(sys.modules[__name__], "FIREFLIES_WEBHOOK_SECRET"):
    FIREFLIES_WEBHOOK_SECRET: str = _config.FIREFLIES_WEBHOOK_SECRET


def _get_secret() -> str:
    """Return the current webhook secret, respecting any test patches on this module."""
    return sys.modules[__name__].FIREFLIES_WEBHOOK_SECRET


def verify_signature(payload: bytes, signature_header: str, secret: str) -> bool:
    """Verify Fireflies HMAC-SHA256 webhook signature."""
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header)


@app.post("/webhook/fireflies")
async def fireflies_webhook(request: Request, background_tasks: BackgroundTasks):
    body = await request.body()

    # Log raw body for debugging empty webhook payloads
    logger.info("Webhook raw body (%d bytes) from %s: %s",
                len(body), request.client.host if request.client else "unknown",
                body[:500].decode(errors="replace"))

    secret = _get_secret()
    if secret:
        signature = request.headers.get("x-hub-signature", "")
        if not verify_signature(body, signature, secret):
            raise HTTPException(status_code=401, detail="Invalid signature")

    payload = await request.json()
    event_type = payload.get("event", "")
    meeting_id = payload.get("meeting_id")

    logger.info("Received event: %s for meeting %s", event_type, meeting_id)

    if event_type != "meeting.transcribed":
        return {"status": "ignored", "event": event_type}

    if not meeting_id:
        raise HTTPException(status_code=400, detail="Missing meetingId")

    async def _run_pipeline(mid: str) -> None:
        try:
            await process_meeting(mid)
        except Exception:
            logger.exception("Pipeline failed for meeting %s", mid)

    background_tasks.add_task(_run_pipeline, meeting_id)
    return {"status": "accepted", "meetingId": meeting_id}  # meeting_id from payload


@app.get("/health")
def health():
    return {"status": "ok"}
