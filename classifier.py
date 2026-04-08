import json
import re
from dataclasses import dataclass
import openai
from config import LITELLM_BASE_URL, LITELLM_API_KEY, LITELLM_MODEL, KNOWN_CATEGORIES

SYSTEM_PROMPT = """You are classifying a meeting transcript into a category.

Known categories:
- customer-discovery: Customer interviews, sales discovery calls, demos with prospects, and conversations with anyone in the target market — including retailers, suppliers, distributors, or end-users — whose feedback informs the product or go-to-market strategy
- investor-calls: Meetings with investors, VCs, angels, fundraising conversations
- team-syncs: Internal team meetings, standups, retrospectives, planning sessions
- competitors: Competitive analysis calls, conversations about or with competitors
- advisors: Advisor meetings, mentor conversations, board advisor check-ins

Return ONLY a JSON object with no other text:
{
  "category": "<category slug — use a known one or create a new descriptive slug>",
  "confidence": "high|medium|low",
  "reasoning": "<one sentence>"
}

If none of the known categories fit, invent a short descriptive slug (e.g. "conference-panel", "podcast-interview", "class-lecture")."""


def _extract_json(text: str) -> dict:
    """Extract JSON from LLM response, handling markdown code blocks and trailing commentary."""
    # Try to extract content between code fences first
    match = re.search(r"```(?:json)?\n?(.*?)\n?```", text, re.DOTALL)
    if match:
        text = match.group(1).strip()
    else:
        text = text.strip()
    return json.loads(text)


@dataclass
class ClassificationResult:
    category: str
    confidence: str
    reasoning: str

    @property
    def is_new_category(self) -> bool:
        return self.category not in KNOWN_CATEGORIES


async def classify_meeting(
    title: str,
    participants: list[str],
    summary: str,
    transcript_excerpt: str,
) -> ClassificationResult:
    client = openai.AsyncOpenAI(base_url=LITELLM_BASE_URL, api_key=LITELLM_API_KEY)

    user_message = (
        f"Title: {title}\n"
        f"Participants: {', '.join(participants)}\n"
        f"Summary: {summary}\n"
        f"Transcript excerpt (first 500 chars): {transcript_excerpt[:500]}"
    )

    response = await client.chat.completions.create(
        model=LITELLM_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        temperature=0.0,
        max_tokens=200,
    )

    raw = response.choices[0].message.content.strip()
    try:
        data = _extract_json(raw)
    except (json.JSONDecodeError, ValueError) as e:
        raise ValueError(f"Failed to parse classifier response: {e!r}\nRaw response: {raw!r}") from e

    return ClassificationResult(
        category=data["category"],
        confidence=data["confidence"],
        reasoning=data["reasoning"],
    )
