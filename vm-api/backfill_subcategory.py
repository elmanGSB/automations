"""
One-time backfill: assign subcategory to existing insights, reassign technology insights.

Run from the vm-api directory with an active SSH tunnel to the DB:
  gcloud compute ssh paperclip-vm --tunnel-through-iap --zone=us-central1-f \
    --project=paperclip-tribuai -- -N -L 5433:127.0.0.1:5432

Then:
  DATABASE_URL=postgresql://paperclip:paperclip@localhost:5433/discovery \
  uv run python backfill_subcategory.py [--dry-run] [--limit 10]
"""
import argparse
import asyncio
import json
import logging
import os
import re

import asyncpg
import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://paperclip:paperclip@localhost:5433/discovery",
)
CLAUDE_PROXY_URL = "http://127.0.0.1:8199/v1/messages"

VALID_CATEGORIES = [
    "ordering", "delivery", "pricing", "inventory", "communication",
    "quality", "returns", "payments", "compliance", "relationship",
]

BACKFILL_SYSTEM_PROMPT = """You are reclassifying food distribution customer discovery insights.

Given an insight's content and current category, return the correct operational category and subcategory.

Rules:
- If category is 'technology', reassign to the operational domain the insight actually describes.
  Example: "orders re-keyed manually causes errors" → ordering / manual-entry-causes-errors
  If the insight describes a root cause or market observation with no specific operator pain
  (e.g. "ERP systems predate the computer mouse", "AI adoption failure rate is 91%"), return
  category=null and subcategory=null — these will be flagged for manual review.
- For all other categories, keep the category and assign the closest subcategory.

Valid categories: ordering, delivery, pricing, inventory, communication, quality, returns, payments, compliance, relationship

SUBCATEGORY REFERENCE:
ordering: manual-entry-causes-errors | missed-upsell-crosssell | customer-wont-place-digitally | no-order-status-after-placed
pricing: wrong-price-on-invoice | customer-doesnt-know-price-before-ordering | margin-shrinking-undetected | promo-roi-invisible | rebates-and-allowances-uncollected | losing-deals-on-price
inventory: unexpected-stockouts | perishable-spoilage | cash-locked-in-overstock | stock-data-always-stale
relationship: account-lost-when-rep-leaves | rep-only-reacts-never-alerts | service-failures-erode-trust | new-rep-takes-months-to-ramp
delivery: late-or-missed-delivery | wrong-items-dropped | 8-hour-delivery-window
communication: order-changes-lost | whatsapp-as-system-of-record | no-escalation-path
payments: invoice-dispute-delays-payment | net-60-cash-flow-crunch | overdue-ar-not-followed-up
quality: product-damaged-on-arrival | same-quality-problems-repeat
returns: credit-takes-weeks | return-pickup-no-show
compliance: records-missing-at-audit | regulatory-complexity-overwhelm

Return ONLY a JSON object, no other text:
{
  "category": "<operational category or null if root-cause observation>",
  "subcategory": "<slug or null>",
  "reasoning": "<one sentence>"
}"""


async def classify_insight(content: str, current_category: str) -> dict:
    """Call Claude to assign category + subcategory to one insight."""
    user_msg = f"Current category: {current_category}\nInsight: {content}"
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            CLAUDE_PROXY_URL,
            json={
                "model": "claude-sonnet-4-6",
                "max_tokens": 200,
                "system": BACKFILL_SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": user_msg}],
            },
            headers={"x-api-key": "not-needed", "Content-Type": "application/json"},
        )
        response.raise_for_status()
    raw = response.json()["content"][0]["text"].strip()
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", raw, re.DOTALL)
    if match:
        raw = match.group(1).strip()
    return json.loads(raw)


async def run_backfill(dry_run: bool = False, limit: int | None = None):
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        query = """
            SELECT id, content, category
            FROM discovery.insights
            WHERE subcategory IS NULL
            ORDER BY id
        """
        if limit:
            query += f" LIMIT {limit}"
        rows = await conn.fetch(query)
        logger.info("Found %d insights to backfill", len(rows))

        updated = skipped = errors = 0
        for row in rows:
            insight_id = row["id"]
            content = row["content"]
            current_cat = row["category"]
            try:
                result = await classify_insight(content, current_cat or "unknown")
                new_cat = result.get("category")
                new_sub = result.get("subcategory")
                reasoning = result.get("reasoning", "")

                if new_cat is None:
                    logger.info(
                        "  [SKIP] id=%d category=%s — root cause observation: %s",
                        insight_id, current_cat, reasoning,
                    )
                    skipped += 1
                    continue

                logger.info(
                    "  [UPDATE] id=%d %s → %s / %s",
                    insight_id, current_cat, new_cat, new_sub,
                )
                if not dry_run:
                    await conn.execute(
                        "UPDATE discovery.insights SET category=$1, subcategory=$2 WHERE id=$3",
                        new_cat, new_sub, insight_id,
                    )
                updated += 1
            except Exception as e:
                logger.error("  [ERROR] id=%d: %s", insight_id, e)
                errors += 1

        logger.info(
            "Done. updated=%d skipped=%d errors=%d dry_run=%s",
            updated, skipped, errors, dry_run,
        )
    finally:
        await conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill subcategory on existing insights")
    parser.add_argument("--dry-run", action="store_true", help="Print changes without writing to DB")
    parser.add_argument("--limit", type=int, default=None, help="Process only N insights (for testing)")
    args = parser.parse_args()
    asyncio.run(run_backfill(dry_run=args.dry_run, limit=args.limit))
