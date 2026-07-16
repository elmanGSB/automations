import json
import re
from dataclasses import dataclass
import httpx
from config import KNOWN_CATEGORIES, LITELLM_BASE_URL, LITELLM_API_KEY, CLASSIFY_MODEL

# Classification runs through the LiteLLM gateway (default model: Gemini 3.1 Pro)
# instead of the Max-subscription Claude proxy. Gemini auth is a static API key
# held by LiteLLM, so classify_meeting no longer depends on the Mac's OAuth token
# being freshly synced to the VM — the failure mode that took the pipeline down
# for days (expired Keychain token → no fresh creds → classify_meeting 401s).
# Claude stays the engine for discovery extraction and the Attio triage resolver,
# which still hit the proxy directly.


class ClassifyAuthError(Exception):
    """Legacy: was raised when the Claude proxy returned 401 (expired OAuth).

    classify_meeting now runs on Gemini via LiteLLM (static API key), so this is
    no longer raised on the classify path. Kept for import compatibility with
    pipeline_runner's auto-heal handler, which is now a dead branch for classify.
    A LiteLLM auth failure (misconfigured master key) surfaces as a normal
    HTTPStatusError → classify_failed → Telegram alert, which is correct: a bad
    gateway key is an operator problem, not something a Secret Manager pull fixes.
    """

SYSTEM_PROMPT = """You are classifying a meeting transcript into a category.

The transcript uses two speaker labels:
- [BROCCOLI TEAM]: Internal team members (Elman, Klara, etc.)
- [INTERVIEWEE]: The external party

Use the full conversation — both sides — to determine the meeting type. The external party's identity and what they discuss is the primary signal, but team questions and the overall flow all count.

Known categories:
- customer-discovery: Customer interviews, sales discovery calls, demos with prospects, and conversations with anyone in the target market — including retailers, suppliers, distributors, or end-users — whose feedback informs the product or go-to-market strategy
- investor-calls: Meetings with investors, VCs, angels, fundraising conversations. Weigh BOTH the person's role and the topic together — a known investor (VC, angel, fund principal) discussing company progress, strategy, or advice is investor-calls even without explicit fundraising talk. But if a known investor is clearly on the call for an unrelated reason (e.g. giving hands-on product feedback as a user, not speaking as an investor), let the topic decide instead — role is a strong signal, not an automatic override.
- team-syncs: Internal team meetings, standups, retrospectives, planning sessions. Only use this when every speaker is [BROCCOLI TEAM] — any [INTERVIEWEE] speaker present means it is NOT team-syncs, even if the conversation feels internal (e.g. reviewing our own roadmap with an outside guest).
- competitors: Competitive analysis calls, conversations about or with competitors
- advisors: Advisor meetings, mentor conversations, board advisor check-ins with someone who is not acting as an investor in this conversation. Focus: business strategy, growth guidance, mentorship. When in doubt between advisors and investor-calls: weigh both the person's role and what they're actually discussing — don't rely on role alone, and don't rely on topic alone. When in doubt between advisors and tools-research: advisors discuss business decisions and strategy; tools-research discusses software functionality and evaluation.
- tools-research: Technical tool evaluation, workflow automation research, software product evaluations, technical demos of automation platforms. Examples: evaluating Windmill vs other automation tools, testing NotebookLM CLI features, comparing AI automation platforms. When in doubt: tools-research focuses on HOW software works; advisors focuses on BUSINESS implications.

Stanford GSB classes (use the specific slug, not a generic one):
- class-mge: Managing Growing Enterprises
- class-sales: Building Sales Organizations
- class-leadership: The Art of Leading in Challenging Times
- class-taxes: Taxes and Business Strategy
- class-fsa: Financial Statement Analysis
- class-fin-trading: Financial Trading Strategies
- class-conv-mgmt: Conversations in Management (interpersonal communication, difficult conversations, feedback)
- class-policy: Policy Proposals & Political Strategy (immigration, accountability, public policy seminars)
- class-humor: Comedy Fundamentals (humor, comedy writing, performance)

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


def _make_client() -> httpx.AsyncClient:
    """Build the HTTP client for the LiteLLM call. Factored out so tests can
    inject an httpx.MockTransport without a live gateway."""
    return httpx.AsyncClient(timeout=60.0)


async def _chat_completion(system: str, user: str) -> str:
    """POST an OpenAI-shaped chat completion to LiteLLM and return the reply text.

    LiteLLM routes CLASSIFY_MODEL (default gemini-3-1-pro) to Gemini and, per its
    default_fallbacks config, drops to gemini-3-1-flash-lite if the primary errors.
    """
    url = f"{LITELLM_BASE_URL.rstrip('/')}/chat/completions"
    async with _make_client() as client:
        response = await client.post(
            url,
            json={
                "model": CLASSIFY_MODEL,
                # Gemini 3.1 Pro is a thinking model: it spends most of the token
                # budget on internal reasoning before emitting the answer. At 200
                # it burned ~190 reasoning tokens and truncated the JSON mid-string
                # (finish_reason=length) — classify_failed on every meeting. A real
                # classification finishes around ~330 total tokens; 2048 gives safe
                # headroom for longer transcripts. The JSON itself stays tiny, so
                # the extra ceiling only ever costs reasoning we actually use.
                "max_tokens": 2048,
                "temperature": 0,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
            headers={
                "Authorization": f"Bearer {LITELLM_API_KEY}",
                "Content-Type": "application/json",
            },
        )
        response.raise_for_status()

    data = response.json()
    return data["choices"][0]["message"]["content"].strip()


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

    raw = await _chat_completion(SYSTEM_PROMPT, user_message)

    try:
        parsed = _extract_json(raw)
    except (json.JSONDecodeError, ValueError) as e:
        raise ValueError(f"Failed to parse classifier response: {e!r}\nRaw: {raw!r}") from e

    return ClassificationResult(
        category=parsed["category"],
        confidence=parsed["confidence"],
        reasoning=parsed["reasoning"],
    )
