# vm-api/tests/test_notifier.py
"""Tests for the Telegram notifier — the alert path that error handling depends on.

The silent-fail behaviour this module replaced was the root cause of an
operational incident: Fireflies extraction would raise inside a FastAPI
BackgroundTask, get swallowed, and never notify anyone. These tests lock in
the behaviour that keeps that class of failure visible:

  1. send_error must post to Telegram when called
  2. send_error must raise KeyError (not silently no-op) when the VM is
     misconfigured
  3. send_error must never leak the bot token into exception messages
  4. _run_extraction must always call send_error on failure and must never
     re-raise from the alert path
"""
import os

# config.py reads FIREFLIES_API_KEY at import time; satisfy that before
# importing notifier (which transitively imports config).
os.environ.setdefault("FIREFLIES_API_KEY", "test-fireflies-key")

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

import notifier


@pytest.fixture
def telegram_env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:SECRET_TOKEN_ABC")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "-1001234567890")


async def test_send_error_posts_to_telegram(telegram_env):
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value.post = AsyncMock(return_value=mock_response)
    mock_client.__aexit__.return_value = None

    with patch("notifier.httpx.AsyncClient", return_value=mock_client):
        await notifier.send_error("Boom", "Traceback detail", meeting_id="abc123")

    mock_client.__aenter__.return_value.post.assert_called_once()
    call = mock_client.__aenter__.return_value.post.call_args
    url = call.args[0]
    assert url == "https://api.telegram.org/bot123:SECRET_TOKEN_ABC/sendMessage"
    payload = call.kwargs["json"]
    assert payload["chat_id"] == "-1001234567890"
    assert payload["parse_mode"] == "HTML"
    assert "Boom" in payload["text"]
    assert "Traceback detail" in payload["text"]
    assert "meeting_id: abc123" in payload["text"]


async def test_send_error_escapes_html(telegram_env):
    """Payload must escape HTML so <script> and & never render as markup."""
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value.post = AsyncMock(return_value=mock_response)
    mock_client.__aexit__.return_value = None

    with patch("notifier.httpx.AsyncClient", return_value=mock_client):
        await notifier.send_error("<script>alert(1)</script>", "a & b")

    payload = mock_client.__aenter__.return_value.post.call_args.kwargs["json"]
    assert "<script>" not in payload["text"]
    assert "&lt;script&gt;" in payload["text"]
    assert "a &amp; b" in payload["text"]


async def test_send_error_raises_keyerror_when_token_missing(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
    with pytest.raises(KeyError):
        await notifier.send_error("x", "y")


async def test_send_error_raises_keyerror_when_chat_id_missing(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "abc")
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    with pytest.raises(KeyError):
        await notifier.send_error("x", "y")


async def test_send_error_scrubs_token_from_http_error(telegram_env):
    """httpx.HTTPStatusError carries the full URL (including the bot token).
    send_error must re-raise as RuntimeError with `from None` so the token
    never reaches logs."""
    bad_response = MagicMock(spec=httpx.Response)
    bad_response.status_code = 401
    status_err = httpx.HTTPStatusError(
        "401 Unauthorized",
        request=MagicMock(url="https://api.telegram.org/bot123:SECRET_TOKEN_ABC/sendMessage"),
        response=bad_response,
    )
    raising_response = MagicMock()
    raising_response.raise_for_status = MagicMock(side_effect=status_err)
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value.post = AsyncMock(return_value=raising_response)
    mock_client.__aexit__.return_value = None

    with patch("notifier.httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(RuntimeError) as exc_info:
            await notifier.send_error("x", "y")

    # The re-raised RuntimeError must carry only the status code, never the URL.
    assert "SECRET_TOKEN_ABC" not in str(exc_info.value)
    assert "401" in str(exc_info.value)
    # `from None` must suppress the original exception chain.
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__suppress_context__ is True


async def test_run_extraction_calls_notifier_on_failure(telegram_env, monkeypatch):
    """The primary regression test: when extraction fails inside the
    FastAPI BackgroundTask, send_error must fire."""
    import main

    monkeypatch.setattr(main, "FIREFLIES_API_KEY", "fake-key")
    monkeypatch.setattr(main, "pool", MagicMock())

    mock_ff = MagicMock()
    mock_ff.fetch_transcript = AsyncMock(side_effect=RuntimeError("fireflies API down"))
    mock_ff.aclose = AsyncMock()

    with patch("main.FirefliesClient", return_value=mock_ff), \
         patch("notifier.send_error", new_callable=AsyncMock) as mock_send:
        await main._run_extraction("meeting-xyz")

    mock_send.assert_called_once()
    _args, kwargs = mock_send.call_args
    assert mock_send.call_args.args[0] == "Fireflies extraction failed"
    assert "RuntimeError" in mock_send.call_args.args[1]
    assert "fireflies API down" in mock_send.call_args.args[1]
    assert kwargs["meeting_id"] == "meeting-xyz"


async def test_run_extraction_swallows_alert_path_errors(telegram_env, monkeypatch):
    """If Telegram itself is down, the alert-path error must not propagate —
    it would crash the BackgroundTask and mask the original failure."""
    import main

    monkeypatch.setattr(main, "FIREFLIES_API_KEY", "fake-key")
    monkeypatch.setattr(main, "pool", MagicMock())

    mock_ff = MagicMock()
    mock_ff.fetch_transcript = AsyncMock(side_effect=RuntimeError("primary failure"))
    mock_ff.aclose = AsyncMock()

    with patch("main.FirefliesClient", return_value=mock_ff), \
         patch("notifier.send_error", new_callable=AsyncMock,
               side_effect=RuntimeError("Telegram API 500")):
        # Must not raise.
        await main._run_extraction("meeting-xyz")
