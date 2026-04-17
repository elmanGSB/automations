import subprocess
import pytest
from unittest.mock import MagicMock, patch
import notebooklm


# ---------------------------------------------------------------------------
# create_notebook
# ---------------------------------------------------------------------------

def test_create_notebook_returns_id():
    """Successful create_notebook returns the notebook ID."""
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "✓ Created notebook: Test\n  ID: abc12345-0000-0000-0000-000000000000"
    mock_result.stderr = ""

    with patch("notebooklm.subprocess.run", return_value=mock_result) as mock_run:
        result = notebooklm.create_notebook("Test")

    assert result == "abc12345-0000-0000-0000-000000000000"
    call_kwargs = mock_run.call_args[1]
    assert call_kwargs["timeout"] == 120


def test_create_notebook_raises_on_timeout():
    """create_notebook raises RuntimeError when subprocess times out."""
    with patch("notebooklm.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="nlm", timeout=120)):
        with pytest.raises(RuntimeError, match="Timed out creating notebook"):
            notebooklm.create_notebook("Test")


def test_create_notebook_raises_on_nonzero_exit():
    """create_notebook raises RuntimeError on non-zero returncode."""
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stderr = "auth error"

    with patch("notebooklm.subprocess.run", return_value=mock_result):
        with pytest.raises(RuntimeError, match="Failed to create notebook"):
            notebooklm.create_notebook("Test")


# ---------------------------------------------------------------------------
# add_pdf_source
# ---------------------------------------------------------------------------

def test_add_pdf_source_success():
    """Successful add_pdf_source completes without raising."""
    mock_result = MagicMock()
    mock_result.returncode = 0

    with patch("notebooklm.subprocess.run", return_value=mock_result) as mock_run:
        notebooklm.add_pdf_source("nb-123", "/tmp/test.pdf", "My Meeting")

    call_kwargs = mock_run.call_args[1]
    assert call_kwargs["timeout"] == 600


def test_add_pdf_source_raises_on_timeout():
    """add_pdf_source raises RuntimeError when subprocess times out."""
    with patch("notebooklm.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="nlm", timeout=600)):
        with pytest.raises(RuntimeError, match="Timed out uploading PDF"):
            notebooklm.add_pdf_source("nb-123", "/tmp/test.pdf", "My Meeting")


def test_add_pdf_source_raises_on_nonzero_exit():
    """add_pdf_source raises RuntimeError on non-zero returncode."""
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stderr = "network error"

    with patch("notebooklm.subprocess.run", return_value=mock_result):
        with pytest.raises(RuntimeError, match="Failed to add source"):
            notebooklm.add_pdf_source("nb-123", "/tmp/test.pdf", "My Meeting")
