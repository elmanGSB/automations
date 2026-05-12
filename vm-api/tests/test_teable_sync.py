"""Tests for the /health/teable_sync reconciliation endpoint."""

import asyncpg
import pytest
from unittest.mock import AsyncMock, MagicMock
from httpx import AsyncClient, ASGITransport


def make_mock_pool(row=None, exc=None):
    pool = MagicMock(spec=asyncpg.Pool)
    if exc is not None:
        pool.fetchrow = AsyncMock(side_effect=exc)
    else:
        pool.fetchrow = AsyncMock(return_value=row)
    pool.close = AsyncMock()
    return pool


@pytest.fixture
def patch_auth(monkeypatch):
    import main
    monkeypatch.setattr(main, "VM_API_SECRET", "test-secret")
    return {"Authorization": "Bearer test-secret"}


def _row(pg, teable, missing, extra):
    """asyncpg Record-like dict that supports `row["col"]` access."""
    return {
        "pg_count": pg,
        "teable_count": teable,
        "missing_in_teable": missing,
        "extra_in_teable": extra,
    }


@pytest.mark.asyncio
async def test_teable_sync_reports_ok_when_in_sync(monkeypatch, patch_auth):
    import main
    monkeypatch.setattr(main, "pool", make_mock_pool(row=_row(26, 26, [], [])))
    async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as client:
        resp = await client.get("/health/teable_sync", headers=patch_auth)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["postgres_interviews"] == 26
    assert body["teable_interviews"] == 26
    assert body["missing_in_teable"] == []
    assert body["extra_in_teable"] == []


@pytest.mark.asyncio
async def test_teable_sync_reports_drift_when_missing_in_teable(monkeypatch, patch_auth):
    import main
    monkeypatch.setattr(main, "pool", make_mock_pool(row=_row(27, 26, ["ff-new-123"], [])))
    async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as client:
        resp = await client.get("/health/teable_sync", headers=patch_auth)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "drift"
    assert body["missing_in_teable"] == ["ff-new-123"]
    assert body["extra_in_teable"] == []


@pytest.mark.asyncio
async def test_teable_sync_reports_drift_when_extra_in_teable(monkeypatch, patch_auth):
    import main
    monkeypatch.setattr(main, "pool", make_mock_pool(row=_row(26, 27, [], ["ff-orphan-1"])))
    async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as client:
        resp = await client.get("/health/teable_sync", headers=patch_auth)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "drift"
    assert body["extra_in_teable"] == ["ff-orphan-1"]


@pytest.mark.asyncio
async def test_teable_sync_handles_missing_teable_table(monkeypatch, patch_auth):
    import main
    monkeypatch.setattr(
        main, "pool", make_mock_pool(exc=asyncpg.exceptions.UndefinedTableError("table missing"))
    )
    async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as client:
        resp = await client.get("/health/teable_sync", headers=patch_auth)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "error"
    assert body["error"] == "teable_table_missing"


@pytest.mark.asyncio
async def test_teable_sync_requires_auth(monkeypatch):
    import main
    monkeypatch.setattr(main, "VM_API_SECRET", "test-secret")
    monkeypatch.setattr(main, "pool", make_mock_pool(row=_row(0, 0, [], [])))
    async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as client:
        resp = await client.get("/health/teable_sync")
    assert resp.status_code == 401
