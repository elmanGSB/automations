import httpx
import json
import logging
from fireflies import Transcript
from classifier import ClassificationResult
from config import HINDSIGHT_API_KEY

HINDSIGHT_URL = "http://34.61.120.233:8888"
BANK_ID = "broccoli-meetings"

logger = logging.getLogger(__name__)

_HEADERS = {
    "Authorization": f"Bearer {HINDSIGHT_API_KEY}",
    "Content-Type": "application/json",
}

# Category -> participant_type mapping for entity labeling
_CATEGORY_PARTICIPANT_TYPE = {
    "customer-discovery": "customer",
    "investor-calls": "investor",
    "advisors": "advisor",
    "team-syncs": "team",
    "competitors": "customer",
}


async def _mcp_retain(content: str, context: str, tags: list[str], document_id: str) -> None:
    """Call the Hindsight MCP retain tool via JSON-RPC over SSE."""
    payload = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {
            "name": "retain",
            "arguments": {
                "content": content,
                "context": context,
                "tags": tags,
                "document_id": document_id,
                "bank_id": BANK_ID,
            },
        },
        "id": 1,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(f"{HINDSIGHT_URL}/mcp/", headers=_HEADERS, json=payload)
        resp.raise_for_status()
        # SSE response: parse the data line
        for line in resp.text.splitlines():
            if line.startswith("data: "):
                data = json.loads(line[6:])
                if "error" in data:
                    raise RuntimeError(f"MCP retain error: {data['error']}")
                return
        logger.warning("No data line in MCP response: %s", resp.text[:200])


async def retain_meeting(transcript: Transcript, classification: ClassificationResult) -> None:
    """Store meeting transcript context into the Hindsight meetings bank."""
    participants = ", ".join(transcript.participants) if transcript.participants else "Unknown"
    excerpt = " ".join(s.text for s in transcript.sentences[:60])[:1200]

    content = (
        f"Meeting: {transcript.title}\n"
        f"Category: {classification.category}\n"
        f"Participants: {participants}\n"
        f"Summary: {transcript.summary_overview or 'No summary available'}\n"
        f"Classification reasoning: {classification.reasoning}\n\n"
        f"Transcript excerpt:\n{excerpt}"
    )

    participant_type = _CATEGORY_PARTICIPANT_TYPE.get(classification.category, "customer")
    tags = [
        f"category:{classification.category}",
        f"confidence:{classification.confidence}",
        f"participant_type:{participant_type}",
    ]

    await _mcp_retain(
        content=content,
        context=f"{classification.category} meeting with {participants}",
        tags=tags,
        document_id=f"meeting-{transcript.id}",
    )


async def retain_novel_insights(meeting_title: str, category: str, novel_analysis: str) -> None:
    """Store NotebookLM Prompt 2 novel insights for a meeting into Hindsight."""
    content = (
        f"Novel insights from interview: {meeting_title}\n"
        f"Category: {category}\n\n"
        f"{novel_analysis}"
    )

    participant_type = _CATEGORY_PARTICIPANT_TYPE.get(category, "customer")
    tags = [
        f"category:{category}",
        f"participant_type:{participant_type}",
        "type:novel-insight",
    ]

    await _mcp_retain(
        content=content,
        context=f"Novel insights analysis for {category} interview",
        tags=tags,
        document_id=f"novel-insights-{meeting_title.lower().replace(' ', '-')[:60]}",
    )
