import threading
import pytest
import state as _state


@pytest.fixture
def tmp_state(tmp_path, monkeypatch):
    path = str(tmp_path / "state.json")
    monkeypatch.setattr(_state, "STATE_FILE", path)
    return path


def test_concurrent_mark_processed_no_data_loss(tmp_state):
    """Both meeting IDs must survive concurrent mark_meeting_processed calls."""
    errors = []

    def mark(mid):
        try:
            _state.mark_meeting_processed(mid)
        except Exception as e:
            errors.append(e)

    t1 = threading.Thread(target=mark, args=("meeting-A",))
    t2 = threading.Thread(target=mark, args=("meeting-B",))
    t1.start(); t2.start()
    t1.join(); t2.join()

    assert not errors
    assert _state.is_meeting_processed("meeting-A")
    assert _state.is_meeting_processed("meeting-B")


def test_mark_processed_caps_at_500(tmp_state):
    """_processed list must never exceed 500 entries."""
    for i in range(510):
        _state.mark_meeting_processed(f"meeting-{i}")
    import json
    with open(tmp_state) as f:
        data = json.load(f)
    assert len(data["_processed"]) == 500


def test_mark_nlm_uploaded_and_check(tmp_state):
    """is_nlm_uploaded must return False before and True after mark."""
    assert not _state.is_nlm_uploaded("mtg-1")
    _state.mark_nlm_uploaded("mtg-1")
    assert _state.is_nlm_uploaded("mtg-1")


def test_concurrent_mark_nlm_no_data_loss(tmp_state):
    """Both meeting IDs must survive concurrent mark_nlm_uploaded calls."""
    errors = []

    def mark(mid):
        try:
            _state.mark_nlm_uploaded(mid)
        except Exception as e:
            errors.append(e)

    t1 = threading.Thread(target=mark, args=("nlm-A",))
    t2 = threading.Thread(target=mark, args=("nlm-B",))
    t1.start(); t2.start()
    t1.join(); t2.join()

    assert not errors
    assert _state.is_nlm_uploaded("nlm-A")
    assert _state.is_nlm_uploaded("nlm-B")


def test_get_or_create_notebook_id_creates_when_missing(tmp_state):
    """create_fn must be called when no notebook exists for the category."""
    called = []
    def creator():
        called.append(1)
        return "nb-abc123"

    nb_id, is_new = _state.get_or_create_notebook_id("customer-discovery", creator)
    assert nb_id == "nb-abc123"
    assert is_new is True
    assert len(called) == 1
    assert _state.get_notebook_id("customer-discovery") == "nb-abc123"


def test_get_or_create_notebook_id_returns_existing(tmp_state):
    """create_fn must NOT be called when notebook already exists."""
    _state.save_notebook_id("customer-discovery", "existing-nb")
    called = []
    def creator():
        called.append(1)
        return "new-nb"

    nb_id, is_new = _state.get_or_create_notebook_id("customer-discovery", creator)
    assert nb_id == "existing-nb"
    assert is_new is False
    assert len(called) == 0


def test_save_notebook_id_concurrent_no_data_loss(tmp_state):
    """Concurrent save_notebook_id for different categories must both survive."""
    errors = []

    def save(cat, nbid):
        try:
            _state.save_notebook_id(cat, nbid)
        except Exception as e:
            errors.append(e)

    t1 = threading.Thread(target=save, args=("cat-A", "nb-1"))
    t2 = threading.Thread(target=save, args=("cat-B", "nb-2"))
    t1.start(); t2.start()
    t1.join(); t2.join()

    assert not errors
    assert _state.get_notebook_id("cat-A") == "nb-1"
    assert _state.get_notebook_id("cat-B") == "nb-2"
