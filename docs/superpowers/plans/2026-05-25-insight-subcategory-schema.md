# Insight Subcategory Schema Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `subcategory` to every discovery insight, eliminate `technology` as a catch-all category, and enable Metabase to cross-tab pain type × customer segment.

**Architecture:** Four sequential changes — DB migration adds the column and relaxes the category constraint, prompt update makes every new interview write a subcategory, backfill script reclassifies the existing 593 insights, BAML dev-tool stays in sync. Metabase chart is a configuration step with no code.

**Tech Stack:** PostgreSQL (asyncpg), Python 3.12, FastAPI/uv, Claude API via local proxy at `:8199`, BAML.

---

## File Map

| File | Change |
|---|---|
| `vm-api/discovery_extractor.py` | Update system prompt + user prompt + `store_extraction` to write `subcategory` |
| `vm-api/backfill_subcategory.py` | New — one-time script to reclassify existing 593 insights |
| `vm-api/tests/test_extractor.py` | Add tests for subcategory field presence and `technology` rejection |
| `discovery/baml_src/types.baml` | Remove `Technology` from `InsightCategory`, add `InsightSubcategory` enum |
| `discovery/baml_src/extract.baml` | Add subcategory instruction to insight extraction section |

Migration SQL is run directly via `docker exec` — no migration framework in this project.

---

## Subcategory Reference (used in Tasks 1, 2, 3, 4)

```
ordering:
  manual-entry-causes-errors      orders phoned in, re-keyed into ERP → wrong items shipped
  missed-upsell-crosssell         rep has no data on buying gaps → revenue left on table
  customer-wont-place-digitally   portal built, customers still call → <2% adoption
  no-order-status-after-placed    no tracking once order placed → customer calls for status

pricing:
  wrong-price-on-invoice                      price lists not synced → customer disputes, payment delayed
  customer-doesnt-know-price-before-ordering  no price visibility before invoice → sticker shock
  margin-shrinking-undetected                 no cost tracking against price → profitability erodes
  promo-roi-invisible                         no way to tag promo periods → promotions lose money invisibly
  rebates-and-allowances-uncollected          vendor data in ERP, never surfaced → money left on table
  losing-deals-on-price                       no market pricing visibility → accounts switching to competitor

inventory:
  unexpected-stockouts      demand forecasting in Excel → customer runs out at wrong time
  perishable-spoilage       no sell-through visibility → product thrown away
  cash-locked-in-overstock  no mechanism to flag slow SKUs → working capital trapped
  stock-data-always-stale   inventory updated overnight → rep promises unavailable product

relationship:
  account-lost-when-rep-leaves  relationship personal, no shared history → account walks with rep
  rep-only-reacts-never-alerts  no early warning on pattern changes → customer discovers problems first
  service-failures-erode-trust  repeated errors, no accountability → customer shops alternatives
  new-rep-takes-months-to-ramp  no knowledge transfer → new rep starts from zero

delivery:
  late-or-missed-delivery  route planning manual → customer runs out of product
  wrong-items-dropped      pick lists written hours before → customer receives incorrect order
  8-hour-delivery-window   no real-time tracking → customer can't plan kitchen or staffing

communication:
  order-changes-lost            WhatsApp changes never updated in system → original order arrives
  whatsapp-as-system-of-record  no structured channel → decisions unrecorded, knowledge lost
  no-escalation-path            no way to flag issues → problem festers until crisis

payments:
  invoice-dispute-delays-payment  price mismatch on invoice → payment held 30-60 extra days
  net-60-cash-flow-crunch         customer net-60, supplier net-30 → distributor can't pay suppliers
  overdue-ar-not-followed-up      no systematic AR process → bad debt writeoffs

quality:
  product-damaged-on-arrival    temperature break or rough handling → customer rejects shipment
  same-quality-problems-repeat  complaints verbal, never logged → no improvement, recurs

returns:
  credit-takes-weeks     requires manager approval, paper trail → customer withholds payment
  return-pickup-no-show  no scheduled return route → product sits at customer's dock

compliance:
  records-missing-at-audit           docs buried in emails → fails inspection
  regulatory-complexity-overwhelm    regulations change frequently, no tracking → operator can't keep up
```

---

## Task 1: DB Migration

**Files:**
- No file — migration runs via `docker exec` directly on the VM

### What this does

