import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from classifier import classify_meeting, ClassificationResult


def _mock_httpx_response(body: str) -> MagicMock:
    """Build a fake httpx response that classifier.classify_meeting can parse."""
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"content": [{"text": body}]}
    return mock_response


async def test_classify_customer_meeting():
    body = '{"category": "customer-discovery", "confidence": "high", "reasoning": "Sales discovery call."}'
    mock_response = _mock_httpx_response(body)

    with patch("classifier.httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.post = AsyncMock(return_value=mock_response)

        result = await classify_meeting(
            title="Discovery call - Acme Corp",
            participants=["alice@acme.com", "me@company.com"],
            summary="Discussion about product pricing and onboarding needs.",
            transcript_excerpt="[INTERVIEWEE] Alice: What does your enterprise plan include?",
        )

    assert result.category == "customer-discovery"
    assert result.confidence == "high"
    assert isinstance(result.reasoning, str)
    assert result.is_new_category is False


async def test_classify_unknown_creates_slug():
    body = '{"category": "conference-panel", "confidence": "medium", "reasoning": "Panel discussion."}'
    mock_response = _mock_httpx_response(body)

    with patch("classifier.httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.post = AsyncMock(return_value=mock_response)

        result = await classify_meeting(
            title="TechCrunch Panel 2026",
            participants=["moderator@tc.com"],
            summary="Panel about AI trends.",
            transcript_excerpt="[INTERVIEWEE] Moderator: Welcome to the panel.",
        )

    assert result.category == "conference-panel"
    assert result.is_new_category is True


async def test_classify_handles_malformed_json():
    """Claude occasionally returns JSON wrapped in markdown — handle gracefully."""
    body = '```json\n{"category": "advisors", "confidence": "high", "reasoning": "Advisor meeting."}\n```'
    mock_response = _mock_httpx_response(body)

    with patch("classifier.httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.post = AsyncMock(return_value=mock_response)

        result = await classify_meeting(
            title="Advisor call with John",
            participants=["john@advisor.com"],
            summary="Guidance on product strategy.",
            transcript_excerpt="[INTERVIEWEE] John: Let me share some feedback.",
        )

    assert result.category == "advisors"


async def test_classify_handles_json_with_trailing_text():
    """LLM sometimes adds commentary after the closing code fence."""
    body = '```json\n{"category": "team-syncs", "confidence": "high", "reasoning": "Internal standup."}\n```\n\nNote: team meeting.'
    mock_response = _mock_httpx_response(body)

    with patch("classifier.httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.post = AsyncMock(return_value=mock_response)

        result = await classify_meeting(
            title="Weekly standup",
            participants=["alice@co.com"],
            summary="Weekly team sync.",
            transcript_excerpt="[BROCCOLI TEAM] Alice: Any blockers?",
        )

    assert result.category == "team-syncs"
