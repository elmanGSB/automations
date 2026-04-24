import hashlib
import hmac

import asyncpg
import pytest
from unittest.mock import AsyncMock, MagicMock
from httpx import AsyncClient, ASGITransport


def _sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


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


# --- /webhook/fireflies: signature missing → 401 ---

@pytest.mark.asyncio
async def test_webhook_rejects_when_signature_missing(app_client, monkeypatch):
    import main
    monkeypatch.setattr(main, "FIREFLIES_WEBHOOK_SECRET", "wsec")
    async with app_client as client:
        resp = await client.post(
            "/webhook/fireflies",
            json={"eventType": "Transcription complete", "meetingId": "abc"},
        )
    assert resp.status_code == 401


# --- /webhook/fireflies: signature wrong → 401 ---

@pytest.mark.asyncio
async def test_webhook_rejects_wrong_signature(app_client, monkeypatch):
    import main
    monkeypatch.setattr(main, "FIREFLIES_WEBHOOK_SECRET", "wsec")
    async with app_client as client:
        resp = await client.post(
            "/webhook/fireflies",
            headers={"x-hub-signature": "sha256=deadbeef"},
            json={"eventType": "Transcription complete", "meetingId": "abc"},
        )
    assert resp.status_code == 401


# --- /webhook/fireflies: fail-closed when FIREFLIES_WEBHOOK_SECRET unset ---

@pytest.mark.asyncio
async def test_webhook_rejects_when_webhook_secret_unset(app_client, monkeypatch):
    import main
    monkeypatch.setattr(main, "FIREFLIES_WEBHOOK_SECRET", "")
    body = b'{"eventType":"Transcription complete","meetingId":"abc"}'
    async with app_client as client:
        resp = await client.post(
            "/webhook/fireflies",
            headers={
                "x-hub-signature": _sign("anysecret", body),
                "Content-Type": "application/json",
            },
            content=body,
        )
    assert resp.status_code == 401


# --- /webhook/fireflies: valid signature accepted ---

@pytest.mark.asyncio
async def test_webhook_accepts_valid_signature(app_client, monkeypatch):
    import main
    monkeypatch.setattr(main, "FIREFLIES_WEBHOOK_SECRET", "wsec")
    body = b'{"eventType":"ignored_event"}'
    async with app_client as client:
        resp = await client.post(
            "/webhook/fireflies",
            headers={
                "x-hub-signature": _sign("wsec", body),
                "Content-Type": "application/json",
            },
            content=body,
        )
    # 202 default for the route — signature passed, payload was a non-transcription
    # event so it short-circuits with status="ignored" but FastAPI still returns 202.
    assert resp.status_code == 202
    assert resp.json().get("status") == "ignored"


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