- Drops the `insights_category_check` and `clusters_category_check` constraints (they include `technology` and will block new writes once the prompt removes it)
- Adds a `NOT VALID` replacement constraint that excludes `technology` (existing `technology` rows survive until backfill)
- Adds `subcategory TEXT` column to `discovery.insights`
- Adds index on `subcategory` for Metabase query performance

`NOT VALID` means: new rows must satisfy the constraint, existing rows are exempt until you run `VALIDATE CONSTRAINT` (done after backfill in Task 3).

- [ ] **Step 1: Connect to VM and open psql**

```bash
gcloud compute ssh paperclip-vm --tunnel-through-iap --zone=us-central1-f --project=paperclip-tribuai --command "docker exec -i paperclip-db-1 psql -U paperclip -d discovery"
```

- [ ] **Step 2: Run the migration**

```sql
BEGIN;

-- insights: drop old constraint, add new one without technology, add subcategory column
ALTER TABLE discovery.insights
  DROP CONSTRAINT insights_category_check;

ALTER TABLE discovery.insights
  ADD CONSTRAINT insights_category_check CHECK (
    category = ANY (ARRAY[
      'ordering','delivery','pricing','inventory','communication',
      'quality','returns','payments','compliance','relationship'
    ])
  ) NOT VALID;

ALTER TABLE discovery.insights
  ADD COLUMN subcategory TEXT;

CREATE INDEX idx_insights_subcategory ON discovery.insights (subcategory);

-- clusters: same constraint drop/replace (no subcategory column needed there)
ALTER TABLE discovery.clusters
  DROP CONSTRAINT clusters_category_check;

ALTER TABLE discovery.clusters
  ADD CONSTRAINT clusters_category_check CHECK (
    category = ANY (ARRAY[
      'ordering','delivery','pricing','inventory','communication',
      'quality','returns','payments','compliance','relationship'
    ])
  ) NOT VALID;

COMMIT;
```

- [ ] **Step 3: Verify**

```sql
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_schema = 'discovery' AND table_name = 'insights'
ORDER BY ordinal_position;
```

Expected: `subcategory` appears as `text`, `YES` nullable.

```sql
SELECT conname FROM pg_constraint
WHERE conrelid = 'discovery.insights'::regclass;
```

Expected: `insights_category_check` still present (NOT VALID version).

```sql
-- Confirm existing technology rows still exist (constraint is NOT VALID)
SELECT COUNT(*) FROM discovery.insights WHERE category = 'technology';
```

Expected: 222 (unchanged — NOT VALID means existing rows are not rechecked).

---

## Task 2: Update Extraction Prompt

**Files:**
- Modify: `vm-api/discovery_extractor.py`
- Modify: `vm-api/tests/test_extractor.py`

### What changes in `discovery_extractor.py`

Three things:
1. `EXTRACTION_SYSTEM_PROMPT` — remove `technology` from the category list in the JSON schema, add `subcategory` field with the full reference table
2. `EXTRACTION_USER_PROMPT` — make `verbatim_quote` required (remove "or null"), add subcategory instruction
3. `store_extraction()` — pass `insight.get("subcategory")` in the INSERT

- [ ] **Step 1: Write failing tests**

Add to `vm-api/tests/test_extractor.py`:

