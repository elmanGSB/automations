"""
Discovery extraction module for the automations pipeline.
Calls Claude proxy at localhost:8199 with the extraction prompt,
parses JSON response, inserts into the discovery Postgres database.

No BAML dependency — prompt is embedded directly.
"""

import json
import logging
import os
import re
from datetime import date as date_type

import asyncpg
import httpx

from teable_client import TeableClient

logger = logging.getLogger(__name__)

CLAUDE_PROXY_URL = "http://127.0.0.1:8199/v1/messages"
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://paperclip:paperclip@127.0.0.1:5432/discovery",
)

EXTRACTION_SYSTEM_PROMPT = """You are a customer discovery analyst for a food distribution startup. You analyze
interviews with DISTRIBUTORS (food distribution companies), RETAILERS (grocery stores,
restaurants, convenience stores), SUPPLIERS (food manufacturers, farmers, processors),
INDUSTRY EXPERTS (consultants, analysts, trade leaders), and COMPETITORS (other
distribution or distribution-tech companies).

We're building for food distributors. Each interviewee type reveals different angles:
distributors show direct pain points, retailers/suppliers show what distributors
need to do better, experts provide macro patterns, competitors reveal market gaps.

You MUST respond with ONLY valid JSON matching the schema below. No markdown, no explanation, just JSON.

JSON Schema:
{
  "summary": "2-3 sentences: who is this person, what do they need, key takeaway",
  "participant_role": "their job title/role or null",
  "company_name": "their company or null",
  "interviewee_type": "distributor|retailer|supplier|industry_expert|competitor",
  "product_categories": ["perishable","frozen","liquor","nonperishable","meat","produce","dairy","specialty","full_line"],
  "behavioral_segment": "extreme_user|solution_user|solution_seeker|stuck_in_status_quo|complainer",
  "demographics": "Background info: years in business, location, company size, etc. or null",
  "insights": [
    {
      "type": "problem|need|observation|opportunity|quote",
      "content": "Clear, specific description in 1-2 sentences",
      "category": "ordering|delivery|pricing|inventory|communication|quality|returns|payments|technology|compliance|relationship",
      "severity": "critical|high|medium|low",
      "sentiment": "positive|negative|neutral|mixed",
      "verbatim_quote": "exact words from participant or null"
    }
  ],
  "empathy_map": {
    "thinks": ["internal thoughts"],
    "feels": ["emotions"],
    "says": ["direct quotes"],
    "does": ["observable actions"]
  },
  "clusters": [
    {
      "user_type": "who",
      "need": "what they need solved",
      "insight": "why it matters",
      "memorable_quote": "verbatim quote",
      "category": "ordering|delivery|pricing|inventory|communication|quality|returns|payments|technology|compliance|relationship"
    }
  ],
  "memorable_quotes": ["top 3-5 quotable lines"]
}"""

EXTRACTION_USER_PROMPT = """Analyze this interview and extract:

1. **Summary**: 2-3 sentences — who is this person, what do they need, key takeaway

2. **Interviewee classification**:
   - Type: distributor, retailer, supplier, industry_expert, or competitor
   - Product categories they deal with

3. **Behavioral segment** (pick ONE):
   - extreme_user: power user of current systems, pushes boundaries
   - solution_user: already built workarounds (spreadsheets, manual tracking)
   - solution_seeker: actively looking for better solutions, open to change
   - stuck_in_status_quo: knows problems exist, doesn't act
   - complainer: vocal about problems but resistant to change

4. **Demographics & background**: years in business, location, company size, revenue, etc.

5. **Insights**: Every distinct problem, need, observation, opportunity, or quote (aim for 5-15).
   - Be specific — "delivery windows vary by 8 hours" not "delivery is unreliable"
   - Rate severity: critical (blocking), high (major friction), medium (annoying), low (minor)

6. **Empathy map**:
   - THINKS: internal thoughts about business, role, industry
   - FEELS: emotions about distribution, relationships, challenges
   - SAYS: direct quotes and common phrases
   - DOES: observable actions, workarounds, daily habits

7. **Clusters**: 2-5 rows of User type / Need / Insight / Memorable quote

8. **Memorable quotes**: 3-5 lines you'd put in a pitch deck

{title_line}
{date_line}

TRANSCRIPT:
---
{transcript}
---

Respond with ONLY the JSON object. No markdown fences, no explanation."""


def _extract_json(text: str) -> dict:
    """Extract JSON from LLM response, handling markdown fences."""
    text = text.strip()
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    if match:
        text = match.group(1).strip()
    return json.loads(text)


async def extract_discovery_insights(
    transcript_text: str,
    meeting_title: str | None = None,
    meeting_date: str | None = None,
) -> dict:
    """Call Claude proxy to extract structured insights from a transcript."""
    title_line = f"Meeting: {meeting_title}" if meeting_title else ""
    date_line = f"Date: {meeting_date}" if meeting_date else ""

    user_prompt = EXTRACTION_USER_PROMPT.format(
        title_line=title_line,
        date_line=date_line,
        transcript=transcript_text,
    )

    async with httpx.AsyncClient(timeout=300.0) as client:
        response = await client.post(
            CLAUDE_PROXY_URL,
            json={
                "model": "claude-sonnet-4-6",
                "max_tokens": 8192,
                "system": EXTRACTION_SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": user_prompt}],
            },
            headers={"x-api-key": "not-needed", "Content-Type": "application/json"},
        )
        response.raise_for_status()

    data = response.json()
    raw_text = data["content"][0]["text"]
    return _extract_json(raw_text)


