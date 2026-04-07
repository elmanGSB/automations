import os
import json
import tempfile
import pytest
from unittest.mock import patch

def _make_state_file(data: dict) -> str:
    """Helper: write data to a temp JSON file, return path."""
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    json.dump(data, f)
    f.close()
    return f.name

def test_get_notebook_id_returns_existing():
    path = _make_state_file({"customer-discovery": "nb-abc"})
    try:
        with patch("state.STATE_FILE", path):
            import state
            from importlib import reload
            reload(state)
            assert state.get_notebook_id("customer-discovery") == "nb-abc"
    finally:
        os.unlink(path)

def test_get_notebook_id_returns_none_for_unknown():
    path = _make_state_file({})
    try:
        with patch("state.STATE_FILE", path):
            import state
            from importlib import reload
            reload(state)
            assert state.get_notebook_id("unknown-category") is None
    finally:
        os.unlink(path)

def test_save_notebook_id_persists():
    path = _make_state_file({})
    try:
        with patch("state.STATE_FILE", path):
            import state
            from importlib import reload
            reload(state)
            state.save_notebook_id("advisors", "nb-xyz")
            with open(path) as f:
                data = json.load(f)
            assert data["advisors"] == "nb-xyz"
    finally:
        os.unlink(path)

def test_get_returns_none_when_file_missing():
    with patch("state.STATE_FILE", "/tmp/nonexistent-interview-router-state.json"):
        import state
        from importlib import reload
        reload(state)
        assert state.get_notebook_id("anything") is None

def test_save_creates_file_if_missing():
    path = "/tmp/test-interview-router-state-new.json"
    if os.path.exists(path):
        os.unlink(path)
    try:
        with patch("state.STATE_FILE", path):
            import state
            from importlib import reload
            reload(state)
            state.save_notebook_id("team-syncs", "nb-999")
            with open(path) as f:
                data = json.load(f)
            assert data["team-syncs"] == "nb-999"
    finally:
        if os.path.exists(path):
            os.unlink(path)
