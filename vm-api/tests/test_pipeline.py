import asyncio
import pytest
import pipeline_runner as _pr
from httpx import ASGITransport, AsyncClient
from unittest.mock import AsyncMock, MagicMock, patch


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
        ff.fetch_transcript = AsyncMock(return_value=mock_transcript)
        ff.aclose = AsyncMock()
        return ff

    return mock_transcript, mock_cls, make_ff


def _mock_loop():
    """Return a mock asyncio event loop for test calls."""
    return MagicMock(spec=asyncio.AbstractEventLoop)


# _run_on_loop substitute for tests: runs the coroutine in a fresh event loop
# instead of scheduling it on the shared FastAPI loop (which doesn't exist in tests).
_test_async_runner = lambda coro, _loop: asyncio.run(coro)


# ---------------------------------------------------------------------------
# Existing: dedup and happy path
# ---------------------------------------------------------------------------

def test_pipeline_skips_already_processed():
    """run_meeting_pipeline must short-circuit when meeting is already in state."""
    with patch("pipeline_runner.is_meeting_processed", return_value=True):
        result = _pr.run_meeting_pipeline("already-done", MagicMock(), _mock_loop())

    assert result["status"] == "skipped"
    assert result["reason"] == "already_processed"


def test_pipeline_returns_structured_steps():
    """run_meeting_pipeline returns completed status with per-step results."""
    mock_transcript, mock_cls, make_ff = _full_happy_path_patches()

    with patch("pipeline_runner.is_meeting_processed", return_value=False), \
         patch("pipeline_runner.mark_meeting_processed"), \
         patch("pipeline_runner._run_on_loop", side_effect=_test_async_runner), \
         patch("pipeline_runner.FirefliesClient", return_value=make_ff()), \
         patch("pipeline_runner.classify_meeting", new_callable=AsyncMock, return_value=mock_cls), \
         patch("pipeline_runner.classify_speakers", return_value={"Jane": "external", "Elman": "internal"}), \
         patch("pipeline_runner.format_with_roles", return_value="labeled"), \
         patch("pipeline_runner.format_external_with_context", return_value="external transcript"), \
         patch("pipeline_runner.process_discovery_meeting", new_callable=AsyncMock, return_value={"interview_id": 1}), \
         patch("pipeline_runner.get_or_create_notebook_id", return_value=("nb-123", False)), \
         patch("pipeline_runner.is_nlm_uploaded", return_value=False), \
         patch("pipeline_runner.generate_transcript_docx", return_value="/tmp/test.docx"), \
         patch("pipeline_runner.add_file_source"), \
         patch("pipeline_runner.mark_nlm_uploaded"), \
         patch("pipeline_runner.analyze_novel", return_value=MagicMock(novel="Novel stuff here")), \
         patch("pipeline_runner.send_novel_report", new_callable=AsyncMock), \
         patch("pipeline_runner.retain_meeting", new_callable=AsyncMock), \
         patch("pipeline_runner.retain_novel_insights", new_callable=AsyncMock):
        result = _pr.run_meeting_pipeline("abc123", MagicMock(), _mock_loop())

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
        result = _pr.run_meeting_pipeline("concurrent-id", MagicMock(), _mock_loop())
    finally:
        _pr._in_flight.discard("concurrent-id")

    assert result["status"] == "skipped"
    assert result["reason"] == "in_flight"


def test_pipeline_clears_in_flight_on_completion():
    """meeting_id must be removed from _in_flight after the pipeline finishes."""
    with patch("pipeline_runner.is_meeting_processed", return_value=True):
        _pr.run_meeting_pipeline("cleanup-id", MagicMock(), _mock_loop())

    assert "cleanup-id" not in _pr._in_flight


# ---------------------------------------------------------------------------
# Guard: no external speakers → skip discovery extraction
# ---------------------------------------------------------------------------