```python
def test_prompt_excludes_technology_category():
    """EXTRACTION_SYSTEM_PROMPT must not list technology as a valid category."""
    from discovery_extractor import EXTRACTION_SYSTEM_PROMPT
    # technology must not appear as a valid enum value
    assert '"technology"' not in EXTRACTION_SYSTEM_PROMPT
    assert "'technology'" not in EXTRACTION_SYSTEM_PROMPT
    # operational categories must still be present
    for cat in ["ordering", "pricing", "inventory", "relationship", "delivery"]:
        assert cat in EXTRACTION_SYSTEM_PROMPT


def test_prompt_includes_subcategory_field():
    """EXTRACTION_SYSTEM_PROMPT must include subcategory in the insight JSON schema."""
    from discovery_extractor import EXTRACTION_SYSTEM_PROMPT
    assert '"subcategory"' in EXTRACTION_SYSTEM_PROMPT


def test_prompt_includes_subcategory_slugs():
    """EXTRACTION_SYSTEM_PROMPT must list subcategory slugs."""
    from discovery_extractor import EXTRACTION_SYSTEM_PROMPT
    for slug in [
        "manual-entry-causes-errors",
        "promo-roi-invisible",
        "unexpected-stockouts",
        "account-lost-when-rep-leaves",
        "whatsapp-as-system-of-record",
        "invoice-dispute-delays-payment",
    ]:
        assert slug in EXTRACTION_SYSTEM_PROMPT


@pytest.mark.asyncio
async def test_store_extraction_writes_subcategory():
    """store_extraction must include subcategory in the insights INSERT."""
    pool, conn = make_mock_pool()
    extraction = {
        "interviewee_type": "distributor",
        "insights": [{
            "type": "problem",
            "content": "Orders are wrong",
            "category": "ordering",
            "subcategory": "manual-entry-causes-errors",
            "severity": "critical",
            "sentiment": "negative",
            "verbatim_quote": "We retype everything twice",
        }],
        "clusters": [],
        "summary": "s",
        "participant_role": None,
        "company_name": None,
        "product_categories": [],
        "behavioral_segment": None,
        "demographics": None,
    }

    with patch("discovery_extractor.TeableClient"):
        await store_extraction_fn(
            pool=pool,
            extraction=extraction,
            participant_name="John",
            interview_date=date(2026, 5, 25),
            transcript_text="text",
        )

    # The INSERT for insights should have been called with subcategory value
    execute_calls = conn.execute.await_args_list
    insight_call = execute_calls[0]
    call_args = insight_call.args
    assert "manual-entry-causes-errors" in call_args
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /Users/elmanamador/coding/automations/vm-api
uv run pytest tests/test_extractor.py::test_prompt_excludes_technology_category tests/test_extractor.py::test_prompt_includes_subcategory_field tests/test_extractor.py::test_prompt_includes_subcategory_slugs tests/test_extractor.py::test_store_extraction_writes_subcategory -v
```

Expected: all 4 FAIL.

- [ ] **Step 3: Update `EXTRACTION_SYSTEM_PROMPT`**

Replace the `"category"` line in the insights schema section and add `"subcategory"`:

```python
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
      "category": "ordering|delivery|pricing|inventory|communication|quality|returns|payments|compliance|relationship",
      "subcategory": "<slug from the reference below — match to the insight's category>",
      "severity": "critical|high|medium|low",
      "sentiment": "positive|negative|neutral|mixed",
      "verbatim_quote": "exact words from participant — REQUIRED, do not leave null"
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
      "category": "ordering|delivery|pricing|inventory|communication|quality|returns|payments|compliance|relationship"
    }
  ],
  "memorable_quotes": ["top 3-5 quotable lines"]
}

SUBCATEGORY REFERENCE — use the slug exactly as listed, pick the closest match to the insight:

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

If an insight does not fit any subcategory, use the closest match. Do not leave subcategory null."""
```

- [ ] **Step 4: Update `EXTRACTION_USER_PROMPT` insight instruction**

Change the insights section (around line 95) to note subcategory and require verbatim quote:

```python
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
   - Assign category from: ordering, delivery, pricing, inventory, communication, quality, returns, payments, compliance, relationship
   - Assign subcategory slug from the reference in the system prompt
   - Rate severity: critical (blocking), high (major friction), medium (annoying), low (minor)
   - verbatim_quote is REQUIRED — find the closest direct quote from the transcript

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
```

- [ ] **Step 5: Update `store_extraction` to write `subcategory`**

In `store_extraction`, find the insights INSERT (around line 213) and add `subcategory`:

```python
for insight in extraction.get("insights", []):
    await conn.execute(
        """
        INSERT INTO discovery.insights
            (interview_id, type, content, category, subcategory, severity,
             sentiment, verbatim_quote, tags)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
        """,
        interview_id,
        insight["type"],
        insight["content"],
        insight.get("category"),
        insight.get("subcategory"),
        insight.get("severity"),
        insight.get("sentiment"),
        insight.get("verbatim_quote"),
        "[]",
    )
    insights_count += 1
```

- [ ] **Step 6: Run all four new tests**

```bash
cd /Users/elmanamador/coding/automations/vm-api
uv run pytest tests/test_extractor.py::test_prompt_excludes_technology_category tests/test_extractor.py::test_prompt_includes_subcategory_field tests/test_extractor.py::test_prompt_includes_subcategory_slugs tests/test_extractor.py::test_store_extraction_writes_subcategory -v
```

Expected: all 4 PASS.

- [ ] **Step 7: Run full test suite to check for regressions**

```bash
cd /Users/elmanamador/coding/automations/vm-api
uv run pytest tests/ -v --ignore=tests/test_classifier.py
```

Expected: all existing tests PASS. (`test_classifier.py` is excluded because it makes live Claude calls.)

- [ ] **Step 8: Commit**

