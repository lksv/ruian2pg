-- Notice Board Documents - Database Schema
-- Migration script for creating tables related to notice board document processing
--
-- Run with: psql -U ruian -d ruian -f scripts/setup_notice_boards_db.sql

BEGIN;

-- =============================================================================
-- 1. notice_boards - Notice board sources
-- =============================================================================

CREATE TABLE IF NOT EXISTS notice_boards (
    id SERIAL PRIMARY KEY,

    -- Link to RUIAN municipality
    municipality_code INTEGER,  -- FK to obce.kod

    -- Organization identification
    name VARCHAR(255) NOT NULL,
    abbreviation VARCHAR(50),
    ico VARCHAR(20),                       -- IČO (organization ID)

    -- URLs
    source_url VARCHAR(1024),              -- Direct website URL
    edesky_url VARCHAR(1024),              -- eDesky.cz URL
    ofn_json_url VARCHAR(1024),            -- Open Formal Norm JSON API URL
    source_type VARCHAR(50),               -- 'ginis', 'vismo', 'edesky', 'ofn', ...

    -- Location
    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION,

    -- Address
    address_street VARCHAR(255),
    address_city VARCHAR(255),
    address_district VARCHAR(255),
    address_postal_code VARCHAR(10),
    address_region VARCHAR(100),
    address_point_id INTEGER,              -- RUIAN address point ID

    -- Contact
    data_box_id VARCHAR(20),               -- Datová schránka ID
    emails TEXT[],                         -- Array of email addresses

    -- Legal form
    legal_form_code INTEGER,               -- e.g., 801
    legal_form_label VARCHAR(100),         -- e.g., "Obec"
    board_type VARCHAR(50),                -- 'obec', 'kraj', 'ministerstvo', ...

    -- Scraping metadata
    is_active BOOLEAN DEFAULT TRUE,
    last_scraped_at TIMESTAMP,
    scrape_interval_hours INTEGER DEFAULT 24,

    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_notice_boards_municipality ON notice_boards(municipality_code);
CREATE INDEX IF NOT EXISTS idx_notice_boards_ico ON notice_boards(ico);
CREATE INDEX IF NOT EXISTS idx_notice_boards_type ON notice_boards(board_type);
CREATE INDEX IF NOT EXISTS idx_notice_boards_is_active ON notice_boards(is_active);

COMMENT ON TABLE notice_boards IS 'Notice board sources - municipalities and other public authorities';
COMMENT ON COLUMN notice_boards.municipality_code IS 'Reference to RUIAN obce.kod';
COMMENT ON COLUMN notice_boards.ico IS 'Organization identification number (IČO)';
COMMENT ON COLUMN notice_boards.source_type IS 'Type of source system: ginis, vismo, edesky, ofn, ...';
COMMENT ON COLUMN notice_boards.data_box_id IS 'Data box ID (Datová schránka)';

-- =============================================================================
-- 2. document_types - Document type classification
-- =============================================================================

CREATE TABLE IF NOT EXISTS document_types (
    id SERIAL PRIMARY KEY,

    -- Source type mapping (from notice board -> normalized)
    source_name VARCHAR(255),
    source_board_id INTEGER REFERENCES notice_boards(id) ON DELETE CASCADE,  -- NULL = global

    -- Normalized type (own classification)
    code VARCHAR(50) NOT NULL,
    name VARCHAR(255) NOT NULL,

    -- Categorization
    category VARCHAR(50),  -- 'real_estate', 'construction', 'traffic', 'other'

    UNIQUE(source_name, source_board_id)
);

CREATE INDEX IF NOT EXISTS idx_document_types_code ON document_types(code);
CREATE INDEX IF NOT EXISTS idx_document_types_category ON document_types(category);

COMMENT ON TABLE document_types IS 'Document type classification and mapping';

-- Insert default normalized document types
INSERT INTO document_types (code, name, category) VALUES
    ('auction', 'Auction notice', 'real_estate'),
    ('execution', 'Execution order', 'real_estate'),
    ('zoning', 'Zoning decision', 'construction'),
    ('building_permit', 'Building permit', 'construction'),
    ('demolition_permit', 'Demolition permit', 'construction'),
    ('street_cleaning', 'Street cleaning', 'traffic'),
    ('road_closure', 'Road closure', 'traffic'),
    ('public_notice', 'Public notice', 'general'),
    ('public_hearing', 'Public hearing', 'general'),
    ('other', 'Other', 'other')
ON CONFLICT DO NOTHING;

-- =============================================================================
-- 3. documents - Downloaded documents from notice boards
-- =============================================================================

CREATE TABLE IF NOT EXISTS documents (
    id SERIAL PRIMARY KEY,

    -- Relations
    notice_board_id INTEGER NOT NULL REFERENCES notice_boards(id) ON DELETE CASCADE,
    document_type_id INTEGER REFERENCES document_types(id) ON DELETE SET NULL,

    -- Identification
    external_id VARCHAR(255),

    -- Basic metadata
    title VARCHAR(1024) NOT NULL,
    description TEXT,

    -- Dates
    published_at DATE NOT NULL,
    valid_from DATE,
    valid_until DATE,

    -- Original metadata from source
    source_metadata JSONB,
    source_document_type VARCHAR(255),

    -- Processing status
    parse_status VARCHAR(20) DEFAULT 'pending',  -- pending, parsing, completed, failed
    parsed_at TIMESTAMP,
    parse_error TEXT,

    -- System
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),

    UNIQUE(notice_board_id, external_id)
);

