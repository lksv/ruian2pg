-- Notice Board Documents - Migration v4
-- Optimizes Martin tile functions to use spatial indexes correctly
--
-- Problem: Original functions bypass GIST index by transforming geometry column:
--   WHERE ST_Transform(p.originalnihranice, 3857) && ST_TileEnvelope(z, x, y)
-- This causes sequential scan + transform of ALL geometries (~3M parcels)
--
-- Solution: Transform tile envelope instead of geometry column:
--   WHERE p.originalnihranice && ST_Transform(ST_TileEnvelope(z, x, y), 5514)
-- This transforms 1 bbox instead of millions of geometries and uses GIST index
--
-- Run with: psql -U ruian -d ruian -f scripts/migrate_notice_boards_v4.sql

BEGIN;

-- =============================================================================
-- 1. Optimized: parcels_with_documents
-- =============================================================================

CREATE OR REPLACE FUNCTION parcels_with_documents(z integer, x integer, y integer)
RETURNS bytea AS $$
DECLARE
    tile_bounds geometry;
BEGIN
    -- Pre-compute tile bounds in EPSG:5514 (S-JTSK / Krovak East North)
    tile_bounds := ST_Transform(ST_TileEnvelope(z, x, y), 5514);

    RETURN (
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
            WHERE p.originalnihranice IS NOT NULL
              AND p.originalnihranice && tile_bounds
            ORDER BY p.id, d.published_at DESC
        ) AS tile
        WHERE geom IS NOT NULL
    );
END;
$$ LANGUAGE plpgsql STABLE PARALLEL SAFE;

COMMENT ON FUNCTION parcels_with_documents(integer, integer, integer) IS
    '{"description": "Parcels referenced in notice board documents", "name": "parcels_with_documents"}';

-- =============================================================================
-- 2. Optimized: streets_with_documents
-- =============================================================================

CREATE OR REPLACE FUNCTION streets_with_documents(z integer, x integer, y integer)
RETURNS bytea AS $$
DECLARE
    tile_bounds geometry;
BEGIN
    -- Pre-compute tile bounds in EPSG:5514 (S-JTSK / Krovak East North)
    tile_bounds := ST_Transform(ST_TileEnvelope(z, x, y), 5514);

    RETURN (
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
            WHERE u.geom IS NOT NULL
              AND u.geom && tile_bounds
            ORDER BY u.kod, d.published_at DESC
        ) AS tile
        WHERE geom IS NOT NULL
    );
END;
$$ LANGUAGE plpgsql STABLE PARALLEL SAFE;

COMMENT ON FUNCTION streets_with_documents(integer, integer, integer) IS
    '{"description": "Streets referenced in notice board documents", "name": "streets_with_documents"}';

-- =============================================================================
-- 3. Optimized: addresses_with_documents
-- =============================================================================

CREATE OR REPLACE FUNCTION addresses_with_documents(z integer, x integer, y integer)
RETURNS bytea AS $$
DECLARE
    tile_bounds geometry;
BEGIN
    -- Pre-compute tile bounds in EPSG:5514 (S-JTSK / Krovak East North)
    tile_bounds := ST_Transform(ST_TileEnvelope(z, x, y), 5514);

    RETURN (
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
            WHERE am.geom IS NOT NULL
              AND am.geom && tile_bounds
            ORDER BY am.kod, d.published_at DESC
        ) AS tile
        WHERE geom IS NOT NULL
    );
END;
$$ LANGUAGE plpgsql STABLE PARALLEL SAFE;

COMMENT ON FUNCTION addresses_with_documents(integer, integer, integer) IS
    '{"description": "Addresses referenced in notice board documents", "name": "addresses_with_documents"}';

-- =============================================================================
-- 4. Optimized: buildings_with_documents
-- =============================================================================

CREATE OR REPLACE FUNCTION buildings_with_documents(z integer, x integer, y integer)
RETURNS bytea AS $$
DECLARE
    tile_bounds geometry;
BEGIN
    -- Pre-compute tile bounds in EPSG:5514 (S-JTSK / Krovak East North)
    tile_bounds := ST_Transform(ST_TileEnvelope(z, x, y), 5514);

    RETURN (
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
              AND so.originalnihranice && tile_bounds
            ORDER BY so.kod, d.published_at DESC
        ) AS tile
        WHERE geom IS NOT NULL
    );
END;
$$ LANGUAGE plpgsql STABLE PARALLEL SAFE;

COMMENT ON FUNCTION buildings_with_documents(integer, integer, integer) IS
    '{"description": "Buildings referenced in notice board documents", "name": "buildings_with_documents"}';

COMMIT;

-- Print summary
DO $$
BEGIN
    RAISE NOTICE 'Migration v4 completed!';
    RAISE NOTICE 'Optimized Martin tile functions to use spatial indexes:';
    RAISE NOTICE '  - parcels_with_documents()';
    RAISE NOTICE '  - streets_with_documents()';
    RAISE NOTICE '  - addresses_with_documents()';
    RAISE NOTICE '  - buildings_with_documents()';
    RAISE NOTICE '';
    RAISE NOTICE 'Key change: Transform tile envelope instead of geometry column';
    RAISE NOTICE '  BEFORE: WHERE ST_Transform(geom, 3857) && ST_TileEnvelope(z, x, y)';
    RAISE NOTICE '  AFTER:  WHERE geom && ST_Transform(ST_TileEnvelope(z, x, y), 5514)';
END $$;