```bash
cd /Users/elmanamador/coding/automations
git add vm-api/discovery_extractor.py vm-api/tests/test_extractor.py
git commit -m "feat: add subcategory to insight extraction — remove technology category"
```

---

## Task 3: Backfill Script

**Files:**
- Create: `vm-api/backfill_subcategory.py`

This script runs once against the production DB to assign `category` and `subcategory` to the 593 existing insights. Technology insights get reassigned to their operational category or skipped (left as `category='technology'`, `subcategory=NULL`) for manual review.

- [ ] **Step 1: Create `vm-api/backfill_subcategory.py`**

```python
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
import sys

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
```

- [ ] **Step 2: Smoke test with dry-run on 5 rows (requires SSH tunnel)**

Open the SSH tunnel in a separate terminal first:
```bash
gcloud compute ssh paperclip-vm --tunnel-through-iap --zone=us-central1-f \
  --project=paperclip-tribuai -- -N -L 5433:127.0.0.1:5432
```

Then run:
```bash
cd /Users/elmanamador/coding/automations/vm-api
DATABASE_URL=postgresql://paperclip:paperclip@localhost:5433/discovery \
  uv run python backfill_subcategory.py --dry-run --limit 5
```

Expected output: 5 lines showing `[UPDATE]` or `[SKIP]` with reasoning. No DB writes.

- [ ] **Step 3: Run full dry-run on all 593 insights**

```bash
cd /Users/elmanamador/coding/automations/vm-api
DATABASE_URL=postgresql://paperclip:paperclip@localhost:5433/discovery \
  uv run python backfill_subcategory.py --dry-run 2>&1 | tee /tmp/backfill-dry-run.txt
```

Review `/tmp/backfill-dry-run.txt`. Check:
- Technology insights are being redistributed correctly
- Root-cause observations (ERP is legacy, AI adoption stats) are being SKIPped
- No unexpected errors

- [ ] **Step 4: Run the real backfill**

```bash
cd /Users/elmanamador/coding/automations/vm-api
DATABASE_URL=postgresql://paperclip:paperclip@localhost:5433/discovery \
  uv run python backfill_subcategory.py 2>&1 | tee /tmp/backfill-live.txt
```

Expected: `updated=N skipped=M errors=0` in the final line.

- [ ] **Step 5: Verify in DB**

```bash
gcloud compute ssh paperclip-vm --tunnel-through-iap --zone=us-central1-f --project=paperclip-tribuai --command "docker exec paperclip-db-1 psql -U paperclip -d discovery -c \"SELECT category, subcategory, COUNT(*) FROM discovery.insights GROUP BY category, subcategory ORDER BY category, COUNT(*) DESC;\""
```

Expected: `technology` rows are now in operational categories. A small number may remain as `technology` with `subcategory=NULL` (root-cause observations flagged for manual review).

- [ ] **Step 6: Validate the DB constraint on non-technology rows**

```bash
gcloud compute ssh paperclip-vm --tunnel-through-iap --zone=us-central1-f --project=paperclip-tribuai --command "docker exec paperclip-db-1 psql -U paperclip -d discovery -c \"ALTER TABLE discovery.insights VALIDATE CONSTRAINT insights_category_check;\""
```

Expected: succeeds if no `technology` rows remain. If it fails, some technology rows weren't backfilled — check `/tmp/backfill-live.txt` for errors and re-run.

- [ ] **Step 7: Commit**

```bash
cd /Users/elmanamador/coding/automations
git add vm-api/backfill_subcategory.py
git commit -m "feat: add backfill script for insight subcategory reclassification"
```

---

## Task 4: Update BAML Dev Tool

**Files:**
- Modify: `discovery/baml_src/types.baml`
- Modify: `discovery/baml_src/extract.baml`

This keeps the standalone `discovery/pipeline.py` in sync with production. Not on the critical path — do after Task 3 is live.

- [ ] **Step 1: Update `discovery/baml_src/types.baml`**

Replace the `InsightCategory` enum and add `InsightSubcategory`. Also add `subcategory` to `InterviewInsight`:

