import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fireflies import FirefliesClient, Transcript, Sentence

@pytest.mark.asyncio
async def test_fetch_transcript_returns_transcript():
    mock_response = {
        "data": {
            "transcript": {
                "id": "abc123",
                "title": "Customer call with Acme Corp",
                "date": "2026-04-07T14:00:00Z",
                "duration": 3600,
                "participants": ["alice@acme.com", "me@company.com"],
                "sentences": [
                    {
                        "index": 0,
                        "speaker_name": "Alice",
                        "text": "Tell me about your pricing.",
                        "start_time": 5.0,
                        "end_time": 8.2,
                    }
                ],
                "summary": {
                    "overview": "Discussion about pricing and onboarding.",
                    "action_items": ["Send pricing deck"],
                    "keywords": ["pricing", "onboarding"],
                },
            }
        }
    }

    mock_resp = MagicMock()
    mock_resp.json.return_value = mock_response
    mock_resp.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient") as MockClient:
        mock_client_instance = AsyncMock()
        MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client_instance)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_client_instance.post = AsyncMock(return_value=mock_resp)

        client = FirefliesClient(api_key="test-key")
        transcript = await client.fetch_transcript("abc123")

    assert transcript.id == "abc123"
    assert transcript.title == "Customer call with Acme Corp"
    assert len(transcript.sentences) == 1
    assert transcript.sentences[0].speaker_name == "Alice"
    assert transcript.sentences[0].text == "Tell me about your pricing."
    assert transcript.summary_overview == "Discussion about pricing and onboarding."
    assert transcript.summary_action_items == ["Send pricing deck"]
    assert transcript.summary_keywords == ["pricing", "onboarding"]
    assert transcript.participants == ["alice@acme.com", "me@company.com"]
    assert transcript.duration == 3600

@pytest.mark.asyncio
async def test_fetch_transcript_handles_missing_summary():
    mock_response = {
        "data": {
            "transcript": {
                "id": "xyz",
                "title": "Quick sync",
                "date": "2026-04-07T10:00:00Z",
                "duration": 600,
                "participants": [],
                "sentences": [],
                "summary": None,
            }
        }
    }

    mock_resp = MagicMock()
    mock_resp.json.return_value = mock_response
    mock_resp.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient") as MockClient:
        mock_client_instance = AsyncMock()
        MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client_instance)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_client_instance.post = AsyncMock(return_value=mock_resp)

        client = FirefliesClient(api_key="test-key")
        transcript = await client.fetch_transcript("xyz")

    assert transcript.summary_overview == ""
    assert transcript.summary_action_items == []
    assert transcript.summary_keywords == []
