-- Notice Board Documents - Migration v2
-- Adds nutslau and coat_of_arms_url columns to notice_boards table
--
-- Run with: psql -U ruian -d ruian -f scripts/migrate_notice_boards_v2.sql

BEGIN;

-- Add new columns
ALTER TABLE notice_boards ADD COLUMN IF NOT EXISTS nutslau VARCHAR(20);
ALTER TABLE notice_boards ADD COLUMN IF NOT EXISTS coat_of_arms_url VARCHAR(1024);

-- Add comments for new columns
COMMENT ON COLUMN notice_boards.nutslau IS 'NUTS LAU territorial code (matches RÚIAN obce.nutslau)';
COMMENT ON COLUMN notice_boards.coat_of_arms_url IS 'URL to coat of arms image (typically Wikimedia Commons)';

-- Add unique constraint on ico for upsert operations
-- Using partial index to allow NULL values
CREATE UNIQUE INDEX IF NOT EXISTS idx_notice_boards_ico_unique
    ON notice_boards (ico) WHERE ico IS NOT NULL;

COMMIT;

DO $$
BEGIN
    RAISE NOTICE 'Migration v2 completed: added nutslau and coat_of_arms_url columns';
END $$;