def test_pipeline_skips_extraction_when_all_speakers_internal():
    """customer-discovery meeting with no external speakers must skip extraction."""
    mock_transcript, mock_cls, make_ff = _full_happy_path_patches()

    with patch("pipeline_runner.is_meeting_processed", return_value=False), \
         patch("pipeline_runner.mark_meeting_processed"), \
         patch("pipeline_runner._run_on_loop", side_effect=_test_async_runner), \
         patch("pipeline_runner.FirefliesClient", return_value=make_ff()), \
         patch("pipeline_runner.classify_meeting", new_callable=AsyncMock, return_value=mock_cls), \
         patch("pipeline_runner.classify_speakers", return_value={"Elman": "internal", "Klara": "internal"}), \
         patch("pipeline_runner.format_with_roles", return_value="labeled"), \
         patch("pipeline_runner.format_external_with_context", return_value=""), \
         patch("pipeline_runner.process_discovery_meeting", new_callable=AsyncMock) as mock_extract, \
         patch("pipeline_runner.get_or_create_notebook_id", return_value=("nb-123", False)), \
         patch("pipeline_runner.is_nlm_uploaded", return_value=False), \
         patch("pipeline_runner.generate_transcript_docx", return_value="/tmp/test.docx"), \
         patch("pipeline_runner.add_file_source"), \
         patch("pipeline_runner.mark_nlm_uploaded"), \
         patch("pipeline_runner.analyze_novel", return_value=MagicMock(novel="some novel")), \
         patch("pipeline_runner.send_novel_report", new_callable=AsyncMock), \
         patch("pipeline_runner.retain_meeting", new_callable=AsyncMock), \
         patch("pipeline_runner.retain_novel_insights", new_callable=AsyncMock):
        result = _pr.run_meeting_pipeline("internal-only", MagicMock(), _mock_loop())

    assert result["steps"]["discovery_extraction"]["status"] == "skipped"
    assert result["steps"]["discovery_extraction"]["reason"] == "no_external_speakers"
    mock_extract.assert_not_called()


# ---------------------------------------------------------------------------
# Guard: empty NLM novel → skip email
# ---------------------------------------------------------------------------

def test_pipeline_skips_email_when_novel_is_empty():
    """Empty novel analysis result must skip email rather than send blank HTML."""
    mock_transcript, mock_cls, make_ff = _full_happy_path_patches()

    with patch("pipeline_runner.is_meeting_processed", return_value=False), \
         patch("pipeline_runner.mark_meeting_processed"), \
         patch("pipeline_runner._run_on_loop", side_effect=_test_async_runner), \
         patch("pipeline_runner.FirefliesClient", return_value=make_ff()), \
         patch("pipeline_runner.classify_meeting", new_callable=AsyncMock, return_value=mock_cls), \
         patch("pipeline_runner.classify_speakers", return_value={"Jane": "external", "Elman": "internal"}), \
         patch("pipeline_runner.format_with_roles", return_value="labeled"), \
         patch("pipeline_runner.format_external_with_context", return_value="external transcript"), \
         patch("pipeline_runner.process_discovery_meeting", new_callable=AsyncMock, return_value={"interview_id": 1}), \
         patch("pipeline_runner.get_or_create_notebook_id", return_value=("nb-123", False)), \
         patch("pipeline_runner.is_nlm_uploaded", return_value=False), \
         patch("pipeline_runner.generate_transcript_docx", return_value="/tmp/test.docx"), \
         patch("pipeline_runner.add_file_source"), \
         patch("pipeline_runner.mark_nlm_uploaded"), \
         patch("pipeline_runner.analyze_novel", return_value=MagicMock(novel="")), \
         patch("pipeline_runner.send_novel_report", new_callable=AsyncMock) as mock_send, \
         patch("pipeline_runner.retain_meeting", new_callable=AsyncMock), \
         patch("pipeline_runner.retain_novel_insights", new_callable=AsyncMock):
        result = _pr.run_meeting_pipeline("empty-novel", MagicMock(), _mock_loop())

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

    with patch("pipeline_runner.is_meeting_processed", return_value=False), \
         patch("pipeline_runner.mark_meeting_processed"), \
         patch("pipeline_runner._run_on_loop", side_effect=_test_async_runner), \
         patch("pipeline_runner.FirefliesClient", return_value=make_ff()), \
         patch("pipeline_runner.classify_meeting", new_callable=AsyncMock, return_value=team_sync_cls), \
         patch("pipeline_runner.classify_speakers", return_value={"Jane": "external", "Elman": "internal"}), \
         patch("pipeline_runner.format_with_roles", return_value="labeled"), \
         patch("pipeline_runner.format_external_with_context", return_value="external transcript"), \
         patch("pipeline_runner.process_discovery_meeting", new_callable=AsyncMock) as mock_extract, \
         patch("pipeline_runner.get_or_create_notebook_id", return_value=("nb-123", False)), \
         patch("pipeline_runner.generate_transcript_docx", return_value="/tmp/test.docx"), \
         patch("pipeline_runner.add_file_source"), \
         patch("pipeline_runner.analyze_novel", return_value=MagicMock(novel="novel")), \
         patch("pipeline_runner.send_novel_report", new_callable=AsyncMock), \
         patch("pipeline_runner.retain_meeting", new_callable=AsyncMock), \
         patch("pipeline_runner.retain_novel_insights", new_callable=AsyncMock):
        result = _pr.run_meeting_pipeline("team-sync-123", MagicMock(), _mock_loop())

    assert result["steps"]["discovery_extraction"]["status"] == "skipped"
    assert "team-syncs" in result["steps"]["discovery_extraction"]["reason"]
    mock_extract.assert_not_called()


