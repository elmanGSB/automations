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
# add_file_source
# ---------------------------------------------------------------------------

def test_add_file_source_success():
    """Successful add_file_source completes without raising."""
    mock_result = MagicMock()
    mock_result.returncode = 0

    with patch("notebooklm.subprocess.run", return_value=mock_result) as mock_run:
        notebooklm.add_file_source("nb-123", "/tmp/test.docx", "My Meeting")

    call_kwargs = mock_run.call_args[1]
    assert call_kwargs["timeout"] == 600


def test_add_file_source_raises_on_timeout():
    """add_file_source raises RuntimeError when subprocess times out."""
    with patch("notebooklm.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="nlm", timeout=600)):
        with pytest.raises(RuntimeError, match="Timed out uploading file"):
            notebooklm.add_file_source("nb-123", "/tmp/test.docx", "My Meeting")


def test_add_file_source_raises_on_nonzero_exit():
    """add_file_source raises RuntimeError on non-zero returncode."""
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stderr = "network error"

    with patch("notebooklm.subprocess.run", return_value=mock_result):
        with pytest.raises(RuntimeError, match="Failed to add source"):
            notebooklm.add_file_source("nb-123", "/tmp/test.docx", "My Meeting")


# ---------------------------------------------------------------------------
# list_notebooks
# ---------------------------------------------------------------------------

def _list_result(stdout):
    m = MagicMock()
    m.returncode = 0
    m.stdout = stdout
    m.stderr = ""
    return m


def test_list_notebooks_parses_json():
    """list_notebooks returns a list of dicts parsed from --json output."""
    payload = '[{"id":"a","title":"X","source_count":2},{"id":"b","title":"Y","source_count":0}]'
    with patch("notebooklm.subprocess.run", return_value=_list_result(payload)) as run:
        result = notebooklm.list_notebooks()
    assert result == [
        {"id": "a", "title": "X", "source_count": 2},
        {"id": "b", "title": "Y", "source_count": 0},
    ]
    assert run.call_args[0][0] == ["nlm", "notebook", "list", "--json"]


def test_list_notebooks_raises_on_nonzero_exit():
    m = MagicMock()
    m.returncode = 1
    m.stderr = "auth"
    with patch("notebooklm.subprocess.run", return_value=m):
        with pytest.raises(RuntimeError, match="Failed to list notebooks"):
            notebooklm.list_notebooks()


def test_list_notebooks_raises_on_bad_json():
    with patch("notebooklm.subprocess.run", return_value=_list_result("not json")):
        with pytest.raises(RuntimeError, match="parse notebook list"):
            notebooklm.list_notebooks()


def test_list_notebooks_raises_on_timeout():
    with patch(
        "notebooklm.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="nlm", timeout=60),
    ):
        with pytest.raises(RuntimeError, match="Timed out listing notebooks"):
            notebooklm.list_notebooks()


# ---------------------------------------------------------------------------
# find_notebook_by_title
# ---------------------------------------------------------------------------

def test_find_notebook_by_title_returns_none_when_no_match():
    payload = '[{"id":"a","title":"Other","source_count":1}]'
    with patch("notebooklm.subprocess.run", return_value=_list_result(payload)):
        assert notebooklm.find_notebook_by_title("Customer Interviews & Sales") is None


def test_find_notebook_by_title_returns_id_on_single_match():
    payload = '[{"id":"abc","title":"Customer Interviews & Sales","source_count":3}]'
    with patch("notebooklm.subprocess.run", return_value=_list_result(payload)):
        assert notebooklm.find_notebook_by_title("Customer Interviews & Sales") == "abc"


def test_find_notebook_by_title_picks_most_sources_on_duplicates():
    """Duplicates pick the notebook with the most sources — most history wins."""
    payload = (
        '[{"id":"new","title":"Customer Interviews & Sales","source_count":1},'
        '{"id":"old","title":"Customer Interviews & Sales","source_count":7}]'
    )
    with patch("notebooklm.subprocess.run", return_value=_list_result(payload)):
        assert notebooklm.find_notebook_by_title("Customer Interviews & Sales") == "old"
