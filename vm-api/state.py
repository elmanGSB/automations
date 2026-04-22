import json
import os
import sys
import tempfile
from contextlib import contextmanager
from fcntl import flock, LOCK_EX, LOCK_UN
from typing import Callable, Optional
from config import STATE_FILE as _DEFAULT_STATE_FILE

# Only set STATE_FILE if this module is being loaded fresh (not reloaded into
# an already-patched module). This allows tests to patch state.STATE_FILE and
# then call reload() without losing the patched value.
if "state" not in sys.modules or not hasattr(sys.modules.get("state"), "STATE_FILE"):
    STATE_FILE = _DEFAULT_STATE_FILE

# Bound the _processed list so state.json does not grow unbounded. Kept
# FIFO (oldest dropped); 500 is large enough to cover realistic webhook
# replay windows.
PROCESSED_CAP = 500


def _atomic_write(path: str, data: dict) -> None:
    """Write JSON atomically via a tempfile in the same dir + rename.

    Caller MUST hold the lock — this function does not lock.
    """
    dir_name = os.path.dirname(path) or "."
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


@contextmanager
def _locked():
    """Acquire an exclusive flock on STATE_FILE.lock for the duration.

    Wraps the full read-modify-write transaction so concurrent callers
    cannot interleave and lose updates.
    """
    state_file = sys.modules[__name__].STATE_FILE
    lock_file = state_file + ".lock"
    with open(lock_file, "w") as lock_fd:
        flock(lock_fd, LOCK_EX)
        try:
            yield
        finally:
            flock(lock_fd, LOCK_UN)


def _load_unlocked() -> dict:
    """Read state.json without acquiring the lock. Caller must hold it
    (or not care about concurrent writers, e.g. single-threaded reads).
    """
    path = sys.modules[__name__].STATE_FILE
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return json.load(f)


def _transact(mutator: Callable[[dict], None]) -> None:
    """Run a load-modify-write transaction under the state lock.

    `mutator` receives the current state dict and mutates it in place.
    """
    with _locked():
        data = _load_unlocked()
        mutator(data)
        _atomic_write(sys.modules[__name__].STATE_FILE, data)


def _load() -> dict:
    """Public read. Single read is safe without the lock (atomic rename
    from _atomic_write gives us a consistent snapshot)."""
    return _load_unlocked()


def get_notebook_id(category: str) -> Optional[str]:
    """Return the NotebookLM notebook ID for a category, or None if not found."""
    return _load().get(category)


def save_notebook_id(category: str, notebook_id: str) -> None:
    """Persist a new category -> notebook ID mapping."""
    def _mutate(data: dict) -> None:
        data[category] = notebook_id
    _transact(_mutate)


def get_all_notebooks() -> dict:
    """Return all category -> notebook ID mappings (excludes internal keys)."""
    data = _load()
    return {k: v for k, v in data.items() if not k.startswith("_")}


def is_meeting_processed(meeting_id: str) -> bool:
    """Return True if this meeting has already been processed."""
    return meeting_id in _load().get("_processed", [])


def mark_meeting_processed(meeting_id: str) -> None:
    """Record a meeting ID as processed to prevent duplicate runs.

    List is capped at PROCESSED_CAP entries, FIFO (oldest dropped).
    """
    def _mutate(data: dict) -> None:
        processed = data.setdefault("_processed", [])
        if meeting_id not in processed:
            processed.append(meeting_id)
        if len(processed) > PROCESSED_CAP:
            data["_processed"] = processed[-PROCESSED_CAP:]
    _transact(_mutate)


def get_or_create_notebook_id(category: str, create_fn) -> tuple[str, bool]:
    """Get existing notebook ID or create and return it.

    Returns (notebook_id, is_new) where is_new=True iff this call
    observed the category as missing AND called create_fn. Concurrent
    calls for the same missing category serialize on the state lock,
    so exactly one caller sees is_new=True and all callers return the
    same persisted id.
    """
    existing = get_notebook_id(category)
    if existing:
        return (existing, False)

    result: dict = {}

    def _mutate(data: dict) -> None:
        # Re-check under the lock — another caller may have created it.
        if category in data:
            result["id"] = data[category]
            result["is_new"] = False
            return
        notebook_id = create_fn()
        data[category] = notebook_id
        result["id"] = notebook_id
        result["is_new"] = True

    _transact(_mutate)
    return (result["id"], result["is_new"])


def is_nlm_uploaded(meeting_id: str) -> bool:
    """Check if NotebookLM upload is complete for a meeting."""
    return meeting_id in _load().get("_nlm_uploaded", [])


def mark_nlm_uploaded(meeting_id: str) -> None:
    """Record that NotebookLM upload is complete for a meeting."""
    def _mutate(data: dict) -> None:
        uploaded = data.setdefault("_nlm_uploaded", [])
        if meeting_id not in uploaded:
            uploaded.append(meeting_id)
    _transact(_mutate)