```baml
// discovery/baml_src/types.baml

enum InsightCategory {
  Ordering       @alias("ordering")
  Delivery       @alias("delivery")
  Pricing        @alias("pricing")
  Inventory      @alias("inventory")
  Communication  @alias("communication")
  Quality        @alias("quality")
  Returns        @alias("returns")
  Payments       @alias("payments")
  Compliance     @alias("compliance")
  Relationship   @alias("relationship")
}

enum InsightSubcategory {
  // ordering
  ManualEntryCausesErrors      @alias("manual-entry-causes-errors")
  MissedUpsellCrosssell        @alias("missed-upsell-crosssell")
  CustomerWontPlaceDigitally   @alias("customer-wont-place-digitally")
  NoOrderStatusAfterPlaced     @alias("no-order-status-after-placed")
  // pricing
  WrongPriceOnInvoice                     @alias("wrong-price-on-invoice")
  CustomerDoesntKnowPriceBeforeOrdering   @alias("customer-doesnt-know-price-before-ordering")
  MarginShrinkingUndetected               @alias("margin-shrinking-undetected")
  PromoRoiInvisible                       @alias("promo-roi-invisible")
  RebatesAndAllowancesUncollected         @alias("rebates-and-allowances-uncollected")
  LosingDealsOnPrice                      @alias("losing-deals-on-price")
  // inventory
  UnexpectedStockouts     @alias("unexpected-stockouts")
  PerishableSpoilage      @alias("perishable-spoilage")
  CashLockedInOverstock   @alias("cash-locked-in-overstock")
  StockDataAlwaysStale    @alias("stock-data-always-stale")
  // relationship
  AccountLostWhenRepLeaves   @alias("account-lost-when-rep-leaves")
  RepOnlyReactsNeverAlerts   @alias("rep-only-reacts-never-alerts")
  ServiceFailuresErodeTrust  @alias("service-failures-erode-trust")
  NewRepTakesMonthsToRamp    @alias("new-rep-takes-months-to-ramp")
  // delivery
  LateOrMissedDelivery   @alias("late-or-missed-delivery")
  WrongItemsDropped      @alias("wrong-items-dropped")
  EightHourDeliveryWindow @alias("8-hour-delivery-window")
  // communication
  OrderChangesLost           @alias("order-changes-lost")
  WhatsappAsSystemOfRecord   @alias("whatsapp-as-system-of-record")
  NoEscalationPath           @alias("no-escalation-path")
  // payments
  InvoiceDisputeDelaysPayment  @alias("invoice-dispute-delays-payment")
  Net60CashFlowCrunch          @alias("net-60-cash-flow-crunch")
  OverdueArNotFollowedUp       @alias("overdue-ar-not-followed-up")
  // quality
  ProductDamagedOnArrival    @alias("product-damaged-on-arrival")
  SameQualityProblemsRepeat  @alias("same-quality-problems-repeat")
  // returns
  CreditTakesWeeks     @alias("credit-takes-weeks")
  ReturnPickupNoShow   @alias("return-pickup-no-show")
  // compliance
  RecordsMissingAtAudit          @alias("records-missing-at-audit")
  RegulatoryComplexityOverwhelm  @alias("regulatory-complexity-overwhelm")
}

// Stanford GSB behavioral segmentation
enum BehavioralSegment {
  ExtremeUser       @alias("extreme_user") @description("Power user of current systems, pushes boundaries, deep opinions")
  SolutionUser      @alias("solution_user") @description("Already built workarounds — spreadsheets, manual tracking, custom tools")
  SolutionSeeker    @alias("solution_seeker") @description("Actively looking for better solutions, open to change, has budget")
  StuckInStatusQuo  @alias("stuck_in_status_quo") @description("Knows problems exist, doesn't act — 'it's always been this way'")
  Complainer        @alias("complainer") @description("Vocal about problems but resistant to change, blames others")
}

class InterviewInsight {
  type "problem" | "need" | "observation" | "opportunity" | "quote"
  content string @description("Clear, concise description in 1-2 sentences. Be specific.")
  category InsightCategory @description("Food distribution domain category")
  subcategory InsightSubcategory @description("Specific pain point slug — see subcategory reference in prompt")
  severity "critical" | "high" | "medium" | "low"
  sentiment "positive" | "negative" | "neutral" | "mixed"
  verbatim_quote string @description("Exact words from the participant — required")
}

// Stanford GSB Empathy Map
class EmpathyMap {
  thinks string[] @description("Internal thoughts: role concerns, industry worries, strategic questions")
  feels string[] @description("Emotions: frustration, anxiety, hope, loyalty, resentment")
  says string[] @description("Direct quotes and common phrases they use")
  does string[] @description("Observable actions: workarounds, habits, tools they use, daily routines")
}

// Stanford GSB Cluster Table row
class ClusterEntry {
  user_type string @description("Who: 'Small retailer (independent shop owner)'")
  need string @description("What they need solved: 'Predictable delivery windows'")
  insight string @description("The aha — why this matters, what behavior it drives")
  memorable_quote string @description("Verbatim quote that captures this cluster")
  category InsightCategory
}

class InterviewExtraction {
  summary string @description("2-3 sentences: who is this person, what do they need, key takeaway")
  participant_role string?
  company_name string?
  interviewee_type "distributor" | "retailer" | "supplier" | "industry_expert" | "competitor"
  product_categories string[] @description("What products they deal with: perishable, frozen, liquor, nonperishable, meat, produce, dairy, specialty, full_line")
  behavioral_segment BehavioralSegment
  demographics string? @description("Background info mentioned in interview: years in business, location, company size, revenue, # employees, # trucks, etc.")
  insights InterviewInsight[] @description("All distinct insights. Aim for 5-15 per interview.")
  empathy_map EmpathyMap
  clusters ClusterEntry[] @description("2-5 User/Need/Insight/Quote clusters")
  memorable_quotes string[] @description("Top 3-5 most impactful, quotable lines")
}
```

