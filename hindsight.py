import httpx
import logging
from fireflies import Transcript
from classifier import ClassificationResult

HINDSIGHT_URL = "http://34.61.120.233:8888"
HINDSIGHT_API_KEY = "Vm1q6fguODdSX3lCWfMGshObtNoVUD0zTKVaVSM2"
BANK_ID = "broccoli-meetings"

logger = logging.getLogger(__name__)

_HEADERS = {
    "Authorization": f"Bearer {HINDSIGHT_API_KEY}",
    "Content-Type": "application/json",
}

# Category → participant_type mapping for entity labeling
_CATEGORY_PARTICIPANT_TYPE = {
    "customer-discovery": "customer",
    "investor-calls": "investor",
    "advisors": "advisor",
    "team-syncs": "team",
    "competitors": "customer",
}


async def retain_meeting(transcript: Transcript, classification: ClassificationResult) -> None:
    """Store meeting transcript context into the Hindsight meetings bank."""
    participants = ", ".join(transcript.participants) if transcript.participants else "Unknown"
    # Use full transcript excerpt (up to 800 chars) for richer extraction
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

    payload = {
        "items": [
            {
                "content": content,
                "document_id": f"meeting-{transcript.id}",
                "context": f"{classification.category} meeting with {participants}",
                "tags": [
                    f"category:{classification.category}",
                    f"confidence:{classification.confidence}",
                    f"participant_type:{participant_type}",
                ],
            }
        ]
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{HINDSIGHT_URL}/v1/default/banks/{BANK_ID}/memories/retain",
            headers=_HEADERS,
            json=payload,
        )
        resp.raise_for_status()


async def retain_novel_insights(meeting_title: str, category: str, novel_analysis: str) -> None:
    """Store NotebookLM Prompt 2 novel insights for a meeting into Hindsight."""
    content = (
        f"Novel insights from interview: {meeting_title}\n"
        f"Category: {category}\n\n"
        f"{novel_analysis}"
    )

    participant_type = _CATEGORY_PARTICIPANT_TYPE.get(category, "customer")

    payload = {
        "items": [
            {
                "content": content,
                "document_id": f"novel-insights-{meeting_title.lower().replace(' ', '-')[:60]}",
                "context": f"Novel insights analysis for {category} interview",
                "tags": [
                    f"category:{category}",
                    f"participant_type:{participant_type}",
                    "type:novel-insight",
                    "finding_type:pain-point",
                    "finding_type:workaround",
                    "finding_type:emotional-driver",
                    "finding_type:quote",
                ],
            }
        ]
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{HINDSIGHT_URL}/v1/default/banks/{BANK_ID}/memories/retain",
            headers=_HEADERS,
            json=payload,
        )
        resp.raise_for_status()
