import httpx
import logging
from fireflies import Transcript
from classifier import ClassificationResult

HINDSIGHT_URL = "http://34.61.120.233:8888/mcp/"
HINDSIGHT_API_KEY = "Vm1q6fguODdSX3lCWfMGshObtNoVUD0zTKVaVSM2"
BANK_ID = "meetings"

logger = logging.getLogger(__name__)

_HEADERS = {
    "Authorization": f"Bearer {HINDSIGHT_API_KEY}",
    "Content-Type": "application/json",
}


async def _call(payload: dict) -> None:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(HINDSIGHT_URL, headers=_HEADERS, json=payload)
        resp.raise_for_status()


async def retain_meeting(transcript: Transcript, classification: ClassificationResult) -> None:
    """Store meeting summary and key insights into the Hindsight meetings bank."""
    participants = ", ".join(transcript.participants) if transcript.participants else "Unknown"
    excerpt = " ".join(s.text for s in transcript.sentences[:40])

    content = (
        f"Meeting: {transcript.title}\n"
        f"Category: {classification.category} (confidence: {classification.confidence})\n"
        f"Participants: {participants}\n"
        f"Summary: {transcript.summary_overview or 'No summary available'}\n"
        f"Classification reasoning: {classification.reasoning}\n"
        f"Transcript excerpt: {excerpt[:800]}"
    )

    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "retain",
            "arguments": {
                "content": content,
                "context": classification.category,
                "tags": [
                    f"category:{classification.category}",
                    f"confidence:{classification.confidence}",
                ],
                "bank_id": BANK_ID,
            },
        },
    }
    await _call(payload)


async def retain_novel_insights(meeting_title: str, category: str, novel_analysis: str) -> None:
    """Store Prompt 2 novel insights from a single interview into Hindsight."""
    content = (
        f"Novel insights from interview: {meeting_title}\n"
        f"Category: {category}\n\n"
        f"{novel_analysis}"
    )
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "retain",
            "arguments": {
                "content": content,
                "context": f"novel-insights:{category}",
                "tags": [f"category:{category}", "type:novel-insight"],
                "bank_id": BANK_ID,
            },
        },
    }
    await _call(payload)
