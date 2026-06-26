"""
Full meeting pipeline: fetch → classify speakers → classify meeting →
discovery extraction → NotebookLM → email → mark processed → Hindsight.

Returns a structured dict of per-step results so Windmill can display each stage.

IMPORTANT: This function is a plain `def` (not async) intentionally.
FastAPI runs plain `def` endpoint handlers in a thread pool via run_in_threadpool.
The nlm CLI subprocess calls block for up to 3 minutes — using async def here
would stall the event loop and freeze all other vm-api endpoints.
"""
import asyncio
import json
import logging
import os
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
from datetime import date as date_type, datetime, timezone

import asyncpg

from analyzer import analyze_novel
from classifier import ClassifyAuthError, classify_meeting
from config import (
    FIREFLIES_API_KEY,
    INTERNAL_TEAM_NAMES,
    NLM_ANALYSIS_CATEGORIES,
    NLM_UPLOAD_CATEGORIES,
)
from discovery_extractor import process_discovery_meeting
from docx_generator import generate_transcript_docx
from emailer import send_novel_report
from fireflies import FirefliesClient
from hindsight import retain_meeting, retain_novel_insights
from notebooklm import (
    add_file_source,
    create_notebook,
    find_notebook_by_title,
    notebook_title_for_category,
)
from notifier import notify_new_category
from speaker_roles import classify_speakers
from state import (
    get_or_create_notebook_id,
    is_meeting_processed,
    is_nlm_uploaded,
    mark_meeting_processed,
    mark_nlm_uploaded,
)
from transcript_formatter import format_external_with_context, format_with_roles


def _meeting_date(raw) -> str:
    """Return YYYY-MM-DD from a Fireflies date field (ms timestamp or ISO string).
    Falls back to today when Fireflies provides no date.
    """
    if not raw:
        return str(date_type.today())
    try:
        if isinstance(raw, (int, float)):
            return datetime.fromtimestamp(raw / 1000, tz=timezone.utc).date().isoformat()
        return str(raw)[:10]
    except Exception:
        logger.warning("Could not parse meeting date %r, falling back to today", raw)
        return str(date_type.today())


logger = logging.getLogger(__name__)

# In-flight guard: prevents concurrent webhook retries from starting duplicate runs
_in_flight: set[str] = set()

_GCP_PROJECT = os.environ.get("GCP_PROJECT", "paperclip-tribuai")
_CREDS_SECRET = os.environ.get("CLAUDE_CREDS_SECRET", "claude-code-credentials")
_CREDS_PATH = os.path.expanduser("~/.claude/.credentials.json")

_OAUTH_TOKEN_URL = "https://console.anthropic.com/v1/oauth/token"
_OAUTH_CLIENT_ID = os.environ.get("CLAUDE_OAUTH_CLIENT_ID", "9d1c250a-e61b-44d9-88ed-5944d1962f5e")
_OAUTH_DEFAULT_EXPIRES_IN = 8 * 3600  # 8h fallback if Anthropic omits expires_in
# Serialises concurrent credential refreshes: prevents two simultaneous 401s from
# both consuming the same refresh_token and having the loser overwrite the winner.
_CREDS_LOCK = threading.Lock()
_OAUTH_HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Origin": "https://claude.ai",
    "Referer": "https://claude.ai/",
    "Accept": "application/json, text/plain, */*",
}


