import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from classifier import classify_meeting, ClassificationResult


async def test_classify_customer_meeting():
    mock_completion = MagicMock()
    mock_completion.choices[0].message.content = (
        '{"category": "customer-discovery", "confidence": "high", '
        '"reasoning": "Sales discovery call with external company contact."}'
    )

    with patch("classifier.openai.AsyncOpenAI") as MockClient:
        instance = MockClient.return_value
        instance.chat.completions.create = AsyncMock(return_value=mock_completion)

        result = await classify_meeting(
            title="Discovery call - Acme Corp",
            participants=["alice@acme.com", "me@company.com"],
            summary="Discussion about product pricing and onboarding needs.",
            transcript_excerpt="Alice: What does your enterprise plan include?",
        )

    assert result.category == "customer-discovery"
    assert result.confidence == "high"
    assert isinstance(result.reasoning, str)
    assert result.is_new_category is False


async def test_classify_unknown_creates_slug():
    mock_completion = MagicMock()
    mock_completion.choices[0].message.content = (
        '{"category": "conference-panel", "confidence": "medium", '
        '"reasoning": "Panel discussion at a tech conference."}'
    )

    with patch("classifier.openai.AsyncOpenAI") as MockClient:
        instance = MockClient.return_value
        instance.chat.completions.create = AsyncMock(return_value=mock_completion)

        result = await classify_meeting(
            title="TechCrunch Panel 2026",
            participants=["moderator@tc.com"],
            summary="Panel about AI trends.",
            transcript_excerpt="Moderator: Welcome to the panel.",
        )

    assert result.category == "conference-panel"
    assert result.is_new_category is True


async def test_classify_handles_malformed_json():
    """Claude occasionally returns JSON wrapped in markdown — handle gracefully."""
    mock_completion = MagicMock()
    mock_completion.choices[0].message.content = (
        '```json\n{"category": "advisors", "confidence": "high", "reasoning": "Advisor meeting."}\n```'
    )

    with patch("classifier.openai.AsyncOpenAI") as MockClient:
        instance = MockClient.return_value
        instance.chat.completions.create = AsyncMock(return_value=mock_completion)

        result = await classify_meeting(
            title="Advisor call with John",
            participants=["john@advisor.com"],
            summary="Guidance on product strategy.",
            transcript_excerpt="John: Let me share some feedback.",
        )

    assert result.category == "advisors"
