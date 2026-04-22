"""
Fireflies GraphQL client — fetches full transcript by meeting ID.
Copied from ~/interview-router/fireflies.py on Paperclip VM.
"""

from dataclasses import dataclass

import httpx

FIREFLIES_GRAPHQL_URL = "https://api.fireflies.ai/graphql"

TRANSCRIPT_QUERY = """
query GetTranscript($id: String!) {
  transcript(id: $id) {
    id
    title
    date
    duration
    participants
    sentences {
      index
      speaker_name
      text
      start_time
      end_time
    }
    summary {
      overview
      action_items
      keywords
    }
  }
}
"""

UPDATE_MEETING_TITLE_MUTATION = """
mutation UpdateMeetingTitle($input: UpdateMeetingTitleInput!) {
  updateMeetingTitle(input: $input) {
    id
    title
  }
}
"""


@dataclass
class Sentence:
    index: int
    speaker_name: str
    text: str
    start_time: float
    end_time: float


@dataclass
class Transcript:
    id: str
    title: str
    date: str
    duration: int
    participants: list[str]
    sentences: list[Sentence]
    summary_overview: str
    summary_action_items: list[str]
    summary_keywords: list[str]


class FirefliesClient:
    def __init__(self, api_key: str):
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            # Cloudflare in front of api.fireflies.ai blocks the default python-httpx UA (403)
            "User-Agent": "broccoli-ai-automations/1.0 (+https://jumpersapp.com)",
        }
        self._client = httpx.AsyncClient(headers=self._headers, timeout=30.0)

    async def fetch_transcript(self, transcript_id: str) -> Transcript:
        response = await self._client.post(
            FIREFLIES_GRAPHQL_URL,
            json={"query": TRANSCRIPT_QUERY, "variables": {"id": transcript_id}},
        )
        response.raise_for_status()
        payload = response.json()
        if "errors" in payload:
            errors = payload["errors"]
            msg = errors[0].get("message", "Unknown GraphQL error") if errors else "Unknown GraphQL error"
            raise RuntimeError(f"Fireflies API error: {msg}")
        data = payload.get("data", {})
        transcript_data = data.get("transcript")
        if transcript_data is None:
            raise RuntimeError(f"Transcript not found: {transcript_id}")
        summary = transcript_data.get("summary") or {}
        return Transcript(
            id=transcript_data["id"],
            title=transcript_data.get("title") or "",
            date=transcript_data.get("date") or "",
            duration=transcript_data["duration"],
            participants=transcript_data.get("participants") or [],
            sentences=[
                Sentence(
                    index=s["index"],
                    speaker_name=s["speaker_name"] or "Unknown",
                    text=s["text"],
                    start_time=s["start_time"],
                    end_time=s["end_time"],
                )
                for s in transcript_data.get("sentences") or []
            ],
            summary_overview=summary.get("overview") or "",
            summary_action_items=summary.get("action_items") or [],
            summary_keywords=summary.get("keywords") or [],
        )

    async def update_meeting_title(self, meeting_id: str, title: str) -> str:
        """Update a meeting's title. Returns the new title."""
        response = await self._client.post(
            FIREFLIES_GRAPHQL_URL,
            json={"query": UPDATE_MEETING_TITLE_MUTATION, "variables": {"input": {"id": meeting_id, "title": title}}},
        )
        response.raise_for_status()
        payload = response.json()
        if "errors" in payload:
            errors = payload["errors"]
            msg = errors[0].get("message", "Unknown GraphQL error") if errors else "Unknown GraphQL error"
            raise RuntimeError(f"Fireflies API error: {msg}")
        data = payload.get("data", {})
        update_data = data.get("updateMeetingTitle")
        if update_data is None:
            raise RuntimeError(f"Failed to update meeting: {meeting_id}")
        return update_data.get("title") or ""

    async def aclose(self) -> None:
        await self._client.aclose()