def _oauth_refresh(creds: dict) -> dict | None:
    """Exchange a refresh_token for a fresh access_token via Claude's OAuth endpoint.

    Returns an updated credentials dict on success, None on failure.
    The VM calls this directly so it self-heals without needing the Mac to sync.
    Caller must hold _CREDS_LOCK before calling to prevent token rotation races.
    """
    refresh_token = creds.get("claudeAiOauth", {}).get("refreshToken")
    if not refresh_token:
        logger.warning("No refreshToken in credentials — cannot do OAuth refresh")
        return None

    body = json.dumps({
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": _OAUTH_CLIENT_ID,
    }).encode()

    req = urllib.request.Request(_OAUTH_TOKEN_URL, data=body, headers=_OAUTH_HEADERS, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body_text = e.read().decode(errors="replace")
        try:
            err = json.loads(body_text)
            logger.error("OAuth refresh HTTP %d: %s — %s", e.code, err.get("error", "?"), err.get("error_description", ""))
            if err.get("error") == "invalid_grant":
                logger.critical(
                    "OAuth refresh_token is EXPIRED or revoked — manual credential rotation required. "
                    "Run `claude /login` on the Mac then re-run sync-claude-creds.sh."
                )
        except Exception:
            logger.error("OAuth refresh HTTP %d: %s", e.code, body_text[:200])
        return None
    except Exception:
        logger.exception("OAuth refresh request failed")
        return None

    if "access_token" not in data:
        logger.error("OAuth refresh: unexpected response keys: %s", list(data.keys()))
        return None

    expires_in = data.get("expires_in", _OAUTH_DEFAULT_EXPIRES_IN)
    updated = dict(creds)
    updated["claudeAiOauth"] = dict(creds.get("claudeAiOauth", {}))
    updated["claudeAiOauth"]["accessToken"] = data["access_token"]
    updated["claudeAiOauth"]["expiresAt"] = int((time.time() + expires_in) * 1000)
    if "refresh_token" in data:
        updated["claudeAiOauth"]["refreshToken"] = data["refresh_token"]
    return updated


def _write_creds_atomic(data: dict | str) -> None:
    """Write credentials to _CREDS_PATH atomically with restricted permissions.

    Uses write-to-temp + os.replace to avoid a truncated file on crash.
    Caller must hold _CREDS_LOCK.
    """
    creds_dir = os.path.dirname(_CREDS_PATH)
    os.makedirs(creds_dir, exist_ok=True)
    tmp_path = _CREDS_PATH + ".tmp"
    with open(tmp_path, "w") as f:
        if isinstance(data, dict):
            json.dump(data, f)
        else:
            f.write(data)
    os.chmod(tmp_path, 0o600)
    os.replace(tmp_path, _CREDS_PATH)


def _refresh_claude_credentials() -> bool:
    """Refresh Claude Code credentials, trying OAuth refresh first then Secret Manager.

    Strategy:
    1. Acquire _CREDS_LOCK to serialise concurrent refreshes (prevents token rotation race).
    2. Read current credentials from disk (they include the refreshToken).
    3. Call Claude's OAuth token endpoint to swap the refresh_token for a fresh
       access_token — no Mac sync or browser required.
    4. Write the updated credentials back to disk atomically with 0o600 permissions.
    5. If OAuth refresh fails (e.g. refresh_token itself expired), fall back to
       pulling the latest blob from GCP Secret Manager (requires the Mac to have
       synced recently).

    Called automatically when classify_meeting raises ClassifyAuthError.
    """
    with _CREDS_LOCK:
        # --- Primary path: OAuth refresh token ---
        try:
            with open(_CREDS_PATH) as f:
                creds = json.load(f)
            refreshed = _oauth_refresh(creds)
            if refreshed:
                _write_creds_atomic(refreshed)
                logger.info("Claude credentials refreshed via OAuth refresh_token")
                return True
            logger.warning("OAuth refresh failed — falling back to Secret Manager")
        except Exception:
            logger.exception("Error during OAuth refresh attempt — falling back to Secret Manager")

        # --- Fallback: pull latest blob from GCP Secret Manager ---
        try:
            result = subprocess.run(
                [
                    "gcloud", "secrets", "versions", "access", "latest",
                    f"--secret={_CREDS_SECRET}",
                    f"--project={_GCP_PROJECT}",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                logger.error("Secret Manager pull failed (rc=%d): %s", result.returncode, result.stderr[:300])
                return False
            _write_creds_atomic(result.stdout)
            logger.info("Claude credentials refreshed from Secret Manager (%s)", _CREDS_SECRET)
            return True
        except Exception:
            logger.exception("Unexpected error refreshing Claude credentials from Secret Manager")
            return False


def _run_on_loop(coro, loop: asyncio.AbstractEventLoop):
    """Submit a coroutine to a running event loop from this threadpool thread.

    Required for pool-bound coroutines (asyncpg) that must run on the loop
    that owns the connection pool. Non-pool coroutines can use asyncio.run().
    """
    return asyncio.run_coroutine_threadsafe(coro, loop).result()


def run_meeting_pipeline(
    meeting_id: str,
    pool: asyncpg.Pool,
    loop: asyncio.AbstractEventLoop,
    force: bool = False,
) -> dict:
    """
    Run full pipeline for a meeting. Returns structured dict with status per step.
    Windmill displays this dict as the job result.

    Plain def — runs in FastAPI threadpool. All blocking I/O (subprocess, HTTP) is safe here.
    loop: the FastAPI event loop that owns the asyncpg pool.
    force: bypass the is_meeting_processed early-return so backfills can re-run
        on meetings the prior pipeline marked done. Upload-level idempotency
        (is_nlm_uploaded) still prevents duplicate sources.
    """
    # Fast in-flight check (in-memory, no file I/O).
    # force does NOT bypass this — concurrent retries should still dedup.
    if meeting_id in _in_flight:
        logger.info("Meeting %s already in-flight, skipping concurrent run", meeting_id)
        return {"status": "skipped", "reason": "in_flight", "meeting_id": meeting_id}
    _in_flight.add(meeting_id)

    try:
        return _run_pipeline(meeting_id, pool, loop, force=force)
    finally:
        _in_flight.discard(meeting_id)


def _run_pipeline(
    meeting_id: str,
    pool: asyncpg.Pool,
    loop: asyncio.AbstractEventLoop,
    force: bool = False,
) -> dict:
    # Read-only idempotency check — does not claim the meeting yet.
    # Marking happens after the NLM upload succeeds so transient failures are retryable.
    if not force and is_meeting_processed(meeting_id):
        logger.info("Meeting %s already processed, skipping", meeting_id)
        return {"status": "skipped", "reason": "already_processed", "meeting_id": meeting_id}

    result: dict = {"meeting_id": meeting_id, "title": None, "category": None, "steps": {}}

    # Step 1: Fetch transcript
    # httpx client must live and die on a single event loop — using two separate
    # asyncio.run() calls for fetch + aclose crashes with "Event loop is closed".
    async def _fetch_with_cleanup():
        client = FirefliesClient(api_key=FIREFLIES_API_KEY)
        try:
            return await client.fetch_transcript(meeting_id)
        finally:
            await client.aclose()

    try:
        transcript = asyncio.run(_fetch_with_cleanup())
        result["title"] = transcript.title
        result["steps"]["fetch"] = {"status": "ok", "title": transcript.title}
        logger.info("Fetched: '%s'", transcript.title)
    except Exception:
        logger.exception("Fetch step failed for meeting %s", meeting_id)
        result["steps"]["fetch"] = {"status": "error", "error": "fetch_failed"}
        return result

    # Step 2: Classify speakers
    role_map = classify_speakers(transcript.sentences, INTERNAL_TEAM_NAMES)
    external_speakers = [k for k, v in role_map.items() if v == "external"]
    internal_speakers = [k for k, v in role_map.items() if v == "internal"]
    labeled_transcript = format_with_roles(transcript.sentences, role_map)
    external_transcript = format_external_with_context(transcript.sentences, role_map)
    result["steps"]["classify_speakers"] = {
        "status": "ok",
        "external_speakers": external_speakers,
        "internal_speakers": internal_speakers,
    }

    # Step 3: Classify meeting type
    def _do_classify():
        return asyncio.run(classify_meeting(
            title=transcript.title,
            participants=transcript.participants,
            summary=transcript.summary_overview,
            transcript_excerpt=labeled_transcript,
        ))

    try:
        classification = _do_classify()
    except ClassifyAuthError:
        logger.warning("Claude auth expired for meeting %s — refreshing credentials and retrying", meeting_id)
        if _refresh_claude_credentials():
            try:
                classification = _do_classify()
                result["steps"]["classify_meeting_auth_refreshed"] = {"status": "ok"}
            except Exception:
                logger.exception("Classification still failed after credential refresh for %s", meeting_id)
                result["steps"]["classify_meeting"] = {"status": "error", "error": "auth_refresh_failed"}
                return result
        else:
            logger.error("Credential refresh failed — cannot classify meeting %s", meeting_id)
            result["steps"]["classify_meeting"] = {"status": "error", "error": "auth_expired_no_refresh"}
            return result
    except Exception:
        logger.exception("Classification failed for meeting %s", meeting_id)
        result["steps"]["classify_meeting"] = {"status": "error", "error": "classify_failed"}
        return result

    result["category"] = classification.category
    result["steps"]["classify_meeting"] = {
        "status": "ok",
        "category": classification.category,
        "confidence": classification.confidence,
        "reasoning": classification.reasoning,
    }
    logger.info("Classified as '%s' (%s)", classification.category, classification.confidence)

    # Step 4: Discovery extraction (customer-discovery only)
    # Guard: skip if no external speakers or no external transcript content
    if classification.category == "customer-discovery":
        if not external_speakers or not external_transcript.strip():
            logger.warning(
                "Meeting %s is customer-discovery but has no identifiable external speakers — "
                "skipping extraction to avoid writing fabricated data",
                meeting_id,
            )
            result["steps"]["discovery_extraction"] = {
                "status": "skipped",
                "reason": "no_external_speakers",
            }
        else:
            try:
                participant_name = external_speakers[0]
                discovery = _run_on_loop(
                    process_discovery_meeting(
                        pool=pool,
                        transcript_text=external_transcript,
                        participant_name=participant_name,
                        meeting_title=transcript.title,
                        meeting_date=_meeting_date(transcript.date),
                        fireflies_meeting_id=meeting_id,
                    ),
                    loop,
                )
                result["steps"]["discovery_extraction"] = {"status": "ok", **discovery}
            except Exception:
                logger.exception("Discovery extraction failed for meeting %s (non-fatal)", meeting_id)
                result["steps"]["discovery_extraction"] = {"status": "error", "error": "extraction_failed"}
    else:
        result["steps"]["discovery_extraction"] = {
            "status": "skipped",
            "reason": f"category={classification.category}",
        }

    # Steps 5-8: NLM block, gated in two stages.
    #   Upload (notebook + source) runs for any KNOWN category so classes,
    #   investor calls, etc. accumulate searchable archives. Ad-hoc/unknown
    #   categories skip entirely to avoid orphan notebooks.
    #   Analysis + email run only for customer-discovery — other categories
    #   have no [INTERVIEWEE] speaker, so the novel-insights prompt returns noise.
    upload_enabled = classification.category in NLM_UPLOAD_CATEGORIES
    analysis_enabled = classification.category in NLM_ANALYSIS_CATEGORIES
    notebook_id = None
    is_new_notebook = False
    analysis = None

    if not upload_enabled:
        skipped = {"status": "skipped", "reason": f"category={classification.category}"}
        for key in ("notebooklm_notebook", "notebooklm_upload", "nlm_analysis", "email"):
            result["steps"][key] = skipped
    else:
        # Step 5: Get or create NotebookLM notebook
        try:
            nb_title = notebook_title_for_category(classification.category)
            notebook_id, is_new_notebook = get_or_create_notebook_id(
                classification.category,
                create_fn=lambda: create_notebook(nb_title),
                lookup_fn=lambda: find_notebook_by_title(nb_title),
            )
            result["steps"]["notebooklm_notebook"] = {
                "status": "ok",
                "notebook_id": notebook_id,
                "is_new": is_new_notebook,
            }
        except Exception:
            logger.exception("NotebookLM notebook step failed for meeting %s", meeting_id)
            result["steps"]["notebooklm_notebook"] = {"status": "error", "error": "notebook_failed"}
            return result

        # Step 6: Generate DOCX and upload to notebook (idempotent via _nlm_uploaded state)
        try:
            if is_nlm_uploaded(meeting_id):
                logger.info("Meeting %s transcript already uploaded, skipping", meeting_id)
                result["steps"]["notebooklm_upload"] = {
                    "status": "skipped",
                    "reason": "already_uploaded",
                }
            else:
                with tempfile.TemporaryDirectory() as tmpdir:
                    docx_path = generate_transcript_docx(transcript, tmpdir, role_map=role_map)
                    add_file_source(notebook_id, docx_path, transcript.title)
                mark_nlm_uploaded(meeting_id)
                result["steps"]["notebooklm_upload"] = {"status": "ok"}
        except Exception:
            logger.exception("NLM upload failed for meeting %s", meeting_id)
            result["steps"]["notebooklm_upload"] = {"status": "error", "error": "upload_failed"}
            return result

        # Title override: meetings titled "Internal:" suppress analysis+email
        # even when the classifier returns customer-discovery. Elman uses this
        # prefix for team-internal recordings, and the classifier sometimes
        # overrides based on content — firing a misleading novel-insights email.
        internal_title_override = bool(
            transcript.title and transcript.title.strip().lower().startswith("internal:")
        )

        if not analysis_enabled or internal_title_override:
            reason = "internal_title" if internal_title_override else f"category={classification.category}"
            skipped = {"status": "skipped", "reason": reason}
            result["steps"]["nlm_analysis"] = skipped
            result["steps"]["email"] = skipped
        else:
            # Step 7: Query novel insights
            try:
                analysis = analyze_novel(
                    notebook_id,
                    title=transcript.title,
                    date=_meeting_date(transcript.date),
                    participants=list(transcript.participants or []),
                )
                result["steps"]["nlm_analysis"] = {
                    "status": "ok",
                    "novel_length": len(analysis.novel),
                }
                result["novel_insights"] = analysis.novel
            except Exception:
                logger.exception("NLM analysis failed for meeting %s", meeting_id)
                result["steps"]["nlm_analysis"] = {"status": "error", "error": "analysis_failed"}
                return result

            # Step 8: Email report (non-fatal; guard against empty novel)
            if analysis.novel.strip():
                try:
                    asyncio.run(send_novel_report(transcript.title, classification.category, analysis.novel))
                    result["steps"]["email"] = {"status": "ok"}
                except Exception:
                    logger.exception("Email failed for meeting %s (non-fatal)", meeting_id)
                    result["steps"]["email"] = {"status": "error", "error": "email_failed"}
            else:
                logger.warning("Meeting %s: NLM returned empty novel insights — skipping email", meeting_id)
                result["steps"]["email"] = {"status": "skipped", "reason": "empty_novel"}

    # Step 9: Mark as processed — after NLM work (or skip), before Hindsight.
    mark_meeting_processed(meeting_id)
    result["steps"]["mark_processed"] = {"status": "ok"}
    logger.info("Meeting %s marked as processed", meeting_id)

    # Step 10: Retain in Hindsight (non-fatal)
    try:
        asyncio.run(retain_meeting(transcript, classification))
        if analysis is not None and analysis.novel.strip():
            asyncio.run(retain_novel_insights(transcript.title, classification.category, analysis.novel))
        result["steps"]["hindsight"] = {"status": "ok"}
    except Exception:
        logger.exception("Hindsight retention failed for meeting %s (non-fatal)", meeting_id)
        result["steps"]["hindsight"] = {"status": "error", "error": "hindsight_failed"}

    # Step 11: Notify on new unknown category (non-fatal)
    if upload_enabled and is_new_notebook and classification.is_new_category:
        try:
            notify_new_category(
                category=classification.category,
                meeting_title=transcript.title,
                meeting_id=meeting_id,
                notebook_id=notebook_id,
            )
            result["steps"]["notify"] = {"status": "ok"}
        except Exception:
            logger.exception("Telegram notify failed for meeting %s (non-fatal)", meeting_id)
            result["steps"]["notify"] = {"status": "error", "error": "notify_failed"}

    result["status"] = "completed"
    return result
