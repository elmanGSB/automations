-- Migration: Add subcategory column to discovery.insights and update category constraints
-- Run via: docker exec -i paperclip-db-1 psql -U paperclip -d discovery < this-file
-- Applied: 2026-05-25 (manually via gcloud IAP tunnel)
-- Note: discovery/schema.sql must also be updated to remove 'technology' from the
--       category CHECK and add the subcategory column (done in the discovery repo).
--
-- This migration is IDEMPOTENT:
-- - ADD COLUMN IF NOT EXISTS: safe to re-run
-- - Constraint updates: only replace the constraint if 'technology' is still present.
--   If the constraint was already updated (and validated), it is left untouched so
--   VALIDATE CONSTRAINT state is preserved across deploys.

BEGIN;

-- Add subcategory column (no-op if already present)
ALTER TABLE discovery.insights
  ADD COLUMN IF NOT EXISTS subcategory TEXT;

CREATE INDEX IF NOT EXISTS idx_insights_subcategory ON discovery.insights (subcategory);

-- Replace insights_category_check only if 'technology' is still in its definition.
-- Avoids re-creating a validated constraint as NOT VALID on every deploy.
DO $$
DECLARE
  old_check text;
BEGIN
  SELECT pg_get_constraintdef(oid) INTO old_check
  FROM pg_constraint
  WHERE conrelid = 'discovery.insights'::regclass
    AND conname = 'insights_category_check';

  IF old_check IS NULL OR old_check LIKE '%technology%' THEN
    IF old_check IS NOT NULL THEN
      ALTER TABLE discovery.insights DROP CONSTRAINT insights_category_check;
    END IF;
    ALTER TABLE discovery.insights
      ADD CONSTRAINT insights_category_check CHECK (
        category = ANY (ARRAY[
          'ordering','delivery','pricing','inventory','communication',
          'quality','returns','payments','compliance','relationship'
        ])
      ) NOT VALID;
  END IF;
END $$;

-- Same idempotent logic for clusters
DO $$
DECLARE
  old_check text;
BEGIN
  SELECT pg_get_constraintdef(oid) INTO old_check
  FROM pg_constraint
  WHERE conrelid = 'discovery.clusters'::regclass
    AND conname = 'clusters_category_check';

  IF old_check IS NULL OR old_check LIKE '%technology%' THEN
    IF old_check IS NOT NULL THEN
      ALTER TABLE discovery.clusters DROP CONSTRAINT clusters_category_check;
    END IF;
    ALTER TABLE discovery.clusters
      ADD CONSTRAINT clusters_category_check CHECK (
        category = ANY (ARRAY[
          'ordering','delivery','pricing','inventory','communication',
          'quality','returns','payments','compliance','relationship'
        ])
      ) NOT VALID;
  END IF;
END $$;

COMMIT;

-- After running backfill_subcategory.py, validate the constraint:
--   ALTER TABLE discovery.insights VALIDATE CONSTRAINT insights_category_check;
-- The idempotent guard above will leave this validated state intact on future deploys.
