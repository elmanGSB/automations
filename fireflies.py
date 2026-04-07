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
        self._headers = {"Authorization": f"Bearer {api_key}"}

    async def fetch_transcript(self, transcript_id: str) -> Transcript:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                FIREFLIES_GRAPHQL_URL,
                json={"query": TRANSCRIPT_QUERY, "variables": {"id": transcript_id}},
                headers=self._headers,
                timeout=30.0,
            )
            response.raise_for_status()
            data = response.json()["data"]["transcript"]

        summary = data.get("summary") or {}
        return Transcript(
            id=data["id"],
            title=data["title"],
            date=data["date"],
            duration=data["duration"],
            participants=data.get("participants") or [],
            sentences=[
                Sentence(
                    index=s["index"],
                    speaker_name=s["speaker_name"] or "Unknown",
                    text=s["text"],
                    start_time=s["start_time"],
                    end_time=s["end_time"],
                )
                for s in data.get("sentences") or []
            ],
            summary_overview=summary.get("overview") or "",
            summary_action_items=summary.get("action_items") or [],
            summary_keywords=summary.get("keywords") or [],
        )