# ---------------------------------------------------------------------------
# Guard: NLM + email skipped for non-enabled categories (classes, team-syncs)
# ---------------------------------------------------------------------------

def test_pipeline_skips_nlm_and_email_for_class_meetings():
    """Class meetings must skip NLM upload, analysis, and email entirely."""
    mock_transcript, _, make_ff = _full_happy_path_patches()
    class_cls = make_mock_classification(category="class-mge")

    with patch("pipeline_runner.is_meeting_processed", return_value=False), \
         patch("pipeline_runner.mark_meeting_processed"), \
         patch("pipeline_runner._run_on_loop", side_effect=_test_async_runner), \
         patch("pipeline_runner.FirefliesClient", return_value=make_ff()), \
         patch("pipeline_runner.classify_meeting", new_callable=AsyncMock, return_value=class_cls), \
         patch("pipeline_runner.classify_speakers", return_value={"Elman": "internal"}), \
         patch("pipeline_runner.format_with_roles", return_value="labeled"), \
         patch("pipeline_runner.format_external_with_context", return_value=""), \
         patch("pipeline_runner.get_or_create_notebook_id") as mock_nb, \
         patch("pipeline_runner.add_file_source") as mock_upload, \
         patch("pipeline_runner.analyze_novel") as mock_analyze, \
         patch("pipeline_runner.send_novel_report", new_callable=AsyncMock) as mock_send, \
         patch("pipeline_runner.retain_meeting", new_callable=AsyncMock), \
         patch("pipeline_runner.retain_novel_insights", new_callable=AsyncMock):
        result = _pr.run_meeting_pipeline("class-meeting-1", MagicMock(), _mock_loop())

    assert result["status"] == "completed"
    assert result["steps"]["notebooklm_notebook"]["status"] == "skipped"
    assert result["steps"]["notebooklm_upload"]["status"] == "skipped"
    assert result["steps"]["nlm_analysis"]["status"] == "skipped"
    assert result["steps"]["email"]["status"] == "skipped"
    mock_nb.assert_not_called()
    mock_upload.assert_not_called()
    mock_analyze.assert_not_called()
    mock_send.assert_not_called()


# ---------------------------------------------------------------------------
# Idempotency: mark_processed fires after NLM upload, not before fetch
# ---------------------------------------------------------------------------

def test_mark_processed_fires_after_nlm_upload():
    """mark_meeting_processed must NOT be called when fetch fails."""
    mock_transcript, mock_cls, make_ff = _full_happy_path_patches()
    failing_ff = make_ff()
    failing_ff.fetch_transcript = AsyncMock(side_effect=RuntimeError("Fireflies down"))

    with patch("pipeline_runner.is_meeting_processed", return_value=False), \
         patch("pipeline_runner.mark_meeting_processed") as mock_mark, \
         patch("pipeline_runner.FirefliesClient", return_value=failing_ff):
        result = _pr.run_meeting_pipeline("transient-fail", MagicMock(), _mock_loop())

    assert result["steps"]["fetch"]["status"] == "error"
    mock_mark.assert_not_called()


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
         patch("main.pool", MagicMock()), \
         patch("main.app_event_loop", MagicMock()):
        async with AsyncClient(transport=ASGITransport(app=m.app), base_url="http://test") as ac:
            r = await ac.post(
                "/api/pipeline/run",
                json={"meeting_id": "abc123"},
                headers={"Authorization": "Bearer secret"},
            )
    assert r.status_code == 200
    assert r.json()["status"] == "completed"
    assert r.json()["meeting_id"] == "abc123"


# ---------------------------------------------------------------------------
# Guard: NLM upload skipped when already uploaded
# ---------------------------------------------------------------------------

