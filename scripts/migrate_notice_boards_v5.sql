-- Notice Board Documents - Migration v5
-- Adds eDesky integration fields for notice boards, documents, and attachments
--
-- Run with: psql -U ruian -d ruian -f scripts/migrate_notice_boards_v5.sql

BEGIN;

-- =============================================================================
-- 1. Notice boards - eDesky integration fields
-- =============================================================================

-- eDesky ID and category
ALTER TABLE notice_boards ADD COLUMN IF NOT EXISTS edesky_id INTEGER;
ALTER TABLE notice_boards ADD COLUMN IF NOT EXISTS edesky_category VARCHAR(50);

-- NUTS3 (region) info from eDesky
ALTER TABLE notice_boards ADD COLUMN IF NOT EXISTS nuts3_id INTEGER;
ALTER TABLE notice_boards ADD COLUMN IF NOT EXISTS nuts3_name VARCHAR(255);

-- NUTS4 (district) info from eDesky
ALTER TABLE notice_boards ADD COLUMN IF NOT EXISTS nuts4_id INTEGER;
ALTER TABLE notice_boards ADD COLUMN IF NOT EXISTS nuts4_name VARCHAR(255);

-- Parent board info from eDesky hierarchy
ALTER TABLE notice_boards ADD COLUMN IF NOT EXISTS edesky_parent_id INTEGER;
ALTER TABLE notice_boards ADD COLUMN IF NOT EXISTS edesky_parent_name VARCHAR(255);

-- Unique index on edesky_id for fast lookups
CREATE UNIQUE INDEX IF NOT EXISTS idx_notice_boards_edesky_id
ON notice_boards(edesky_id) WHERE edesky_id IS NOT NULL;

COMMENT ON COLUMN notice_boards.edesky_id IS 'ID from eDesky.cz system';
COMMENT ON COLUMN notice_boards.edesky_category IS 'Category from eDesky (obec, mesto, kraj, ministerstvo, etc.)';
COMMENT ON COLUMN notice_boards.nuts3_id IS 'Region ID from eDesky (NUTS3)';
COMMENT ON COLUMN notice_boards.nuts3_name IS 'Region name from eDesky (NUTS3)';
COMMENT ON COLUMN notice_boards.nuts4_id IS 'District ID from eDesky (NUTS4)';
COMMENT ON COLUMN notice_boards.nuts4_name IS 'District name from eDesky (NUTS4)';
COMMENT ON COLUMN notice_boards.edesky_parent_id IS 'Parent board ID from eDesky hierarchy';
COMMENT ON COLUMN notice_boards.edesky_parent_name IS 'Parent board name from eDesky hierarchy';

-- =============================================================================
-- 2. Documents - URLs and text path
-- =============================================================================

-- eDesky URL for the document
ALTER TABLE documents ADD COLUMN IF NOT EXISTS edesky_url TEXT;

-- Original URL on the source notice board
ALTER TABLE documents ADD COLUMN IF NOT EXISTS orig_url TEXT;

-- Path to extracted text file (relative to storage root)
ALTER TABLE documents ADD COLUMN IF NOT EXISTS extracted_text_path TEXT;

-- Unique index on external_id per notice board for efficient upserts
CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_external_id
ON documents(notice_board_id, external_id) WHERE external_id IS NOT NULL;

-- Index for querying by edesky_url
CREATE INDEX IF NOT EXISTS idx_documents_edesky_url
ON documents(edesky_url) WHERE edesky_url IS NOT NULL;

COMMENT ON COLUMN documents.edesky_url IS 'URL to document on eDesky.cz';
COMMENT ON COLUMN documents.orig_url IS 'Original URL on source notice board';
COMMENT ON COLUMN documents.extracted_text_path IS 'Path to extracted text file in storage';

-- =============================================================================
-- 3. Attachments - original URL
-- =============================================================================

-- Original URL for downloading the attachment file
ALTER TABLE attachments ADD COLUMN IF NOT EXISTS orig_url TEXT;

-- Unique index on (document_id, orig_url) for upsert deduplication
CREATE UNIQUE INDEX IF NOT EXISTS idx_attachments_document_orig_url
ON attachments(document_id, orig_url) WHERE orig_url IS NOT NULL;

COMMENT ON COLUMN attachments.orig_url IS 'Original download URL for the attachment file';

COMMIT;

-- Print summary
DO $$
BEGIN
    RAISE NOTICE 'Migration v5 completed!';
    RAISE NOTICE 'Added eDesky integration fields:';
    RAISE NOTICE '';
    RAISE NOTICE 'notice_boards:';
    RAISE NOTICE '  - edesky_id (INTEGER, unique index)';
    RAISE NOTICE '  - edesky_category (VARCHAR)';
    RAISE NOTICE '  - nuts3_id, nuts3_name';
    RAISE NOTICE '  - nuts4_id, nuts4_name';
    RAISE NOTICE '  - edesky_parent_id, edesky_parent_name';
    RAISE NOTICE '';
    RAISE NOTICE 'documents:';
    RAISE NOTICE '  - edesky_url (TEXT)';
    RAISE NOTICE '  - orig_url (TEXT)';
    RAISE NOTICE '  - extracted_text_path (TEXT)';
    RAISE NOTICE '';
    RAISE NOTICE 'attachments:';
    RAISE NOTICE '  - orig_url (TEXT)';
END $$;
