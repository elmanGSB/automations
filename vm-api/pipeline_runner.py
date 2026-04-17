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
import logging
import tempfile
from datetime import date as date_type

import asyncpg

from analyzer import analyze_novel
from classifier import classify_meeting
from config import FIREFLIES_API_KEY, INTERNAL_TEAM_NAMES, NLM_ENABLED_CATEGORIES
from discovery_extractor import process_discovery_meeting
from emailer import send_novel_report
from fireflies import FirefliesClient
from hindsight import retain_meeting, retain_novel_insights
from notebooklm import add_pdf_source, create_notebook, notebook_title_for_category
from notifier import notify_new_category
from pdf_generator import generate_transcript_pdf
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
            from datetime import timezone
            return date_type.fromtimestamp(raw / 1000, tz=timezone.utc).isoformat()
        return str(raw)[:10]
    except Exception:
        logger.warning("Could not parse meeting date %r, falling back to today", raw)
        return str(date_type.today())


logger = logging.getLogger(__name__)

# In-flight guard: prevents concurrent webhook retries from starting duplicate runs
_in_flight: set[str] = set()


def _run_on_loop(coro, loop: asyncio.AbstractEventLoop):
    """Submit a coroutine to a running event loop from this threadpool thread.

    Required for pool-bound coroutines (asyncpg) that must run on the loop
    that owns the connection pool. Non-pool coroutines can use asyncio.run().
    """
    return asyncio.run_coroutine_threadsafe(coro, loop).result()


def run_meeting_pipeline(
    meeting_id: str, pool: asyncpg.Pool, loop: asyncio.AbstractEventLoop
) -> dict:
    """
    Run full pipeline for a meeting. Returns structured dict with status per step.
    Windmill displays this dict as the job result.

    Plain def — runs in FastAPI threadpool. All blocking I/O (subprocess, HTTP) is safe here.
    loop: the FastAPI event loop that owns the asyncpg pool.
    """
    # Fast in-flight check (in-memory, no file I/O)
    if meeting_id in _in_flight:
        logger.info("Meeting %s already in-flight, skipping concurrent run", meeting_id)
        return {"status": "skipped", "reason": "in_flight", "meeting_id": meeting_id}
    _in_flight.add(meeting_id)

    try:
        return _run_pipeline(meeting_id, pool, loop)
    finally:
        _in_flight.discard(meeting_id)


def _run_pipeline(
    meeting_id: str, pool: asyncpg.Pool, loop: asyncio.AbstractEventLoop
) -> dict:
    # Read-only idempotency check — does not claim the meeting yet.
    # Marking happens after the NLM upload succeeds so transient failures are retryable.
    if is_meeting_processed(meeting_id):
        logger.info("Meeting %s already processed, skipping", meeting_id)
        return {"status": "skipped", "reason": "already_processed", "meeting_id": meeting_id}

    result: dict = {"meeting_id": meeting_id, "title": None, "category": None, "steps": {}}

    # Step 1: Fetch transcript
    client = FirefliesClient(api_key=FIREFLIES_API_KEY)
    try:
        transcript = asyncio.run(client.fetch_transcript(meeting_id))
        result["title"] = transcript.title
        result["steps"]["fetch"] = {"status": "ok", "title": transcript.title}
        logger.info("Fetched: '%s'", transcript.title)
    except Exception:
        logger.exception("Fetch step failed for meeting %s", meeting_id)
        result["steps"]["fetch"] = {"status": "error", "error": "fetch_failed"}
        return result
    finally:
        asyncio.run(client.aclose())

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
    try:
        classification = asyncio.run(classify_meeting(
            title=transcript.title,
            participants=transcript.participants,
            summary=transcript.summary_overview,
            transcript_excerpt=labeled_transcript,
        ))
        result["category"] = classification.category
        result["steps"]["classify_meeting"] = {
            "status": "ok",
            "category": classification.category,
            "confidence": classification.confidence,
            "reasoning": classification.reasoning,
        }
        logger.info("Classified as '%s' (%s)", classification.category, classification.confidence)
    except Exception:
        logger.exception("Classification failed for meeting %s", meeting_id)
        result["steps"]["classify_meeting"] = {"status": "error", "error": "classify_failed"}
        return result

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

    # Steps 5-11: NLM upload, analysis, and email — only for categories where
    # novel insight extraction makes sense (has external interviewees).
    # Classes, team-syncs, etc. skip this entire block.
    nlm_enabled = classification.category in NLM_ENABLED_CATEGORIES
    analysis = None

    if not nlm_enabled:
        skipped = {"status": "skipped", "reason": f"category={classification.category}"}
        for key in ("notebooklm_notebook", "notebooklm_upload", "nlm_analysis", "email"):
            result["steps"][key] = skipped
    else:
        # Step 5: Get or create NotebookLM notebook
        try:
            nb_title = notebook_title_for_category(classification.category)
            notebook_id, is_new_notebook = get_or_create_notebook_id(
                classification.category,
                lambda: create_notebook(nb_title),
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

        # Step 6: Generate PDF and upload to notebook (idempotent via _nlm_uploaded state)
        try:
            if is_nlm_uploaded(meeting_id):
                logger.info("Meeting %s PDF already uploaded, skipping", meeting_id)
                result["steps"]["notebooklm_upload"] = {
                    "status": "skipped",
                    "reason": "already_uploaded",
                }
            else:
                with tempfile.TemporaryDirectory() as tmpdir:
                    pdf_path = generate_transcript_pdf(transcript, tmpdir, role_map=role_map)
                    add_pdf_source(notebook_id, pdf_path, transcript.title)
                mark_nlm_uploaded(meeting_id)
                result["steps"]["notebooklm_upload"] = {"status": "ok"}
        except Exception:
            logger.exception("NLM upload failed for meeting %s", meeting_id)
            result["steps"]["notebooklm_upload"] = {"status": "error", "error": "upload_failed"}
            return result

        # Step 7: Query novel insights
        try:
            analysis = analyze_novel(notebook_id)
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
    if nlm_enabled and is_new_notebook and classification.is_new_category:
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
