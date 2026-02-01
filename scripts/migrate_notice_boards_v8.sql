-- Migration v8: Extend parse_status for text extraction lifecycle
--
-- Introduces additional states for attachment text extraction:
--   pending    - awaiting extraction (default, existing)
--   parsing    - extraction in progress
--   completed  - text successfully extracted (existing)
--   failed     - extraction failed (can be retried, existing)
--   skipped    - intentionally skipped (unsupported type, etc.)
--
-- Run: psql -U ruian -d ruian -f scripts/migrate_notice_boards_v8.sql

-- Drop existing constraint if any (to replace it)
ALTER TABLE attachments
DROP CONSTRAINT IF EXISTS attachments_parse_status_check;

-- Add constraint with all valid parse_status values
ALTER TABLE attachments
ADD CONSTRAINT attachments_parse_status_check
CHECK (parse_status IN ('pending', 'parsing', 'completed', 'failed', 'skipped'));

-- Create index for efficient filtering by parse_status and mime_type
-- Used when querying pending extractions
CREATE INDEX IF NOT EXISTS idx_attachments_parse_extraction
ON attachments(parse_status, mime_type)
WHERE parse_status IN ('pending', 'failed');

-- Create index for downloaded attachments ready for extraction
-- (download_status='downloaded' AND parse_status='pending')
CREATE INDEX IF NOT EXISTS idx_attachments_ready_extraction
ON attachments(download_status, parse_status)
WHERE download_status = 'downloaded' AND parse_status = 'pending';

-- Show current parse_status distribution
SELECT
    parse_status,
    COUNT(*) AS count
FROM attachments
GROUP BY parse_status
ORDER BY parse_status;