async def store_extraction(
    pool: asyncpg.Pool,
    extraction: dict,
    participant_name: str,
    interview_date: date_type,
    transcript_text: str,
    fireflies_meeting_id: str | None = None,
    meeting_title: str | None = None,
    channel: str = "call",
) -> dict:
    """Insert extracted data into the discovery Postgres database."""
    async with pool.acquire() as conn:
        async with conn.transaction():
            if fireflies_meeting_id:
                existing = await conn.fetchrow(
                    "SELECT id FROM discovery.interviews WHERE fireflies_meeting_id = $1",
                    fireflies_meeting_id,
                )
                if existing:
                    logger.info("Meeting %s already in discovery DB, skipping", fireflies_meeting_id)
                    return {"skipped": True, "interview_id": existing["id"]}

            interview_id = await conn.fetchval(
                """
                INSERT INTO discovery.interviews
                    (date, participant_name, participant_role, company_name,
                     interviewee_type, product_categories, behavioral_segment,
                     demographics, channel, fireflies_meeting_id,
                     transcript_raw, summary, extracted_data)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
                RETURNING id
                """,
                interview_date,
                participant_name,
                extraction.get("participant_role"),
                extraction.get("company_name"),
                extraction["interviewee_type"],
                extraction.get("product_categories", []),
                extraction.get("behavioral_segment"),
                extraction.get("demographics"),
                channel,
                fireflies_meeting_id,
                transcript_text,
                extraction.get("summary"),
                json.dumps(extraction),
            )
            logger.info("Discovery interview #%d created", interview_id)

            insights_count = 0
            for insight in extraction.get("insights", []):
                await conn.execute(
                    """
                    INSERT INTO discovery.insights
                        (interview_id, type, content, category, severity,
                         sentiment, verbatim_quote, tags)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
                    """,
                    interview_id,
                    insight["type"],
                    insight["content"],
                    insight.get("category"),
                    insight.get("severity"),
                    insight.get("sentiment"),
                    insight.get("verbatim_quote"),
                    "[]",
                )
                insights_count += 1
            logger.info("  %d insights inserted", insights_count)

            clusters_count = 0
            for cluster in extraction.get("clusters", []):
                await conn.execute(
                    """
                    INSERT INTO discovery.clusters
                        (user_type, need, insight, memorable_quote,
                         category, source_interview_ids)
                    VALUES ($1,$2,$3,$4,$5,$6)
                    """,
                    cluster["user_type"],
                    cluster["need"],
                    cluster["insight"],
                    cluster.get("memorable_quote"),
                    cluster.get("category"),
                    json.dumps([interview_id]),
                )
                clusters_count += 1
            logger.info("  %d clusters inserted", clusters_count)

    # Teable dual-write happens after the transaction commits (Task 2 adds async wrapping)
    try:
        teable = TeableClient()
        teable.write_interview(
            participant_name=participant_name,
            date=str(interview_date),
            participant_role=extraction.get("participant_role") or "",
            company_name=extraction.get("company_name") or "",
            interviewee_type=extraction["interviewee_type"],
            product_categories=extraction.get("product_categories"),
            behavioral_segment=extraction.get("behavioral_segment") or "",
            demographics=extraction.get("demographics") or "",
            summary=extraction.get("summary") or "",
            fireflies_meeting_id=fireflies_meeting_id or "",
        )
        teable.write_insights([
            {
                "interview": participant_name,
                "type": ins["type"],
                "category": ins.get("category") or "",
                "content": ins["content"],
                "severity": ins.get("severity") or "",
                "sentiment": ins.get("sentiment") or "",
                "quote": ins.get("verbatim_quote") or "",
            }
            for ins in extraction.get("insights", [])
        ])
        teable.write_clusters([
            {
                "user_type": cl["user_type"],
                "need": cl["need"],
                "insight": cl["insight"],
                "quote": cl.get("memorable_quote") or "",
                "category": cl.get("category") or "",
            }
            for cl in extraction.get("clusters", [])
        ])
        logger.info("  Teable dual-write: 1 interview, %d insights, %d clusters", insights_count, clusters_count)
    except Exception as e:
        logger.warning("Teable dual-write failed (non-fatal): %s", e)

    return {
        "interview_id": interview_id,
        "insights": insights_count,
        "clusters": clusters_count,
        "type": extraction["interviewee_type"],
        "segment": extraction.get("behavioral_segment"),
        "summary": extraction.get("summary"),
    }


async def process_discovery_meeting(
    pool: asyncpg.Pool,
    transcript_text: str,
    participant_name: str,
    meeting_title: str | None = None,
    meeting_date: str | None = None,
    fireflies_meeting_id: str | None = None,
) -> dict:
    """Full extraction pipeline: call Claude → parse → store in Postgres."""
    logger.info("Running discovery extraction for '%s'", meeting_title or participant_name)

    extraction = await extract_discovery_insights(
        transcript_text=transcript_text,
        meeting_title=meeting_title,
        meeting_date=meeting_date,
    )
    logger.info(
        "Extracted: %d insights, %d clusters, type=%s, segment=%s",
        len(extraction.get("insights", [])),
        len(extraction.get("clusters", [])),
        extraction.get("interviewee_type"),
        extraction.get("behavioral_segment"),
    )

    result = await store_extraction(
        pool=pool,
        extraction=extraction,
        participant_name=participant_name,
        interview_date=date_type.fromisoformat(meeting_date) if meeting_date else date_type.today(),
        transcript_text=transcript_text,
        fireflies_meeting_id=fireflies_meeting_id,
        meeting_title=meeting_title,
    )

    return result