- [ ] **Step 2: Update subcategory reference in `discovery/baml_src/extract.baml`**

In the insights section (after line 38), add the subcategory reference. Replace the category instruction line:

```baml
   - Categorize each: ordering, delivery, pricing, inventory, communication, quality, returns, payments, compliance, relationship
   - Assign subcategory slug: ordering→(manual-entry-causes-errors|missed-upsell-crosssell|customer-wont-place-digitally|no-order-status-after-placed) pricing→(wrong-price-on-invoice|customer-doesnt-know-price-before-ordering|margin-shrinking-undetected|promo-roi-invisible|rebates-and-allowances-uncollected|losing-deals-on-price) inventory→(unexpected-stockouts|perishable-spoilage|cash-locked-in-overstock|stock-data-always-stale) relationship→(account-lost-when-rep-leaves|rep-only-reacts-never-alerts|service-failures-erode-trust|new-rep-takes-months-to-ramp) delivery→(late-or-missed-delivery|wrong-items-dropped|8-hour-delivery-window) communication→(order-changes-lost|whatsapp-as-system-of-record|no-escalation-path) payments→(invoice-dispute-delays-payment|net-60-cash-flow-crunch|overdue-ar-not-followed-up) quality→(product-damaged-on-arrival|same-quality-problems-repeat) returns→(credit-takes-weeks|return-pickup-no-show) compliance→(records-missing-at-audit|regulatory-complexity-overwhelm)
```

- [ ] **Step 3: Regenerate BAML client**

```bash
cd /Users/elmanamador/coding/automations/discovery
uv run baml-cli generate
```

Expected: `baml_client/` regenerated with no errors.

- [ ] **Step 4: Commit**

```bash
cd /Users/elmanamador/coding/automations
git add discovery/baml_src/types.baml discovery/baml_src/extract.baml
git commit -m "feat: sync BAML schema with subcategory — remove Technology enum"
```

---

## Task 5: Metabase Segmentation Chart

**No code.** Pure Metabase configuration.

- [ ] **Step 1: Open Metabase**

Navigate to the discovery dashboard in Metabase (running at `metabase.jumpersapp.com` or via Cloudflare Tunnel).

- [ ] **Step 2: Create a new question**

- Table: `discovery.insights`
- Join: `discovery.interviews` on `insights.interview_id = interviews.id`
- Group by: `insights.subcategory`, `interviews.interviewee_type`
- Metric: Count of rows
- Filter: `insights.subcategory IS NOT NULL`

- [ ] **Step 3: Add visualization**

Set visualization to **Bar chart**. X-axis: `subcategory`. Series: `interviewee_type`. This produces a grouped bar per subcategory, colored by customer type.

- [ ] **Step 4: Add a severity filter**

Add a dashboard filter: `insights.severity` = (All / critical / high / medium / low). This lets you drill to "critical ordering problems by customer segment."

- [ ] **Step 5: Save to discovery dashboard**

Save as "Pain by subcategory × customer type" and add to the main discovery dashboard.

---

## Execution Order

```
Task 1 (migration) → Task 2 (prompt) → Task 3 (backfill) → Task 4 (BAML) → Task 5 (Metabase)
```

Tasks 1 and 2 are independent of each other but both must complete before Task 3 runs. Task 4 can run any time after Task 2. Task 5 is unblocked after Task 3 completes.
