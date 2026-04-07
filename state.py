import json
import os
import sys
import tempfile
from typing import Optional
from config import STATE_FILE as _DEFAULT_STATE_FILE

# Only set STATE_FILE if this module is being loaded fresh (not reloaded into
# an already-patched module). This allows tests to patch state.STATE_FILE and
# then call reload() without losing the patched value.
if "state" not in sys.modules or not hasattr(sys.modules.get("state"), "STATE_FILE"):
    STATE_FILE = _DEFAULT_STATE_FILE


def _load() -> dict:
    path = sys.modules[__name__].STATE_FILE
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return json.load(f)


def _save(data: dict) -> None:
    import tempfile
    state_file = sys.modules[__name__].STATE_FILE
    dir_name = os.path.dirname(state_file) or "."
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, state_file)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def get_notebook_id(category: str) -> Optional[str]:
    """Return the NotebookLM notebook ID for a category, or None if not found."""
    return _load().get(category)


def save_notebook_id(category: str, notebook_id: str) -> None:
    """Persist a new category -> notebook ID mapping."""
    data = _load()
    data[category] = notebook_id
    _save(data)
