import json
import os
import sys
import tempfile
from fcntl import flock, LOCK_EX, LOCK_UN
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
    state_file = sys.modules[__name__].STATE_FILE
    dir_name = os.path.dirname(state_file) or "."
    lock_file = state_file + ".lock"

    with open(lock_file, "w") as lock_fd:
        flock(lock_fd, LOCK_EX)
        try:
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
        finally:
            flock(lock_fd, LOCK_UN)


def get_notebook_id(category: str) -> Optional[str]:
    """Return the NotebookLM notebook ID for a category, or None if not found."""
    return _load().get(category)


def save_notebook_id(category: str, notebook_id: str) -> None:
    """Persist a new category -> notebook ID mapping."""
    data = _load()
    data[category] = notebook_id
    _save(data)


def get_all_notebooks() -> dict:
    """Return all category -> notebook ID mappings (excludes internal keys)."""
    data = _load()
    return {k: v for k, v in data.items() if not k.startswith("_")}


def is_meeting_processed(meeting_id: str) -> bool:
    """Return True if this meeting has already been processed."""
    return meeting_id in _load().get("_processed", [])


def mark_meeting_processed(meeting_id: str) -> None:
    """Record a meeting ID as processed to prevent duplicate runs."""
    data = _load()
    processed = data.setdefault("_processed", [])
    if meeting_id not in processed:
        processed.append(meeting_id)
    _save(data)


def get_or_create_notebook_id(category: str, create_fn) -> tuple[str, bool]:
    """Get existing notebook ID or create and return it.
    Returns (notebook_id, is_new) where is_new=True if just created."""
    existing = get_notebook_id(category)
    if existing:
        return (existing, False)
    notebook_id = create_fn()
    save_notebook_id(category, notebook_id)
    return (notebook_id, True)


def is_nlm_uploaded(meeting_id: str) -> bool:
    """Check if NotebookLM upload is complete for a meeting."""
    return meeting_id in _load().get("_nlm_uploaded", [])


def mark_nlm_uploaded(meeting_id: str) -> None:
    """Record that NotebookLM upload is complete for a meeting."""
    data = _load()
    uploaded = data.setdefault("_nlm_uploaded", [])
    if meeting_id not in uploaded:
        uploaded.append(meeting_id)
    _save(data)
