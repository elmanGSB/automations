# vm-api/tests/test_digest.py
import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient, ASGITransport
import asyncpg


def make_mock_pool():
    pool = MagicMock(spec=asyncpg.Pool)
    pool.fetchval = AsyncMock(return_value=1)
    pool.close = AsyncMock()
    return pool


@pytest.fixture
async def mock_app_globals(monkeypatch):
    """Patch pool and app_event_loop — required for the 503 guard in the endpoint."""
    pool = make_mock_pool()
    import main
    monkeypatch.setattr(main, "pool", pool)
    # Use the test's running event loop so app_event_loop is not None
    monkeypatch.setattr(main, "app_event_loop", asyncio.get_running_loop())
    return pool


@pytest.fixture
def tmp_state_with_notebook(tmp_path, monkeypatch):
    state_file = str(tmp_path / "state.json")
    with open(state_file, "w") as f:
        # UUID format required — UUIDs are validated before subprocess
        json.dump({"customer-discovery": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"}, f)
    import state
    monkeypatch.setattr(state, "STATE_FILE", state_file)
    return state_file


@pytest.fixture
def tmp_state_empty(tmp_path, monkeypatch):
    state_file = str(tmp_path / "state.json")
    with open(state_file, "w") as f:
        json.dump({}, f)
    import state
    monkeypatch.setattr(state, "STATE_FILE", state_file)
    return state_file


@pytest.fixture
def tmp_state_with_invalid_notebook(tmp_path, monkeypatch):
    state_file = str(tmp_path / "state.json")
    with open(state_file, "w") as f:
        json.dump({"customer-discovery": "not-a-uuid"}, f)
    import state
    monkeypatch.setattr(state, "STATE_FILE", state_file)
    return state_file


@pytest.fixture
async def app_client(mock_app_globals):
    from main import app
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


VM_SECRET = "test-secret"

# run_coroutine_threadsafe substitute for tests: runs the coroutine immediately
# in the current event loop instead of scheduling it on the FastAPI loop
# (which doesn't exist in tests and would deadlock on .result()).
def _sync_coro_runner(coro, loop):
    """Synchronously run a coroutine — replaces run_coroutine_threadsafe in tests."""
    class _FakeResult:
        def __init__(self, value):
            self._value = value

        def result(self, timeout=None):
            return self._value

    result = asyncio.run(coro)
    return _FakeResult(result)


async def test_digest_runs_for_enabled_categories(app_client, tmp_state_with_notebook, monkeypatch):
    import main
    monkeypatch.setattr(main, "VM_API_SECRET", VM_SECRET)
    with patch("main.analyze_patterns", return_value="## Pain Points\nFoo bar.") as mock_analyze, \
         patch("main.send_patterns_report", new_callable=AsyncMock) as mock_send, \
         patch("main.asyncio") as mock_asyncio:
        # Wire up run_coroutine_threadsafe to use our sync runner
        mock_asyncio.run_coroutine_threadsafe.side_effect = _sync_coro_runner
        async with app_client as client:
            resp = await client.post(
                "/api/digest/run",
                headers={"Authorization": f"Bearer {VM_SECRET}"},
            )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "completed"
    assert data["results"]["customer-discovery"]["status"] == "ok"
    assert data["results"]["customer-discovery"]["patterns_char_count"] > 0
    mock_analyze.assert_called_once_with("a1b2c3d4-e5f6-7890-abcd-ef1234567890")
    mock_send.assert_called_once()


async def test_digest_skips_category_with_no_notebook(app_client, tmp_state_empty, monkeypatch):
    import main
    monkeypatch.setattr(main, "VM_API_SECRET", VM_SECRET)
    async with app_client as client:
        resp = await client.post(
            "/api/digest/run",
            headers={"Authorization": f"Bearer {VM_SECRET}"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["results"]["customer-discovery"]["status"] == "skipped"
    assert data["results"]["customer-discovery"]["reason"] == "no_notebook"


async def test_digest_requires_auth(app_client, monkeypatch):
    import main
    monkeypatch.setattr(main, "VM_API_SECRET", VM_SECRET)
    async with app_client as client:
        resp = await client.post("/api/digest/run")
    assert resp.status_code == 401


async def test_digest_rejects_invalid_notebook_id(app_client, tmp_state_with_invalid_notebook, monkeypatch):
    import main
    monkeypatch.setattr(main, "VM_API_SECRET", VM_SECRET)
    async with app_client as client:
        resp = await client.post(
            "/api/digest/run",
            headers={"Authorization": f"Bearer {VM_SECRET}"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["results"]["customer-discovery"]["status"] == "error"
    assert data["results"]["customer-discovery"]["error"] == "invalid_notebook_id"