CREATE INDEX IF NOT EXISTS idx_documents_board ON documents(notice_board_id);
CREATE INDEX IF NOT EXISTS idx_documents_type ON documents(document_type_id);
CREATE INDEX IF NOT EXISTS idx_documents_published ON documents(published_at);
CREATE INDEX IF NOT EXISTS idx_documents_valid_from ON documents(valid_from);
CREATE INDEX IF NOT EXISTS idx_documents_valid_until ON documents(valid_until);
CREATE INDEX IF NOT EXISTS idx_documents_parse_status ON documents(parse_status);
CREATE INDEX IF NOT EXISTS idx_documents_created ON documents(created_at);

COMMENT ON TABLE documents IS 'Documents downloaded from notice boards';
COMMENT ON COLUMN documents.external_id IS 'External ID from the source system';
COMMENT ON COLUMN documents.parse_status IS 'Processing status: pending, parsing, completed, failed';

-- =============================================================================
-- 4. attachments - Document attachments (PDFs, images, etc.)
-- =============================================================================

CREATE TABLE IF NOT EXISTS attachments (
    id SERIAL PRIMARY KEY,

    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,

    -- File info
    filename VARCHAR(512) NOT NULL,
    mime_type VARCHAR(100) NOT NULL,
    file_size_bytes BIGINT,
    storage_path VARCHAR(1024) NOT NULL,

    -- Checksum
    sha256_hash VARCHAR(64),

    -- Processing status
    parse_status VARCHAR(20) DEFAULT 'pending',  -- pending, parsing, completed, failed
    parsed_at TIMESTAMP,
    extracted_text TEXT,
    parse_error TEXT,

    -- Order
    position INTEGER DEFAULT 0,

    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_attachments_document ON attachments(document_id);
CREATE INDEX IF NOT EXISTS idx_attachments_mime ON attachments(mime_type);
CREATE INDEX IF NOT EXISTS idx_attachments_parse_status ON attachments(parse_status);
CREATE INDEX IF NOT EXISTS idx_attachments_hash ON attachments(sha256_hash);

-- Full-text search index on extracted text
CREATE INDEX IF NOT EXISTS idx_attachments_text ON attachments USING GIN(to_tsvector('simple', COALESCE(extracted_text, '')));

COMMENT ON TABLE attachments IS 'Attachment files belonging to documents';
COMMENT ON COLUMN attachments.storage_path IS 'Path in the storage backend (filesystem or S3)';
COMMENT ON COLUMN attachments.sha256_hash IS 'SHA-256 hash of file content for deduplication';

-- =============================================================================
-- 5. ref_types - Reference type classification
-- =============================================================================

CREATE TABLE IF NOT EXISTS ref_types (
    id SERIAL PRIMARY KEY,
    code VARCHAR(50) UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    description TEXT
);

INSERT INTO ref_types (code, name, description) VALUES
    ('subject', 'Subject', 'Parcel/address/street is the main subject of document'),
    ('affected', 'Affected', 'Object is affected by the decision'),
    ('neighbor', 'Neighbor', 'Neighboring parcel/address'),
    ('owner_address', 'Owner address', 'Address of the owner'),
    ('applicant_address', 'Applicant address', 'Address of the applicant'),
    ('mention', 'Mention', 'General mention in text')
ON CONFLICT DO NOTHING;

COMMENT ON TABLE ref_types IS 'Classification of reference types in documents';

-- =============================================================================
-- 6. parcel_refs - References to parcels extracted from documents
-- =============================================================================

CREATE TABLE IF NOT EXISTS parcel_refs (
    id SERIAL PRIMARY KEY,

    -- Reference source
    attachment_id INTEGER NOT NULL REFERENCES attachments(id) ON DELETE CASCADE,
    ref_type_id INTEGER NOT NULL REFERENCES ref_types(id),

    -- Link to RUIAN parcel
    parcel_id BIGINT,  -- FK to parcely.id (if found)

    -- Extracted data (in case parcel not in RUIAN or for matching)
    cadastral_area_code INTEGER,
    parcel_number INTEGER,
    parcel_sub_number INTEGER,
    raw_text VARCHAR(255),

    -- Text position
    text_start INTEGER,
    text_end INTEGER,

    -- Confidence score (0.0 - 1.0)
    confidence REAL DEFAULT 1.0,

    created_at TIMESTAMP DEFAULT NOW(),

    UNIQUE(attachment_id, parcel_id, ref_type_id)
);

CREATE INDEX IF NOT EXISTS idx_parcel_refs_attachment ON parcel_refs(attachment_id);
CREATE INDEX IF NOT EXISTS idx_parcel_refs_parcel ON parcel_refs(parcel_id);
CREATE INDEX IF NOT EXISTS idx_parcel_refs_cadastral ON parcel_refs(cadastral_area_code);
CREATE INDEX IF NOT EXISTS idx_parcel_refs_ref_type ON parcel_refs(ref_type_id);

COMMENT ON TABLE parcel_refs IS 'References to parcels extracted from document attachments';
COMMENT ON COLUMN parcel_refs.parcel_id IS 'Reference to RUIAN parcely.id (if matched)';
COMMENT ON COLUMN parcel_refs.confidence IS 'Extraction confidence score (0.0 - 1.0)';

-- =============================================================================
-- 7. address_refs - References to addresses extracted from documents
-- =============================================================================

CREATE TABLE IF NOT EXISTS address_refs (
    id SERIAL PRIMARY KEY,

    -- Reference source
    attachment_id INTEGER NOT NULL REFERENCES attachments(id) ON DELETE CASCADE,
    ref_type_id INTEGER NOT NULL REFERENCES ref_types(id),

    -- Link to RUIAN address
    address_point_code INTEGER,  -- FK to adresnimista.kod

    -- Extracted data
    municipality_name VARCHAR(255),
    street_name VARCHAR(255),
    house_number INTEGER,
    orientation_number INTEGER,
    postal_code INTEGER,
    raw_text VARCHAR(512),

    -- Text position & confidence
    text_start INTEGER,
    text_end INTEGER,
    confidence REAL DEFAULT 1.0,

    created_at TIMESTAMP DEFAULT NOW(),

    UNIQUE(attachment_id, address_point_code, ref_type_id)
);

CREATE INDEX IF NOT EXISTS idx_address_refs_attachment ON address_refs(attachment_id);
CREATE INDEX IF NOT EXISTS idx_address_refs_address ON address_refs(address_point_code);
CREATE INDEX IF NOT EXISTS idx_address_refs_ref_type ON address_refs(ref_type_id);

COMMENT ON TABLE address_refs IS 'References to addresses extracted from document attachments';
COMMENT ON COLUMN address_refs.address_point_code IS 'Reference to RUIAN adresnimista.kod (if matched)';

-- =============================================================================
-- 8. street_refs - References to streets extracted from documents
-- =============================================================================

CREATE TABLE IF NOT EXISTS street_refs (
    id SERIAL PRIMARY KEY,

    -- Reference source
    attachment_id INTEGER NOT NULL REFERENCES attachments(id) ON DELETE CASCADE,
    ref_type_id INTEGER NOT NULL REFERENCES ref_types(id),

    -- Link to RUIAN street
    street_code INTEGER,  -- FK to ulice.kod

    -- Extracted data
    municipality_name VARCHAR(255),
    street_name VARCHAR(255),
    raw_text VARCHAR(512),

    -- Text position & confidence
    text_start INTEGER,
    text_end INTEGER,
    confidence REAL DEFAULT 1.0,

    created_at TIMESTAMP DEFAULT NOW(),

    UNIQUE(attachment_id, street_code, ref_type_id)
);

CREATE INDEX IF NOT EXISTS idx_street_refs_attachment ON street_refs(attachment_id);
CREATE INDEX IF NOT EXISTS idx_street_refs_street ON street_refs(street_code);
CREATE INDEX IF NOT EXISTS idx_street_refs_ref_type ON street_refs(ref_type_id);

COMMENT ON TABLE street_refs IS 'References to streets extracted from document attachments';
COMMENT ON COLUMN street_refs.street_code IS 'Reference to RUIAN ulice.kod (if matched)';

-- =============================================================================
-- 9. lv_refs - References to ownership sheets (LV - listy vlastnictví)
-- =============================================================================

CREATE TABLE IF NOT EXISTS lv_refs (
    id SERIAL PRIMARY KEY,

    attachment_id INTEGER NOT NULL REFERENCES attachments(id) ON DELETE CASCADE,
    ref_type_id INTEGER NOT NULL REFERENCES ref_types(id),

    -- LV data
    cadastral_area_code INTEGER,
    lv_number INTEGER NOT NULL,
    raw_text VARCHAR(255),

    -- Text position & confidence
    text_start INTEGER,
    text_end INTEGER,
    confidence REAL DEFAULT 1.0,

    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_lv_refs_attachment ON lv_refs(attachment_id);
CREATE INDEX IF NOT EXISTS idx_lv_refs_cadastral_lv ON lv_refs(cadastral_area_code, lv_number);
CREATE INDEX IF NOT EXISTS idx_lv_refs_ref_type ON lv_refs(ref_type_id);

COMMENT ON TABLE lv_refs IS 'References to ownership sheets (LV) extracted from document attachments';
COMMENT ON COLUMN lv_refs.lv_number IS 'Ownership sheet number (číslo listu vlastnictví)';

-- =============================================================================
-- 10. Martin Tile Server Function Sources
-- =============================================================================

-- Function: Parcels with document references
-- Note: RUIAN data is in EPSG:5514, ST_TileEnvelope returns EPSG:3857
CREATE OR REPLACE FUNCTION parcels_with_documents(z integer, x integer, y integer)
RETURNS bytea AS $$
    SELECT ST_AsMVT(tile, 'parcels_with_documents', 4096, 'geom')
    FROM (
        SELECT DISTINCT ON (p.id)
            p.id,
            ST_AsMVTGeom(
                ST_Transform(p.originalnihranice, 3857),
                ST_TileEnvelope(z, x, y),
                4096, 256, true
            ) AS geom,
            p.kmenovecislo AS parcel_number,
            p.pododdelenicisla AS parcel_sub_number,
            d.id AS document_id,
            d.title AS document_title,
            dt.code AS document_type,
            rt.code AS ref_type,
            pr.confidence
        FROM parcely p
        JOIN parcel_refs pr ON pr.parcel_id = p.id
        JOIN attachments a ON a.id = pr.attachment_id
        JOIN documents d ON d.id = a.document_id
        LEFT JOIN document_types dt ON dt.id = d.document_type_id
        LEFT JOIN ref_types rt ON rt.id = pr.ref_type_id
        WHERE ST_Transform(p.originalnihranice, 3857) && ST_TileEnvelope(z, x, y)
        ORDER BY p.id, d.published_at DESC
    ) AS tile
    WHERE geom IS NOT NULL
$$ LANGUAGE SQL STABLE PARALLEL SAFE;

COMMENT ON FUNCTION parcels_with_documents(integer, integer, integer) IS
    '{"description": "Parcels referenced in notice board documents", "name": "parcels_with_documents"}';

-- Function: Streets with document references
CREATE OR REPLACE FUNCTION streets_with_documents(z integer, x integer, y integer)
RETURNS bytea AS $$
    SELECT ST_AsMVT(tile, 'streets_with_documents', 4096, 'geom')
    FROM (
        SELECT DISTINCT ON (u.kod)
            u.kod AS id,
            ST_AsMVTGeom(
                ST_Transform(u.geom, 3857),
                ST_TileEnvelope(z, x, y),
                4096, 256, true
            ) AS geom,
            u.nazev AS street_name,
            d.id AS document_id,
            d.title AS document_title,
            dt.code AS document_type,
            rt.code AS ref_type,
            sr.confidence
        FROM ulice u
        JOIN street_refs sr ON sr.street_code = u.kod
        JOIN attachments a ON a.id = sr.attachment_id
        JOIN documents d ON d.id = a.document_id
        LEFT JOIN document_types dt ON dt.id = d.document_type_id
        LEFT JOIN ref_types rt ON rt.id = sr.ref_type_id
        WHERE ST_Transform(u.geom, 3857) && ST_TileEnvelope(z, x, y)
        ORDER BY u.kod, d.published_at DESC
    ) AS tile
    WHERE geom IS NOT NULL
$$ LANGUAGE SQL STABLE PARALLEL SAFE;

COMMENT ON FUNCTION streets_with_documents(integer, integer, integer) IS
    '{"description": "Streets referenced in notice board documents", "name": "streets_with_documents"}';

-- Function: Addresses with document references
CREATE OR REPLACE FUNCTION addresses_with_documents(z integer, x integer, y integer)
RETURNS bytea AS $$
    SELECT ST_AsMVT(tile, 'addresses_with_documents', 4096, 'geom')
    FROM (
        SELECT DISTINCT ON (am.kod)
            am.kod AS id,
            ST_AsMVTGeom(
                ST_Transform(am.geom, 3857),
                ST_TileEnvelope(z, x, y),
                4096, 256, true
            ) AS geom,
            am.cislodomovni AS house_number,
            am.cisloorientacni AS orientation_number,
            d.id AS document_id,
            d.title AS document_title,
            dt.code AS document_type,
            rt.code AS ref_type,
            ar.confidence
        FROM adresnimista am
        JOIN address_refs ar ON ar.address_point_code = am.kod
        JOIN attachments a ON a.id = ar.attachment_id
        JOIN documents d ON d.id = a.document_id
        LEFT JOIN document_types dt ON dt.id = d.document_type_id
        LEFT JOIN ref_types rt ON rt.id = ar.ref_type_id
        WHERE ST_Transform(am.geom, 3857) && ST_TileEnvelope(z, x, y)
        ORDER BY am.kod, d.published_at DESC
    ) AS tile
    WHERE geom IS NOT NULL
$$ LANGUAGE SQL STABLE PARALLEL SAFE;

COMMENT ON FUNCTION addresses_with_documents(integer, integer, integer) IS
    '{"description": "Addresses referenced in notice board documents", "name": "addresses_with_documents"}';

COMMIT;

-- Print summary
DO $$
BEGIN
    RAISE NOTICE 'Notice board schema created successfully!';
    RAISE NOTICE 'Tables: notice_boards, document_types, documents, attachments';
    RAISE NOTICE 'Reference tables: ref_types, parcel_refs, address_refs, street_refs, lv_refs';
    RAISE NOTICE 'Martin functions: parcels_with_documents, streets_with_documents, addresses_with_documents';
END $$;
