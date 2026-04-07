import pytest
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient, ASGITransport

# Import the app lazily inside tests to allow patches to work

async def test_health_endpoint():
    with patch("main.FIREFLIES_WEBHOOK_SECRET", ""):
        from main import app
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

async def test_webhook_accepted_for_transcription_complete():
    with (
        patch("main.FIREFLIES_WEBHOOK_SECRET", ""),
        patch("main.process_meeting", new_callable=AsyncMock) as mock_process,
    ):
        from importlib import import_module, reload
        import main as main_mod
        reload(main_mod)
        async with AsyncClient(
            transport=ASGITransport(app=main_mod.app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/webhook/fireflies",
                json={"eventType": "Transcription complete", "meetingId": "abc123"},
            )
    assert response.status_code == 200
    assert response.json()["status"] == "accepted"
    assert response.json()["meetingId"] == "abc123"

async def test_webhook_ignores_other_events():
    with patch("main.FIREFLIES_WEBHOOK_SECRET", ""):
        from importlib import reload
        import main as main_mod
        reload(main_mod)
        async with AsyncClient(
            transport=ASGITransport(app=main_mod.app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/webhook/fireflies",
                json={"eventType": "Meeting started", "meetingId": "abc123"},
            )
    assert response.status_code == 200
    assert response.json()["status"] == "ignored"

async def test_webhook_validates_signature_when_secret_set():
    import hmac, hashlib, json as jsonlib
    secret = "test-secret"
    body = jsonlib.dumps({"eventType": "Transcription complete", "meetingId": "abc123"}).encode()
    sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    with patch("main.FIREFLIES_WEBHOOK_SECRET", secret):
        from importlib import reload
        import main as main_mod
        reload(main_mod)
        async with AsyncClient(
            transport=ASGITransport(app=main_mod.app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/webhook/fireflies",
                content=body,
                headers={"content-type": "application/json", "x-hub-signature": sig},
            )
    assert response.status_code == 200

async def test_webhook_rejects_bad_signature():
    with patch("main.FIREFLIES_WEBHOOK_SECRET", "real-secret"):
        from importlib import reload
        import main as main_mod
        reload(main_mod)
        async with AsyncClient(
            transport=ASGITransport(app=main_mod.app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/webhook/fireflies",
                json={"eventType": "Transcription complete", "meetingId": "abc123"},
                headers={"x-hub-signature": "sha256=badsignature"},
            )
    assert response.status_code == 401

async def test_webhook_rejects_missing_meeting_id():
    with patch("main.FIREFLIES_WEBHOOK_SECRET", ""):
        from importlib import reload
        import main as main_mod
        reload(main_mod)
        async with AsyncClient(
            transport=ASGITransport(app=main_mod.app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/webhook/fireflies",
                json={"eventType": "Transcription complete"},
            )
    assert response.status_code == 400
