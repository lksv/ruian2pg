-- Notice Board Documents - Migration v3
-- Adds building_refs table and Martin function for building references
--
-- Run with: psql -U ruian -d ruian -f scripts/migrate_notice_boards_v3.sql

BEGIN;

-- =============================================================================
-- 1. building_refs - References to buildings extracted from documents
-- =============================================================================

CREATE TABLE IF NOT EXISTS building_refs (
    id SERIAL PRIMARY KEY,

    -- Reference source
    attachment_id INTEGER NOT NULL REFERENCES attachments(id) ON DELETE CASCADE,
    ref_type_id INTEGER NOT NULL REFERENCES ref_types(id),

    -- Link to RUIAN building
    building_code INTEGER,  -- FK to stavebniobjekty.kod

    -- Extracted data
    municipality_name VARCHAR(255),
    part_of_municipality_name VARCHAR(255),
    house_number INTEGER,
    raw_text VARCHAR(512),

    -- Text position & confidence
    text_start INTEGER,
    text_end INTEGER,
    confidence REAL DEFAULT 1.0,

    created_at TIMESTAMP DEFAULT NOW(),

    UNIQUE(attachment_id, building_code, ref_type_id)
);

CREATE INDEX IF NOT EXISTS idx_building_refs_attachment ON building_refs(attachment_id);
CREATE INDEX IF NOT EXISTS idx_building_refs_building ON building_refs(building_code);
CREATE INDEX IF NOT EXISTS idx_building_refs_ref_type ON building_refs(ref_type_id);

COMMENT ON TABLE building_refs IS 'References to buildings extracted from document attachments';
COMMENT ON COLUMN building_refs.building_code IS 'Reference to RUIAN stavebniobjekty.kod (if matched)';

-- =============================================================================
-- 2. Martin Tile Server Function: Buildings with document references
-- =============================================================================

CREATE OR REPLACE FUNCTION buildings_with_documents(z integer, x integer, y integer)
RETURNS bytea AS $$
    SELECT ST_AsMVT(tile, 'buildings_with_documents', 4096, 'geom')
    FROM (
        SELECT DISTINCT ON (so.kod)
            so.kod AS id,
            ST_AsMVTGeom(
                ST_Transform(so.originalnihranice, 3857),
                ST_TileEnvelope(z, x, y),
                4096, 256, true
            ) AS geom,
            so.cislodomovni[1] AS house_number,
            d.id AS document_id,
            d.title AS document_title,
            dt.code AS document_type,
            rt.code AS ref_type,
            br.confidence
        FROM stavebniobjekty so
        JOIN building_refs br ON br.building_code = so.kod
        JOIN attachments a ON a.id = br.attachment_id
        JOIN documents d ON d.id = a.document_id
        LEFT JOIN document_types dt ON dt.id = d.document_type_id
        LEFT JOIN ref_types rt ON rt.id = br.ref_type_id
        WHERE so.originalnihranice IS NOT NULL
          AND ST_Transform(so.originalnihranice, 3857) && ST_TileEnvelope(z, x, y)
        ORDER BY so.kod, d.published_at DESC
    ) AS tile
    WHERE geom IS NOT NULL
$$ LANGUAGE SQL STABLE PARALLEL SAFE;

COMMENT ON FUNCTION buildings_with_documents(integer, integer, integer) IS
    '{"description": "Buildings referenced in notice board documents", "name": "buildings_with_documents"}';

COMMIT;

-- Print summary
DO $$
BEGIN
    RAISE NOTICE 'Migration v3 completed!';
    RAISE NOTICE 'Added: building_refs table';
    RAISE NOTICE 'Added: buildings_with_documents() Martin function';
END $$;
