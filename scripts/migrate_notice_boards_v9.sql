-- Migration v9: Add text_length column for compressed text storage
--
-- When extracted text is stored in SQLite (via SqliteTextStorage),
-- extracted_text in PG is set to NULL. text_length preserves the
-- character count for statistics without requiring the full text.

-- Add text_length column
ALTER TABLE attachments ADD COLUMN IF NOT EXISTS text_length INTEGER;

-- Populate from existing extracted_text data
UPDATE attachments
SET text_length = LENGTH(extracted_text)
WHERE extracted_text IS NOT NULL AND text_length IS NULL;

-- Index for stats queries
CREATE INDEX IF NOT EXISTS idx_attachments_text_length
ON attachments (text_length) WHERE text_length IS NOT NULL;
