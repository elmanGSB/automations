import pytest
import pipeline_runner as _pr
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


def _full_happy_path_patches(classification=None):
    """Return a stack of patches covering the full happy path."""
    mock_transcript = make_mock_transcript()
    mock_cls = classification or make_mock_classification()

    def make_ff():
        ff = MagicMock()
        ff.__enter__ = MagicMock(return_value=ff)
        ff.__exit__ = MagicMock(return_value=False)
        ff.fetch_transcript = MagicMock(return_value=mock_transcript)
        return ff

    return mock_transcript, mock_cls, make_ff


# ---------------------------------------------------------------------------
# Existing: dedup and happy path
# ---------------------------------------------------------------------------

def test_pipeline_skips_already_processed():
    """run_meeting_pipeline must short-circuit when meeting is already in state."""
    with patch("pipeline_runner.check_and_mark_meeting", return_value=True):
        result = _pr.run_meeting_pipeline("already-done", MagicMock())

    assert result["status"] == "skipped"
    assert result["reason"] == "already_processed"


def test_pipeline_returns_structured_steps():
    """run_meeting_pipeline returns completed status with per-step results."""
    mock_transcript, mock_cls, make_ff = _full_happy_path_patches()

    with patch("pipeline_runner.check_and_mark_meeting", return_value=False), \
         patch("pipeline_runner.FirefliesClient", return_value=make_ff()), \
         patch("pipeline_runner.classify_meeting", return_value=mock_cls), \
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
        result = _pr.run_meeting_pipeline("abc123", MagicMock())

    assert result["status"] == "completed"
    assert result["meeting_id"] == "abc123"
    assert result["category"] == "customer-discovery"
    assert result["steps"]["fetch"]["status"] == "ok"
    assert result["steps"]["classify_meeting"]["status"] == "ok"
    assert result["steps"]["discovery_extraction"]["status"] == "ok"
    assert result["steps"]["notebooklm_upload"]["status"] == "ok"
    assert result["steps"]["nlm_analysis"]["status"] == "ok"
    assert result["steps"]["email"]["status"] == "ok"
    assert result["steps"]["mark_processed"]["status"] == "ok"


# ---------------------------------------------------------------------------
# Guard: in-flight concurrent request
# ---------------------------------------------------------------------------

def test_pipeline_skips_in_flight_meeting():
    """Second call for the same meeting_id while first is running must be skipped."""
    _pr._in_flight.add("concurrent-id")
    try:
        result = _pr.run_meeting_pipeline("concurrent-id", MagicMock())
    finally:
        _pr._in_flight.discard("concurrent-id")

    assert result["status"] == "skipped"
    assert result["reason"] == "in_flight"


def test_pipeline_clears_in_flight_on_completion():
    """meeting_id must be removed from _in_flight after the pipeline finishes."""
    with patch("pipeline_runner.check_and_mark_meeting", return_value=True):
        _pr.run_meeting_pipeline("cleanup-id", MagicMock())

    assert "cleanup-id" not in _pr._in_flight


# ---------------------------------------------------------------------------
# Guard: no external speakers → skip discovery extraction
# ---------------------------------------------------------------------------

def test_pipeline_skips_extraction_when_all_speakers_internal():
    """customer-discovery meeting with no external speakers must skip extraction."""
    mock_transcript, mock_cls, make_ff = _full_happy_path_patches()

    with patch("pipeline_runner.check_and_mark_meeting", return_value=False), \
         patch("pipeline_runner.FirefliesClient", return_value=make_ff()), \
         patch("pipeline_runner.classify_meeting", return_value=mock_cls), \
         patch("pipeline_runner.classify_speakers", return_value={"Elman": "internal", "Klara": "internal"}), \
         patch("pipeline_runner.format_with_roles", return_value="labeled"), \
         patch("pipeline_runner.format_external_with_context", return_value=""), \
         patch("pipeline_runner.process_discovery_meeting") as mock_extract, \
         patch("pipeline_runner.get_notebook_id", return_value="nb-123"), \
         patch("pipeline_runner.generate_transcript_pdf", return_value="/tmp/test.pdf"), \
         patch("pipeline_runner.add_pdf_source"), \
         patch("pipeline_runner.analyze_novel", return_value=MagicMock(novel="some novel")), \
         patch("pipeline_runner.send_novel_report"), \
         patch("pipeline_runner.retain_meeting"), \
         patch("pipeline_runner.retain_novel_insights"):
        result = _pr.run_meeting_pipeline("internal-only", MagicMock())

    assert result["steps"]["discovery_extraction"]["status"] == "skipped"
    assert result["steps"]["discovery_extraction"]["reason"] == "no_external_speakers"
    mock_extract.assert_not_called()


