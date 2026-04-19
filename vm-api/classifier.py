import json
import re
from dataclasses import dataclass
import httpx
from config import KNOWN_CATEGORIES

CLAUDE_PROXY_URL = "http://127.0.0.1:8199/v1/messages"

SYSTEM_PROMPT = """You are classifying a meeting transcript into a category.

The transcript uses two speaker labels:
- [BROCCOLI TEAM]: Internal team members (Elman, Klara, etc.)
- [INTERVIEWEE]: The external party

Use the full conversation — both sides — to determine the meeting type. The external party's identity and what they discuss is the primary signal, but team questions and the overall flow all count.

Known categories:
- customer-discovery: Customer interviews, sales discovery calls, demos with prospects, and conversations with anyone in the target market — including retailers, suppliers, distributors, or end-users — whose feedback informs the product or go-to-market strategy
- investor-calls: Meetings with investors, VCs, angels, fundraising conversations
- team-syncs: Internal team meetings, standups, retrospectives, planning sessions
- competitors: Competitive analysis calls, conversations about or with competitors
- advisors: Advisor meetings, mentor conversations, board advisor check-ins. Focus: business strategy, growth guidance, mentorship. When in doubt between advisors and tools-research: advisors discuss business decisions and strategy; tools-research discusses software functionality and evaluation.
- tools-research: Technical tool evaluation, workflow automation research, software product evaluations, technical demos of automation platforms. Examples: evaluating Windmill vs other automation tools, testing NotebookLM CLI features, comparing AI automation platforms. When in doubt: tools-research focuses on HOW software works; advisors focuses on BUSINESS implications.

Stanford GSB classes (use the specific slug, not a generic one):
- class-mge: Managing Growing Enterprises
- class-sales: Building Sales Organizations
- class-leadership: The Art of Leading in Challenging Times
- class-taxes: Taxes and Business Strategy
- class-fsa: Financial Statement Analysis

Return ONLY a JSON object with no other text:
{
  "category": "<category slug — use a known one or create a new descriptive slug>",
  "confidence": "high|medium|low",
  "reasoning": "<one sentence>"
}

If none of the known categories fit, invent a short descriptive slug (e.g. "conference-panel", "podcast-interview")."""


def _extract_json(text: str) -> dict:
    """Extract JSON from LLM response, handling markdown code blocks and trailing commentary."""
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
    user_message = (
        f"Title: {title}\n"
        f"Participants: {', '.join(participants)}\n"
        f"Summary: {summary}\n"
        f"Labeled transcript excerpt (first 500 chars):\n{transcript_excerpt[:500]}"
    )

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            CLAUDE_PROXY_URL,
            json={
                "model": "claude-sonnet-4-6",
                "max_tokens": 200,
                "system": SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": user_message}],
            },
            headers={"x-api-key": "not-needed", "Content-Type": "application/json"},
        )
        response.raise_for_status()

    data = response.json()
    raw = data["content"][0]["text"].strip()

    try:
        parsed = _extract_json(raw)
    except (json.JSONDecodeError, ValueError) as e:
        raise ValueError(f"Failed to parse classifier response: {e!r}\nRaw: {raw!r}") from e

    return ClassificationResult(
        category=parsed["category"],
        confidence=parsed["confidence"],
        reasoning=parsed["reasoning"],
    )
