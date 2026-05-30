-- Migration: Add subcategory column to discovery.insights and update category constraints
-- Run via: docker exec -i paperclip-db-1 psql -U paperclip -d discovery < this-file
-- Applied: 2026-05-25 (manually via gcloud IAP tunnel)

BEGIN;

-- Drop old category constraints (include 'technology', which is being eliminated)
ALTER TABLE discovery.insights
  DROP CONSTRAINT IF EXISTS insights_category_check;

ALTER TABLE discovery.clusters
  DROP CONSTRAINT IF EXISTS clusters_category_check;

-- Add replacement constraints excluding 'technology'.
-- NOT VALID: new rows must satisfy the constraint; existing rows are exempt until
-- VALIDATE CONSTRAINT is run after the backfill script (backfill_subcategory.py).
ALTER TABLE discovery.insights
  ADD CONSTRAINT insights_category_check CHECK (
    category = ANY (ARRAY[
      'ordering','delivery','pricing','inventory','communication',
      'quality','returns','payments','compliance','relationship'
    ])
  ) NOT VALID;

ALTER TABLE discovery.clusters
  ADD CONSTRAINT clusters_category_check CHECK (
    category = ANY (ARRAY[
      'ordering','delivery','pricing','inventory','communication',
      'quality','returns','payments','compliance','relationship'
    ])
  ) NOT VALID;

-- Add subcategory column (nullable — backfill assigns values to existing rows)
ALTER TABLE discovery.insights
  ADD COLUMN IF NOT EXISTS subcategory TEXT;

CREATE INDEX IF NOT EXISTS idx_insights_subcategory ON discovery.insights (subcategory);

COMMIT;

-- After running backfill_subcategory.py, validate the constraint:
--   ALTER TABLE discovery.insights VALIDATE CONSTRAINT insights_category_check;
