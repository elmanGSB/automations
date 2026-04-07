import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from notifier import notify_new_category

async def test_notify_sends_telegram_message():
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient") as MockClient:
        mock_instance = AsyncMock()
        MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_instance.post = AsyncMock(return_value=mock_response)

        await notify_new_category(
            category="conference-panel",
            meeting_title="TechCrunch Panel 2026",
            meeting_id="abc123",
            notebook_id="nb-xyz",
        )

    assert mock_instance.post.called
    call_kwargs = mock_instance.post.call_args.kwargs
    payload = call_kwargs["json"]
    assert "conference-panel" in payload["text"]
    assert "TechCrunch Panel 2026" in payload["text"]
    assert payload["parse_mode"] == "Markdown"

async def test_notify_uses_correct_bot_token():
    """Verify the Telegram API URL uses the configured bot token."""
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient") as MockClient:
        mock_instance = AsyncMock()
        MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_instance.post = AsyncMock(return_value=mock_response)

        with patch("notifier.TELEGRAM_BOT_TOKEN", "test-bot-token-123"):
            await notify_new_category(
                category="podcast-interview",
                meeting_title="My Podcast",
                meeting_id="xyz",
                notebook_id="nb-abc",
            )

    url = mock_instance.post.call_args.args[0]
    assert "test-bot-token-123" in url
    assert "sendMessage" in url

async def test_notify_includes_notebook_id():
    """Verify notebook ID is included in the message for easy reference."""
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient") as MockClient:
        mock_instance = AsyncMock()
        MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_instance.post = AsyncMock(return_value=mock_response)

        await notify_new_category(
            category="class-lecture",
            meeting_title="CS101 Week 3",
            meeting_id="meet-999",
            notebook_id="nb-class-001",
        )

    payload = mock_instance.post.call_args.kwargs["json"]
    assert "nb-class-001" in payload["text"]