# ---------------------------------------------------------------------------
# Guard: empty NLM novel → skip email
# ---------------------------------------------------------------------------

def test_pipeline_skips_email_when_novel_is_empty():
    """Empty novel analysis result must skip email rather than send blank HTML."""
    mock_transcript, mock_cls, make_ff = _full_happy_path_patches()

    with patch("pipeline_runner.check_and_mark_meeting", return_value=False), \
         patch("pipeline_runner.FirefliesClient", return_value=make_ff()), \
         patch("pipeline_runner.classify_meeting", return_value=mock_cls), \
         patch("pipeline_runner.classify_speakers", return_value={"Jane": "external", "Elman": "internal"}), \
         patch("pipeline_runner.format_with_roles", return_value="labeled"), \
         patch("pipeline_runner.format_external_with_context", return_value="external transcript"), \
         patch("pipeline_runner.process_discovery_meeting", return_value={"interview_id": 1}), \
         patch("pipeline_runner.get_notebook_id", return_value="nb-123"), \
         patch("pipeline_runner.generate_transcript_pdf", return_value="/tmp/test.pdf"), \
         patch("pipeline_runner.add_pdf_source"), \
         patch("pipeline_runner.analyze_novel", return_value=MagicMock(novel="")), \
         patch("pipeline_runner.send_novel_report") as mock_send, \
         patch("pipeline_runner.retain_meeting"), \
         patch("pipeline_runner.retain_novel_insights"):
        result = _pr.run_meeting_pipeline("empty-novel", MagicMock())

    assert result["steps"]["email"]["status"] == "skipped"
    assert result["steps"]["email"]["reason"] == "empty_novel"
    mock_send.assert_not_called()


# ---------------------------------------------------------------------------
# Guard: non-customer-discovery category skips extraction
# ---------------------------------------------------------------------------

def test_pipeline_skips_extraction_for_non_discovery_category():
    """team-syncs and other categories must skip discovery extraction entirely."""
    mock_transcript, _, make_ff = _full_happy_path_patches()
    team_sync_cls = make_mock_classification(category="team-syncs")

    with patch("pipeline_runner.check_and_mark_meeting", return_value=False), \
         patch("pipeline_runner.FirefliesClient", return_value=make_ff()), \
         patch("pipeline_runner.classify_meeting", return_value=team_sync_cls), \
         patch("pipeline_runner.classify_speakers", return_value={"Jane": "external", "Elman": "internal"}), \
         patch("pipeline_runner.format_with_roles", return_value="labeled"), \
         patch("pipeline_runner.format_external_with_context", return_value="external transcript"), \
         patch("pipeline_runner.process_discovery_meeting") as mock_extract, \
         patch("pipeline_runner.get_notebook_id", return_value="nb-123"), \
         patch("pipeline_runner.generate_transcript_pdf", return_value="/tmp/test.pdf"), \
         patch("pipeline_runner.add_pdf_source"), \
         patch("pipeline_runner.analyze_novel", return_value=MagicMock(novel="novel")), \
         patch("pipeline_runner.send_novel_report"), \
         patch("pipeline_runner.retain_meeting"), \
         patch("pipeline_runner.retain_novel_insights"):
        result = _pr.run_meeting_pipeline("team-sync-123", MagicMock())

    assert result["steps"]["discovery_extraction"]["status"] == "skipped"
    assert "team-syncs" in result["steps"]["discovery_extraction"]["reason"]
    mock_extract.assert_not_called()


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
