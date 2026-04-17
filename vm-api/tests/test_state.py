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
