"""Tests for meeting classifier."""
import json

import httpx
import pytest

import classifier
from classifier import classify_meeting


def _mock_client_factory(reply_text, capture=None):
    """Return a _make_client replacement whose AsyncClient is backed by an
    httpx.MockTransport that returns an OpenAI-shaped chat completion."""
    def handler(request):
        if capture is not None:
            capture["url"] = str(request.url)
            capture["headers"] = dict(request.headers)
            capture["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": reply_text}}]})

    transport = httpx.MockTransport(handler)
    return lambda: httpx.AsyncClient(transport=transport, timeout=5.0)


@pytest.mark.asyncio
async def test_classify_request_shape_and_parse(monkeypatch):
    """classify_meeting posts an OpenAI chat completion to LiteLLM with the
    Gemini model + bearer auth, and parses the choices[].message.content reply."""
    capture = {}
    monkeypatch.setattr(
        classifier,
        "_make_client",
        _mock_client_factory(
            '{"category": "team-syncs", "confidence": "high", "reasoning": "internal standup"}',
            capture,
        ),
    )

    result = await classify_meeting(
        title="Standup",
        participants=["a@x.com"],
        summary="daily sync",
        transcript_excerpt="[BROCCOLI TEAM]: status updates",
    )

    # Request shape
    assert capture["url"].endswith("/chat/completions")
    assert capture["body"]["model"] == "gemini-3-1-pro"
    assert capture["headers"]["authorization"].startswith("Bearer")
    assert [m["role"] for m in capture["body"]["messages"]] == ["system", "user"]

    # Parsed result
    assert result.category == "team-syncs"
    assert result.confidence == "high"
    assert result.reasoning == "internal standup"
    assert result.is_new_category is False


@pytest.mark.asyncio
async def test_classify_handles_json_code_fence(monkeypatch):
    """Gemini may wrap JSON in a ```json fence; _extract_json must strip it."""
    fenced = '```json\n{"category": "investor-calls", "confidence": "medium", "reasoning": "vc call"}\n```'
    monkeypatch.setattr(classifier, "_make_client", _mock_client_factory(fenced))

    result = await classify_meeting(
        title="VC", participants=["vc@fund.com"], summary="raise", transcript_excerpt="x"
    )
    assert result.category == "investor-calls"
    assert result.is_new_category is False


@pytest.mark.asyncio
async def test_classify_invented_slug_is_new_category(monkeypatch):
    """A classifier-invented slug not in KNOWN_CATEGORIES is flagged new."""
    monkeypatch.setattr(
        classifier,
        "_make_client",
        _mock_client_factory('{"category": "podcast-interview", "confidence": "low", "reasoning": "podcast"}'),
    )
    result = await classify_meeting(title="Pod", participants=[], summary="", transcript_excerpt="")
    assert result.category == "podcast-interview"
    assert result.is_new_category is True


@pytest.mark.asyncio
async def test_classify_raises_on_unparseable_reply(monkeypatch):
    """Non-JSON model output raises ValueError (caught upstream as classify_failed)."""
    monkeypatch.setattr(classifier, "_make_client", _mock_client_factory("not json at all"))
    with pytest.raises(ValueError):
        await classify_meeting(title="x", participants=[], summary="", transcript_excerpt="")


@pytest.mark.asyncio
async def test_tools_research_classification():
    """Test that tool evaluation calls are classified as tools-research, not advisors."""
    # John Beeker call data: discussing Windmill, NotebookLM, Raggy, Compose U
    result = await classify_meeting(
        title="Elman amador and Jon",
        participants=["elman@stanford.edu", "jonathanbeekman@gmail.com"],
        summary="Discussed strategic reassessment, food distribution pivot, AI automation tools (Windmill, NotebookLM CLI, Raggy, Compose U)",
        transcript_excerpt="""[BROCCOLI TEAM]: Jon, thanks for jumping on. We're looking at some workflow automation tools to streamline our operations. Have you looked at Windmill?

[INTERVIEWEE]: Yeah, I've actually been evaluating Windmill for some of my projects. It's pretty solid for building internal tools and automating workflows.

[BROCCOLI TEAM]: What's your take on the UI? Is it intuitive for non-technical users?

[INTERVIEWEE]: The UI is clean, and they've got good documentation. I've also been testing NotebookLM's CLI functionality for document extraction and analysis.""",
    )

    assert result.category == "tools-research"
    assert result.confidence in ["high", "medium", "low"]
    assert isinstance(result.reasoning, str)
    assert len(result.reasoning) > 0


@pytest.mark.asyncio
async def test_advisor_vs_tools_research_disambiguation():
    """Test that advisor business mentorship is distinguished from tool evaluation."""
    # Advisor business mentorship call
    advisor_result = await classify_meeting(
        title="Elman and Advisor: Growth Strategy",
        participants=["elman@stanford.edu", "advisor@example.com"],
        summary="Discussed business strategy, market positioning, hiring decisions for food distribution pivot",
        transcript_excerpt="""[BROCCOLI TEAM]: Looking for your input on our growth strategy for the food distribution business.

[INTERVIEWEE]: You should focus on building relationships with larger distributors first. The market consolidation is accelerating.

[BROCCOLI TEAM]: Any thoughts on hiring for this pivot?

[INTERVIEWEE]: Hire someone with 10+ years in food distribution. The relationships are critical.""",
    )

    assert advisor_result.category == "advisors"

    # Tool evaluation call (same meeting, different conversation)
    tools_result = await classify_meeting(
        title="Elman and Advisor: Automation Tools",
        participants=["elman@stanford.edu", "advisor@example.com"],
        summary="Evaluated Windmill, NotebookLM, and other workflow automation platforms for operations",
        transcript_excerpt="""[BROCCOLI TEAM]: We're considering different automation platforms. What do you think of Windmill?

[INTERVIEWEE]: Windmill is solid for internal tools. Have you looked at their API integrations?

[BROCCOLI TEAM]: How does it compare to NotebookLM for document processing?

[INTERVIEWEE]: Different use cases. Windmill is better for workflows, NotebookLM for document analysis.""",
    )

    assert tools_result.category == "tools-research"
