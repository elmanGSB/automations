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

UPDATE_TRANSCRIPT_MUTATION = """
mutation UpdateTranscript($id: String!, $title: String!) {
  updateTranscript(id: $id, title: $title) {
    id
    title
  }
}
"""

MEETINGS_QUERY = """
query GetMeetings($limit: Int!) {
  meetings(limit: $limit) {
    id
    title
    date
    participants {
      name
    }
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

    async def update_transcript_title(self, transcript_id: str, title: str) -> str:
        """Update a transcript's title. Returns the new title."""
        response = await self._client.post(
            FIREFLIES_GRAPHQL_URL,
            json={"query": UPDATE_TRANSCRIPT_MUTATION, "variables": {"id": transcript_id, "title": title}},
        )
        response.raise_for_status()
        payload = response.json()
        if "errors" in payload:
            errors = payload["errors"]
            msg = errors[0].get("message", "Unknown GraphQL error") if errors else "Unknown GraphQL error"
            raise RuntimeError(f"Fireflies API error: {msg}")
        data = payload.get("data", {})
        update_data = data.get("updateTranscript")
        if update_data is None:
            raise RuntimeError(f"Failed to update transcript: {transcript_id}")
        return update_data.get("title") or ""

    async def list_generic_meetings(self, limit: int = 100) -> list[dict]:
        """List meetings with generic/auto-generated names (dates, random strings, etc.)."""
        import re

        response = await self._client.post(
            FIREFLIES_GRAPHQL_URL,
            json={"query": MEETINGS_QUERY, "variables": {"limit": limit}},
        )
        response.raise_for_status()
        payload = response.json()
        if "errors" in payload:
            errors = payload["errors"]
            msg = errors[0].get("message", "Unknown GraphQL error") if errors else "Unknown GraphQL error"
            raise RuntimeError(f"Fireflies API error: {msg}")

        meetings = payload.get("data", {}).get("meetings", [])

        # Patterns for generic/auto-generated names
        generic_patterns = [
            r'^\d{4}-\d{2}-\d{2}',  # Dates
            r'^[a-z]{3,5}-[a-z]{3,5}-[a-z]{3,5}',  # Random like vze-ihdw-zov
            r'^apr-\d{2}',  # Month-day
            r'^\d{1,2}:\d{2}\s[ap]\.?m',  # Times
        ]

        generic = []
        for meeting in meetings:
            title = meeting.get("title", "").strip()
            is_generic = (
                any(re.match(pattern, title, re.IGNORECASE) for pattern in generic_patterns) or
                len(title) < 8 or
                title.count('-') > 2
            )

            if is_generic:
                generic.append({
                    "id": meeting["id"],
                    "title": title,
                    "date": meeting.get("date", ""),
                    "participants": len(meeting.get("participants", [])),
                })

        # Sort by date (newest first)
        generic.sort(key=lambda x: x["date"], reverse=True)
        return generic

    async def aclose(self) -> None:
        await self._client.aclose()
