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


def test_mark_processed_does_not_evict(tmp_state):
    """_processed list must NOT evict — is_meeting_processed is the
    pipeline's idempotency gate. Any cap would let delayed webhook
    retries reprocess past meetings (duplicate discovery extraction,
    retention, notification). State.json size scales linearly with
    meeting count and is trivial at realistic volumes.
    """
    for i in range(510):
        _state.mark_meeting_processed(f"meeting-{i}")
    import json
    with open(tmp_state) as f:
        data = json.load(f)
    assert len(data["_processed"]) == 510
    # Spot-check: oldest and newest both retained.
    assert "meeting-0" in data["_processed"]
    assert "meeting-509" in data["_processed"]


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


def test_get_or_create_uses_lookup_hit_and_skips_create(tmp_state):
    """When lookup_fn finds an existing notebook, create_fn must NOT run.
    The found ID is saved to state and returned with is_new=False.
    """
    create_calls = []
    lookup_calls = []

    def creator():
        create_calls.append(1)
        return "should-not-be-used"

    def lookup():
        lookup_calls.append(1)
        return "found-by-title"

    nb_id, is_new = _state.get_or_create_notebook_id(
        "customer-discovery", create_fn=creator, lookup_fn=lookup
    )
    assert nb_id == "found-by-title"
    assert is_new is False
    assert lookup_calls == [1]
    assert create_calls == []
    assert _state.get_notebook_id("customer-discovery") == "found-by-title"


def test_get_or_create_falls_through_to_create_when_lookup_misses(tmp_state):
    """When lookup_fn returns None, create_fn must run normally."""
    def lookup():
        return None

    nb_id, is_new = _state.get_or_create_notebook_id(
        "customer-discovery",
        create_fn=lambda: "fresh-id",
        lookup_fn=lookup,
    )
    assert nb_id == "fresh-id"
    assert is_new is True


def test_get_or_create_falls_through_when_lookup_raises(tmp_state):
    """A flaky lookup (e.g. nlm CLI 400) must NOT block notebook creation."""
    def lookup():
        raise RuntimeError("nlm RPC drift")

    nb_id, is_new = _state.get_or_create_notebook_id(
        "customer-discovery",
        create_fn=lambda: "fresh-id",
        lookup_fn=lookup,
    )
    assert nb_id == "fresh-id"
    assert is_new is True


def test_get_or_create_skips_lookup_when_state_has_mapping(tmp_state):
    """Fast path: existing state mapping must short-circuit before lookup_fn."""
    _state.save_notebook_id("customer-discovery", "cached-id")
    lookup_calls = []

    def lookup():
        lookup_calls.append(1)
        return "from-nlm"

    nb_id, is_new = _state.get_or_create_notebook_id(
        "customer-discovery", create_fn=lambda: "x", lookup_fn=lookup
    )
    assert nb_id == "cached-id"
    assert is_new is False
    assert lookup_calls == []


def test_get_or_create_concurrent_same_category_one_wins(tmp_state):
    """Concurrent calls for the same missing category must persist exactly one ID."""
    barrier = threading.Barrier(2)
    results = []

    def create_and_register(name):
        barrier.wait()
        nb_id, is_new = _state.get_or_create_notebook_id(
            "customer-discovery",
            lambda: f"nb-{name}",
        )
        results.append((nb_id, is_new))

    t1 = threading.Thread(target=create_and_register, args=("t1",))
    t2 = threading.Thread(target=create_and_register, args=("t2",))
    t1.start(); t2.start()
    t1.join(); t2.join()

    persisted = _state.get_notebook_id("customer-discovery")
    assert persisted is not None
    # exactly one thread got is_new=True
    assert sum(1 for _, is_new in results if is_new) == 1
    # both threads agree on the same persisted id
    assert results[0][0] == results[1][0] == persisted
