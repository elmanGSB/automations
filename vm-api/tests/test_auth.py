import asyncpg
import pytest
from unittest.mock import AsyncMock, MagicMock
from httpx import AsyncClient, ASGITransport


def make_mock_pool():
    pool = MagicMock(spec=asyncpg.Pool)
    pool.fetchval = AsyncMock(return_value=1)
    pool.fetchrow = AsyncMock(return_value=None)
    pool.fetch = AsyncMock(return_value=[])
    pool.execute = AsyncMock(return_value="UPDATE 0")
    pool.close = AsyncMock()
    return pool


@pytest.fixture
def mock_pool(monkeypatch):
    pool = make_mock_pool()
    import main
    monkeypatch.setattr(main, "pool", pool)
    return pool


@pytest.fixture
def app_client(mock_pool):
    from main import app
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# --- require_auth: fail-closed when secret unset ---

@pytest.mark.asyncio
async def test_pipeline_run_rejects_when_secret_unset(app_client, monkeypatch):
    """When VM_API_SECRET is not set, the auth-gated endpoint must reject."""
    import main
    monkeypatch.setattr(main, "VM_API_SECRET", "")
    async with app_client as client:
        resp = await client.post(
            "/api/pipeline/run",
            json={"meeting_id": "abc"},
        )
    assert resp.status_code == 500
    assert "not configured" in resp.json()["detail"].lower()


# --- /api/interviews requires auth ---

@pytest.mark.asyncio
async def test_interviews_requires_auth(app_client, monkeypatch):
    import main
    monkeypatch.setattr(main, "VM_API_SECRET", "mysecret")
    async with app_client as client:
        resp = await client.get("/api/interviews")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_interviews_accepts_valid_token(app_client, monkeypatch):
    import main
    monkeypatch.setattr(main, "VM_API_SECRET", "mysecret")
    async with app_client as client:
        resp = await client.get(
            "/api/interviews",
            headers={"Authorization": "Bearer mysecret"},
        )
    assert resp.status_code == 200
