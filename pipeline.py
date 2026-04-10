import logging
import tempfile
from datetime import date as date_type
from config import FIREFLIES_API_KEY, INTERNAL_TEAM_NAMES
from fireflies import FirefliesClient
from classifier import classify_meeting
from pdf_generator import generate_transcript_pdf
from notebooklm import create_notebook, add_pdf_source, notebook_title_for_category
from state import get_notebook_id, save_notebook_id, is_meeting_processed, mark_meeting_processed
from notifier import notify_new_category
from hindsight import retain_meeting, retain_novel_insights
from analyzer import analyze_novel
from emailer import send_novel_report
from discovery_extractor import process_discovery_meeting
from speaker_roles import classify_speakers
from transcript_formatter import format_with_roles, format_external_with_context

logger = logging.getLogger(__name__)


async def process_meeting(meeting_id: str) -> None:
    """Full pipeline: fetch → classify speakers → PDF → upload → analyze → email."""
    if is_meeting_processed(meeting_id):
        logger.info("Meeting %s already processed, skipping", meeting_id)
        return

    logger.info("Processing meeting %s", meeting_id)

    # 1. Fetch transcript from Fireflies
    client = FirefliesClient(api_key=FIREFLIES_API_KEY)
    transcript = await client.fetch_transcript(meeting_id)
    logger.info("Fetched transcript: '%s'", transcript.title)

    # 2. Classify speakers (internal team vs external party)
    role_map = classify_speakers(transcript.sentences, INTERNAL_TEAM_NAMES)
    internal_speakers = [k for k, v in role_map.items() if v == "internal"]
    external_speakers = [k for k, v in role_map.items() if v == "external"]
    logger.info(
        "Speaker roles — internal: %s | external: %s",
        ", ".join(internal_speakers) or "(none)",
        ", ".join(external_speakers) or "(none)",
    )

    # 3. Build role-labeled transcript variants
    #    - labeled_transcript: full conversation with [BROCCOLI TEAM]/[INTERVIEWEE] tags (classifier, PDF)
    #    - external_transcript: [CONTEXT/QUESTION] + [INTERVIEWEE] only (discovery extraction)
    labeled_transcript = format_with_roles(transcript.sentences, role_map)
    external_transcript = format_external_with_context(transcript.sentences, role_map)

    # 4. Classify the meeting using labeled transcript so classifier ignores team questions
    result = await classify_meeting(
        title=transcript.title,
        participants=transcript.participants,
        summary=transcript.summary_overview,
        transcript_excerpt=labeled_transcript,
    )
    logger.info(
        "Classified as '%s' (%s): %s", result.category, result.confidence, result.reasoning
    )

    # 4b. If customer-discovery, run discovery extraction on external-only transcript
    if result.category == "customer-discovery":
        try:
            discovery_result = await process_discovery_meeting(
                transcript_text=external_transcript,
                participant_name=external_speakers[0] if external_speakers else "Unknown",
                meeting_title=transcript.title,
                meeting_date=str(date_type.today()),
                fireflies_meeting_id=meeting_id,
                role_map=role_map,
            )
            logger.info("Discovery extraction complete: %s", discovery_result)
        except Exception:
            logger.exception("Discovery extraction failed for meeting %s (continuing pipeline)", meeting_id)

    # 5. Get or create the notebook for this category
    notebook_id = get_notebook_id(result.category)
    is_new_notebook = notebook_id is None

    if is_new_notebook:
        title = notebook_title_for_category(result.category)
        logger.info("Creating new notebook: '%s'", title)
        notebook_id = create_notebook(title)
        save_notebook_id(result.category, notebook_id)
        logger.info("Created notebook %s", notebook_id)

    # 6. Generate PDF with role-labeled speakers and upload to NotebookLM
    with tempfile.TemporaryDirectory() as tmpdir:
        pdf_path = generate_transcript_pdf(transcript, tmpdir, role_map=role_map)
        logger.info("Generated PDF: %s", pdf_path)
        add_pdf_source(notebook_id, pdf_path, transcript.title)
        logger.info("Uploaded PDF to notebook %s", notebook_id)

    # 7. Run novel insights prompt (Prompt 2) only — patterns run weekly
    analysis = analyze_novel(notebook_id)
    logger.info("Completed novel insights analysis")

    # 8. Email novel insights report to both founders
    await send_novel_report(transcript.title, result.category, analysis.novel)

    # 9. Mark meeting as processed before retaining (so crashes don't re-run email)
    mark_meeting_processed(meeting_id)

    # 10. Retain meeting context + novel insights in Hindsight
    await retain_meeting(transcript, result)
    await retain_novel_insights(transcript.title, result.category, analysis.novel)
    logger.info("Retained insights in Hindsight memory bank")

    # 11. Notify only if notebook was newly created AND category is unknown
    if is_new_notebook and result.is_new_category:
        await notify_new_category(
            category=result.category,
            meeting_title=transcript.title,
            meeting_id=meeting_id,
            notebook_id=notebook_id,
        )
        logger.info("Sent notification for new category '%s'", result.category)
