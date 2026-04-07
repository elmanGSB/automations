import pytest
from unittest.mock import patch, MagicMock
from notebooklm import create_notebook, add_pdf_source, notebook_title_for_category

def test_create_notebook_returns_id():
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = '{"id": "nb-12345", "title": "Customer Interviews & Sales"}\n'
    mock_result.stderr = ""

    with patch("subprocess.run", return_value=mock_result) as mock_run:
        notebook_id = create_notebook("Customer Interviews & Sales")

    assert notebook_id == "nb-12345"
    args = mock_run.call_args[0][0]
    assert "nlm" in args
    assert "notebook" in args
    assert "create" in args
    assert "Customer Interviews & Sales" in args
    assert "--output" in args
    assert "json" in args

def test_add_pdf_source_calls_nlm_with_correct_args():
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = ""
    mock_result.stderr = ""

    with patch("subprocess.run", return_value=mock_result) as mock_run:
        add_pdf_source("nb-12345", "/tmp/transcript.pdf", "Customer call - Acme")

    args = mock_run.call_args[0][0]
    assert "nlm" in args
    assert "source" in args
    assert "add" in args
    assert "nb-12345" in args
    assert "--file" in args
    assert "/tmp/transcript.pdf" in args
    assert "--title" in args
    assert "Customer call - Acme" in args
    assert "--wait" in args

def test_create_notebook_raises_on_failure():
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stdout = ""
    mock_result.stderr = "Authentication failed"

    with patch("subprocess.run", return_value=mock_result):
        with pytest.raises(RuntimeError, match="Failed to create notebook"):
            create_notebook("Test Notebook")

def test_add_pdf_source_raises_on_failure():
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stdout = ""
    mock_result.stderr = "Notebook not found"

    with patch("subprocess.run", return_value=mock_result):
        with pytest.raises(RuntimeError, match="Failed to add source"):
            add_pdf_source("bad-nb-id", "/tmp/file.pdf", "Test")

def test_notebook_title_for_known_category():
    assert notebook_title_for_category("customer-discovery") == "Customer Interviews & Sales"
    assert notebook_title_for_category("investor-calls") == "Investor Calls"
    assert notebook_title_for_category("team-syncs") == "Team Syncs"
    assert notebook_title_for_category("competitors") == "Competitor Research"
    assert notebook_title_for_category("advisors") == "Advisors"

def test_notebook_title_for_unknown_category():
    assert notebook_title_for_category("conference-panel") == "Conference Panel"
    assert notebook_title_for_category("podcast-interview") == "Podcast Interview"

def test_create_notebook_handles_preamble_in_output():
    """nlm CLI may emit warning lines before JSON."""
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = 'Warning: using cached auth\n{"id": "nb-99999", "title": "Test"}\n'
    mock_result.stderr = ""

    with patch("subprocess.run", return_value=mock_result):
        notebook_id = create_notebook("Test")

    assert notebook_id == "nb-99999"
