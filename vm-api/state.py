import json
import os
import sys
import tempfile
from collections.abc import Callable
from typing import Optional
from filelock import FileLock
from config import STATE_FILE as _DEFAULT_STATE_FILE

# Only set STATE_FILE if this module is being loaded fresh (not reloaded into
# an already-patched module). This allows tests to patch state.STATE_FILE and
# then call reload() without losing the patched value.
if "state" not in sys.modules or not hasattr(sys.modules.get("state"), "STATE_FILE"):
    STATE_FILE = _DEFAULT_STATE_FILE

_LOCK_TIMEOUT = 10


def _lock_path() -> str:
    return sys.modules[__name__].STATE_FILE + ".lock"


def _load() -> dict:
    path = sys.modules[__name__].STATE_FILE
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return json.load(f)


def _save(data: dict) -> None:
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
    """Persist a new category -> notebook ID mapping. Thread-safe via FileLock."""
    with FileLock(_lock_path(), timeout=_LOCK_TIMEOUT):
        data = _load()
        data[category] = notebook_id
        _save(data)


def get_or_create_notebook_id(category: str, create_fn: Callable[[], str]) -> tuple[str, bool]:
    """Atomically get or create a notebook ID for a category.

    Returns (notebook_id, is_new). Calls create_fn() only when no mapping
    exists yet. Uses optimistic concurrency — create_fn runs outside the lock
    to avoid holding it during slow subprocess calls; re-checks inside the lock
    before writing so only one ID is ever persisted per category.
    """
    # Fast path: check without lock
    existing = _load().get(category)
    if existing:
        return existing, False

    # Slow path: create then lock-check-write
    notebook_id = create_fn()
    if not notebook_id:
        raise ValueError(f"create_fn returned empty notebook ID for category '{category}'")
    with FileLock(_lock_path(), timeout=_LOCK_TIMEOUT):
        data = _load()
        if category in data:
            # Another thread saved while we were creating; discard ours
            return data[category], False
        data[category] = notebook_id
        _save(data)
    return notebook_id, True


def get_all_notebooks() -> dict:
    """Return all category -> notebook ID mappings (excludes internal keys)."""
    data = _load()
    return {k: v for k, v in data.items() if not k.startswith("_")}


def is_meeting_processed(meeting_id: str) -> bool:
    """Return True if this meeting has already been processed."""
    return meeting_id in _load().get("_processed", [])


def mark_meeting_processed(meeting_id: str) -> None:
    """Record a meeting ID as processed. Thread-safe via FileLock."""
    with FileLock(_lock_path(), timeout=_LOCK_TIMEOUT):
        data = _load()
        processed = data.setdefault("_processed", [])
        if meeting_id not in processed:
            processed.append(meeting_id)
        data["_processed"] = processed[-500:]
        _save(data)


def is_nlm_uploaded(meeting_id: str) -> bool:
    """Return True if the NLM PDF for this meeting was already uploaded."""
    return meeting_id in _load().get("_nlm_uploaded", [])


def mark_nlm_uploaded(meeting_id: str) -> None:
    """Record that the NLM PDF for this meeting was successfully uploaded."""
    with FileLock(_lock_path(), timeout=_LOCK_TIMEOUT):
        data = _load()
        uploaded = data.setdefault("_nlm_uploaded", [])
        if meeting_id not in uploaded:
            uploaded.append(meeting_id)
        data["_nlm_uploaded"] = uploaded[-500:]
        _save(data)


def check_and_mark_meeting(meeting_id: str) -> bool:
    """Atomically check if meeting is already processed and mark it if not.

    Returns True if meeting was already processed (caller should skip).
    Returns False if newly claimed (caller should proceed).
    Uses FileLock so concurrent requests cannot both pass the check.
    """
    with FileLock(_lock_path(), timeout=_LOCK_TIMEOUT):
        data = _load()
        processed = data.setdefault("_processed", [])
        if meeting_id in processed:
            return True
        processed.append(meeting_id)
        data["_processed"] = processed[-500:]  # cap to last 500
        _save(data)
    return False
