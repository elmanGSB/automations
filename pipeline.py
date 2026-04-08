import logging
import tempfile
from config import FIREFLIES_API_KEY
from fireflies import FirefliesClient
from classifier import classify_meeting
from pdf_generator import generate_transcript_pdf
from notebooklm import create_notebook, add_pdf_source, notebook_title_for_category
from state import get_notebook_id, save_notebook_id
from notifier import notify_new_category
from hindsight import retain_meeting, retain_novel_insights
from analyzer import analyze_notebook
from emailer import send_meeting_report

logger = logging.getLogger(__name__)


async def process_meeting(meeting_id: str) -> None:
    """Full pipeline: fetch → classify → PDF → upload to NotebookLM."""
    logger.info("Processing meeting %s", meeting_id)

    # 1. Fetch transcript from Fireflies
    client = FirefliesClient(api_key=FIREFLIES_API_KEY)
    transcript = await client.fetch_transcript(meeting_id)
    logger.info("Fetched transcript: '%s'", transcript.title)

    # 2. Classify the meeting
    excerpt = " ".join(s.text for s in transcript.sentences[:20])
    result = await classify_meeting(
        title=transcript.title,
        participants=transcript.participants,
        summary=transcript.summary_overview,
        transcript_excerpt=excerpt,
    )
    logger.info(
        "Classified as '%s' (%s): %s", result.category, result.confidence, result.reasoning
    )

    # 3. Get or create the notebook for this category
    notebook_id = get_notebook_id(result.category)
    is_new_notebook = notebook_id is None

    if is_new_notebook:
        title = notebook_title_for_category(result.category)
        logger.info("Creating new notebook: '%s'", title)
        notebook_id = create_notebook(title)
        save_notebook_id(result.category, notebook_id)
        logger.info("Created notebook %s", notebook_id)

    # 4. Generate PDF and upload (use temp dir so file is cleaned up after upload)
    with tempfile.TemporaryDirectory() as tmpdir:
        pdf_path = generate_transcript_pdf(transcript, tmpdir)
        logger.info("Generated PDF: %s", pdf_path)
        add_pdf_source(notebook_id, pdf_path, transcript.title)
        logger.info("Uploaded PDF to notebook %s", notebook_id)

    # 5. Run both analysis prompts against the notebook
    analysis = analyze_notebook(notebook_id)
    logger.info("Completed notebook analysis")

    # 6. Email report to both founders
    await send_meeting_report(transcript.title, result.category, analysis)

    # 7. Retain meeting context + novel insights in Hindsight
    await retain_meeting(transcript, result)
    await retain_novel_insights(transcript.title, result.category, analysis.novel)
    logger.info("Retained insights in Hindsight memory bank")

    # 8. Notify only if notebook was newly created AND category is unknown
    if is_new_notebook and result.is_new_category:
        await notify_new_category(
            category=result.category,
            meeting_title=transcript.title,
            meeting_id=meeting_id,
            notebook_id=notebook_id,
        )
        logger.info("Sent notification for new category '%s'", result.category)