def test_pipeline_skips_nlm_upload_when_already_uploaded():
    """If is_nlm_uploaded returns True, add_file_source must not be called."""
    mock_transcript, mock_cls, make_ff = _full_happy_path_patches()

    with patch("pipeline_runner.is_meeting_processed", return_value=False), \
         patch("pipeline_runner.mark_meeting_processed"), \
         patch("pipeline_runner._run_on_loop", side_effect=_test_async_runner), \
         patch("pipeline_runner.FirefliesClient", return_value=make_ff()), \
         patch("pipeline_runner.classify_meeting", new_callable=AsyncMock, return_value=mock_cls), \
         patch("pipeline_runner.classify_speakers", return_value={"Jane": "external", "Elman": "internal"}), \
         patch("pipeline_runner.format_with_roles", return_value="labeled"), \
         patch("pipeline_runner.format_external_with_context", return_value="external transcript"), \
         patch("pipeline_runner.process_discovery_meeting", new_callable=AsyncMock, return_value={"interview_id": 1}), \
         patch("pipeline_runner.get_or_create_notebook_id", return_value=("nb-123", False)), \
         patch("pipeline_runner.is_nlm_uploaded", return_value=True), \
         patch("pipeline_runner.add_file_source") as mock_upload, \
         patch("pipeline_runner.analyze_novel", return_value=MagicMock(novel="Novel stuff here")), \
         patch("pipeline_runner.send_novel_report", new_callable=AsyncMock), \
         patch("pipeline_runner.retain_meeting", new_callable=AsyncMock), \
         patch("pipeline_runner.retain_novel_insights", new_callable=AsyncMock):
        result = _pr.run_meeting_pipeline("already-uploaded", MagicMock(), _mock_loop())

    assert result["steps"]["notebooklm_upload"]["status"] == "skipped"
    assert result["steps"]["notebooklm_upload"]["reason"] == "already_uploaded"
    mock_upload.assert_not_called()


# ---------------------------------------------------------------------------
# Guard: meeting date passed correctly to discovery extraction
# ---------------------------------------------------------------------------

def test_pipeline_passes_transcript_date_not_today():
    """process_discovery_meeting must receive transcript.date[:10], not today's date."""
    mock_transcript, mock_cls, make_ff = _full_happy_path_patches()
    mock_transcript.date = "2026-03-15T10:00:00.000Z"

    captured = {}

    async def capture(**kwargs):
        captured["meeting_date"] = kwargs.get("meeting_date")
        return {"interview_id": 1}

    with patch("pipeline_runner.is_meeting_processed", return_value=False), \
         patch("pipeline_runner.mark_meeting_processed"), \
         patch("pipeline_runner._run_on_loop", side_effect=_test_async_runner), \
         patch("pipeline_runner.FirefliesClient", return_value=make_ff()), \
         patch("pipeline_runner.classify_meeting", new_callable=AsyncMock, return_value=mock_cls), \
         patch("pipeline_runner.classify_speakers", return_value={"Jane": "external", "Elman": "internal"}), \
         patch("pipeline_runner.format_with_roles", return_value="labeled"), \
         patch("pipeline_runner.format_external_with_context", return_value="external transcript"), \
         patch("pipeline_runner.process_discovery_meeting", new_callable=AsyncMock, side_effect=capture), \
         patch("pipeline_runner.get_or_create_notebook_id", return_value=("nb-123", False)), \
         patch("pipeline_runner.is_nlm_uploaded", return_value=False), \
         patch("pipeline_runner.generate_transcript_docx", return_value="/tmp/test.docx"), \
         patch("pipeline_runner.add_file_source"), \
         patch("pipeline_runner.mark_nlm_uploaded"), \
         patch("pipeline_runner.analyze_novel", return_value=MagicMock(novel="Novel")), \
         patch("pipeline_runner.send_novel_report", new_callable=AsyncMock), \
         patch("pipeline_runner.retain_meeting", new_callable=AsyncMock), \
         patch("pipeline_runner.retain_novel_insights", new_callable=AsyncMock):
        _pr.run_meeting_pipeline("date-test", MagicMock(), _mock_loop())

    assert captured["meeting_date"] == "2026-03-15", (
        f"Expected '2026-03-15', got {captured.get('meeting_date')!r}"
    )


# ---------------------------------------------------------------------------
# _meeting_date helper
# ---------------------------------------------------------------------------

def test_meeting_date_iso_string():
    """ISO string input should return first 10 chars."""
    assert _pr._meeting_date("2026-03-15T10:00:00.000Z") == "2026-03-15"


def test_meeting_date_ms_timestamp():
    """Integer ms timestamp should return the correct UTC date, not today."""
    # 1742000000000 ms = 2025-03-15 in UTC
    result = _pr._meeting_date(1742000000000)
    assert result == "2025-03-15"


def test_meeting_date_none():
    """None/falsy input should return today's date string."""
    from datetime import date
    assert _pr._meeting_date(None) == str(date.today())
    assert _pr._meeting_date(0) == str(date.today())
