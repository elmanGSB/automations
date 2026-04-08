import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call
from fireflies import Transcript, Sentence
from classifier import ClassificationResult
from analyzer import AnalysisResult


def make_transcript(meeting_id="abc123") -> Transcript:
    return Transcript(
        id=meeting_id,
        title="Discovery call - Acme Corp",
        date="2026-04-07T14:00:00Z",
        duration=1800,
        participants=["alice@acme.com"],
        sentences=[
            Sentence(0, "Alice", "Tell me about pricing.", 5.0, 8.0),
            Sentence(1, "Me", "Sure.", 8.5, 9.0),
        ],
        summary_overview="Pricing discussion.",
        summary_action_items=["Send deck"],
        summary_keywords=["pricing"],
    )


MOCK_ANALYSIS = AnalysisResult(patterns="Mock patterns output", novel="Mock novel insights")


async def test_pipeline_routes_to_existing_notebook():
    """Known category with existing notebook: no create, no notify."""
    transcript = make_transcript()
    classification = ClassificationResult(
        category="customer-discovery", confidence="high", reasoning="Sales call"
    )

    with (
        patch("pipeline.FirefliesClient") as MockFF,
        patch("pipeline.classify_meeting", new_callable=AsyncMock, return_value=classification),
        patch("pipeline.generate_transcript_pdf", return_value="/tmp/t.pdf"),
        patch("pipeline.get_notebook_id", return_value="nb-existing"),
        patch("pipeline.create_notebook") as mock_create,
        patch("pipeline.save_notebook_id") as mock_save,
        patch("pipeline.add_pdf_source") as mock_add,
        patch("pipeline.analyze_notebook", return_value=MOCK_ANALYSIS),
        patch("pipeline.send_meeting_report", new_callable=AsyncMock),
        patch("pipeline.retain_meeting", new_callable=AsyncMock),
        patch("pipeline.retain_novel_insights", new_callable=AsyncMock),
        patch("pipeline.notify_new_category", new_callable=AsyncMock) as mock_notify,
    ):
        MockFF.return_value.fetch_transcript = AsyncMock(return_value=transcript)
        from pipeline import process_meeting
        await process_meeting("abc123")

    mock_create.assert_not_called()
    mock_save.assert_not_called()
    mock_add.assert_called_once_with("nb-existing", "/tmp/t.pdf", transcript.title)
    mock_notify.assert_not_called()


async def test_pipeline_creates_notebook_for_new_known_category():
    """Known category but no notebook yet: create notebook, save ID, no notify."""
    transcript = make_transcript()
    classification = ClassificationResult(
        category="investor-calls", confidence="high", reasoning="VC meeting"
    )

    with (
        patch("pipeline.FirefliesClient") as MockFF,
        patch("pipeline.classify_meeting", new_callable=AsyncMock, return_value=classification),
        patch("pipeline.generate_transcript_pdf", return_value="/tmp/t.pdf"),
        patch("pipeline.get_notebook_id", return_value=None),
        patch("pipeline.create_notebook", return_value="nb-new") as mock_create,
        patch("pipeline.save_notebook_id") as mock_save,
        patch("pipeline.add_pdf_source"),
        patch("pipeline.analyze_notebook", return_value=MOCK_ANALYSIS),
        patch("pipeline.send_meeting_report", new_callable=AsyncMock),
        patch("pipeline.retain_meeting", new_callable=AsyncMock),
        patch("pipeline.retain_novel_insights", new_callable=AsyncMock),
        patch("pipeline.notify_new_category", new_callable=AsyncMock) as mock_notify,
    ):
        MockFF.return_value.fetch_transcript = AsyncMock(return_value=transcript)
        from pipeline import process_meeting
        await process_meeting("abc123")

    mock_create.assert_called_once()
    mock_save.assert_called_once_with("investor-calls", "nb-new")
    mock_notify.assert_not_called()


async def test_pipeline_creates_notebook_and_notifies_for_unknown_category():
    """Unknown category: create notebook, save ID, send notification."""
    transcript = make_transcript()
    classification = ClassificationResult(
        category="conference-panel", confidence="medium", reasoning="Panel event"
    )

    with (
        patch("pipeline.FirefliesClient") as MockFF,
        patch("pipeline.classify_meeting", new_callable=AsyncMock, return_value=classification),
        patch("pipeline.generate_transcript_pdf", return_value="/tmp/t.pdf"),
        patch("pipeline.get_notebook_id", return_value=None),
        patch("pipeline.create_notebook", return_value="nb-panel"),
        patch("pipeline.save_notebook_id"),
        patch("pipeline.add_pdf_source"),
        patch("pipeline.analyze_notebook", return_value=MOCK_ANALYSIS),
        patch("pipeline.send_meeting_report", new_callable=AsyncMock),
        patch("pipeline.retain_meeting", new_callable=AsyncMock),
        patch("pipeline.retain_novel_insights", new_callable=AsyncMock),
        patch("pipeline.notify_new_category", new_callable=AsyncMock) as mock_notify,
    ):
        MockFF.return_value.fetch_transcript = AsyncMock(return_value=transcript)
        from pipeline import process_meeting
        await process_meeting("abc123")

    mock_notify.assert_called_once_with(
        category="conference-panel",
        meeting_title=transcript.title,
        meeting_id="abc123",
        notebook_id="nb-panel",
    )


async def test_pipeline_passes_excerpt_to_classifier():
    """Classifier receives first 20 sentences joined as excerpt."""
    transcript = make_transcript()
    classification = ClassificationResult(
        category="customer-discovery", confidence="high", reasoning="x"
    )

    captured = {}

    async def capture_classify(**kwargs):
        captured.update(kwargs)
        return classification

    with (
        patch("pipeline.FirefliesClient") as MockFF,
        patch("pipeline.classify_meeting", side_effect=capture_classify),
        patch("pipeline.generate_transcript_pdf", return_value="/tmp/t.pdf"),
        patch("pipeline.get_notebook_id", return_value="nb-x"),
        patch("pipeline.add_pdf_source"),
        patch("pipeline.analyze_notebook", return_value=MOCK_ANALYSIS),
        patch("pipeline.send_meeting_report", new_callable=AsyncMock),
        patch("pipeline.retain_meeting", new_callable=AsyncMock),
        patch("pipeline.retain_novel_insights", new_callable=AsyncMock),
        patch("pipeline.notify_new_category", new_callable=AsyncMock),
    ):
        MockFF.return_value.fetch_transcript = AsyncMock(return_value=transcript)
        from pipeline import process_meeting
        await process_meeting("abc123")

    assert captured["title"] == transcript.title
    assert captured["participants"] == transcript.participants
    assert "Tell me about pricing." in captured["transcript_excerpt"]
