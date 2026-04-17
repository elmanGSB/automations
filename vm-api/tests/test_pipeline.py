import pytest
from httpx import ASGITransport, AsyncClient
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_mock_transcript(meeting_id="abc123", title="Test Meeting"):
    transcript = MagicMock()
    transcript.id = meeting_id
    transcript.title = title
    transcript.date = "2026-04-17"
    transcript.duration = 3600
    transcript.participants = ["Elman", "Jane"]
    transcript.summary_overview = "A great meeting."
    transcript.summary_action_items = []
    transcript.sentences = [MagicMock(speaker="Jane", text="We need better tools.")]
    return transcript


def make_mock_classification(category="customer-discovery"):
    cls = MagicMock()
    cls.category = category
    cls.confidence = "high"
    cls.reasoning = "Talked about distribution pain points."
    cls.is_new_category = False
    return cls


# ---------------------------------------------------------------------------
# pipeline_runner tests
# ---------------------------------------------------------------------------

def test_pipeline_skips_already_processed():
    """run_meeting_pipeline must short-circuit when meeting is already in state."""
    from pipeline_runner import run_meeting_pipeline

    with patch("pipeline_runner.check_and_mark_meeting", return_value=True):
        result = run_meeting_pipeline("already-done", MagicMock())

    assert result["status"] == "skipped"
    assert result["reason"] == "already_processed"


def test_pipeline_returns_structured_steps():
    """run_meeting_pipeline must return a dict with per-step results."""
    from pipeline_runner import run_meeting_pipeline

    mock_transcript = make_mock_transcript()
    mock_classification = make_mock_classification()
    mock_pool = MagicMock()

    with patch("pipeline_runner.check_and_mark_meeting", return_value=False), \
         patch("pipeline_runner.FirefliesClient") as mock_ff, \
         patch("pipeline_runner.classify_meeting", return_value=mock_classification), \
         patch("pipeline_runner.classify_speakers", return_value={"Jane": "external", "Elman": "internal"}), \
         patch("pipeline_runner.format_with_roles", return_value="labeled"), \
         patch("pipeline_runner.format_external_with_context", return_value="external transcript"), \
         patch("pipeline_runner.process_discovery_meeting", return_value={"interview_id": 1}), \
         patch("pipeline_runner.get_notebook_id", return_value="nb-123"), \
         patch("pipeline_runner.generate_transcript_pdf", return_value="/tmp/test.pdf"), \
         patch("pipeline_runner.add_pdf_source"), \
         patch("pipeline_runner.analyze_novel", return_value=MagicMock(novel="Novel stuff here")), \
         patch("pipeline_runner.send_novel_report"), \
         patch("pipeline_runner.retain_meeting"), \
         patch("pipeline_runner.retain_novel_insights"):
        mock_ff.return_value.__enter__ = MagicMock(return_value=mock_ff.return_value)
        mock_ff.return_value.__exit__ = MagicMock(return_value=False)
        mock_ff.return_value.fetch_transcript = MagicMock(return_value=mock_transcript)
        result = run_meeting_pipeline("abc123", mock_pool)

    assert result["status"] == "completed"
    assert result["meeting_id"] == "abc123"
    assert result["category"] == "customer-discovery"
    assert "fetch" in result["steps"]
    assert result["steps"]["fetch"]["status"] == "ok"
    assert result["steps"]["classify_meeting"]["status"] == "ok"
    assert result["steps"]["discovery_extraction"]["status"] == "ok"
    assert result["steps"]["notebooklm_upload"]["status"] == "ok"
    assert result["steps"]["nlm_analysis"]["status"] == "ok"
    assert result["steps"]["email"]["status"] == "ok"
    assert result["steps"]["mark_processed"]["status"] == "ok"


# ---------------------------------------------------------------------------
# Endpoint tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pipeline_run_requires_auth():
    """POST /api/pipeline/run must reject unauthenticated requests."""
    import main as m
    m.VM_API_SECRET = "test-secret"
    async with AsyncClient(transport=ASGITransport(app=m.app), base_url="http://test") as ac:
        r = await ac.post("/api/pipeline/run", json={"meeting_id": "abc"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_pipeline_run_returns_result():
    """POST /api/pipeline/run must call run_meeting_pipeline and return its result."""
    import main as m
    m.VM_API_SECRET = "secret"

    fake = {"status": "completed", "meeting_id": "abc123", "steps": {}}

    with patch("main.run_meeting_pipeline", return_value=fake), \
         patch("main.pool", MagicMock()):
        async with AsyncClient(transport=ASGITransport(app=m.app), base_url="http://test") as ac:
            r = await ac.post(
                "/api/pipeline/run",
                json={"meeting_id": "abc123"},
                headers={"Authorization": "Bearer secret"},
            )
    assert r.status_code == 200
    assert r.json()["status"] == "completed"
    assert r.json()["meeting_id"] == "abc123"
