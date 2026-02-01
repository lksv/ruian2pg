-- Migration v7: Add download_status column to attachments table
--
-- Introduces explicit lifecycle states for attachment downloads:
--   pending    - awaiting download (default)
--   downloaded - content successfully downloaded
--   failed     - download failed (can be retried)
--   removed    - marked as not to be downloaded (terminal state)
--
-- Run: psql -U ruian -d ruian -f scripts/migrate_notice_boards_v7.sql

-- Add download_status column with default 'pending'
ALTER TABLE attachments ADD COLUMN IF NOT EXISTS download_status VARCHAR(20) DEFAULT 'pending';

-- Create index for efficient filtering by status
CREATE INDEX IF NOT EXISTS idx_attachments_download_status ON attachments(download_status);

-- Migrate existing data based on current state

-- Mark already downloaded attachments
UPDATE attachments
SET download_status = 'downloaded'
WHERE storage_path IS NOT NULL
  AND storage_path != ''
  AND file_size_bytes IS NOT NULL
  AND download_status = 'pending';

-- Mark attachments without URL as 'removed' (cannot be downloaded)
UPDATE attachments
SET download_status = 'removed'
WHERE (orig_url IS NULL OR orig_url = '')
  AND download_status = 'pending';

-- Add constraint to ensure valid status values
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'attachments_download_status_check'
    ) THEN
        ALTER TABLE attachments
        ADD CONSTRAINT attachments_download_status_check
        CHECK (download_status IN ('pending', 'downloaded', 'failed', 'removed'));
    END IF;
END $$;

-- Show migration results
SELECT
    download_status,
    COUNT(*) AS count
FROM attachments
GROUP BY download_status
ORDER BY download_status;
