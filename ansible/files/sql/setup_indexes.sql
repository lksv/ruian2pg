-- RUIAN Spatial Indexes Setup Script
-- Creates GiST indexes on all geometry columns for optimal tile generation
-- Run with: psql -U ruian -d ruian -f scripts/setup_indexes.sql

-- Note: Most indexes should already exist from ogr2ogr import,
-- but this script ensures all are present.

-- Address points (adresnimista)
CREATE INDEX IF NOT EXISTS idx_adresnimista_geom ON adresnimista USING GIST(geom);
CREATE INDEX IF NOT EXISTS idx_adresnimista_zachranka ON adresnimista USING GIST(zachranka);
CREATE INDEX IF NOT EXISTS idx_adresnimista_hasici ON adresnimista USING GIST(hasici);

-- Buildings (stavebniobjekty)
CREATE INDEX IF NOT EXISTS idx_stavebniobjekty_geom ON stavebniobjekty USING GIST(geom);
CREATE INDEX IF NOT EXISTS idx_stavebniobjekty_originalnihranice ON stavebniobjekty USING GIST(originalnihranice);
CREATE INDEX IF NOT EXISTS idx_stavebniobjekty_originalnihraniceompv ON stavebniobjekty USING GIST(originalnihraniceompv);

-- Parcels (parcely)
CREATE INDEX IF NOT EXISTS idx_parcely_geom ON parcely USING GIST(geom);
CREATE INDEX IF NOT EXISTS idx_parcely_originalnihranice ON parcely USING GIST(originalnihranice);
CREATE INDEX IF NOT EXISTS idx_parcely_originalnihraniceompv ON parcely USING GIST(originalnihraniceompv);

-- Streets (ulice)
CREATE INDEX IF NOT EXISTS idx_ulice_geom ON ulice USING GIST(geom);

-- Municipalities (obce)
CREATE INDEX IF NOT EXISTS idx_obce_geom ON obce USING GIST(geom);
CREATE INDEX IF NOT EXISTS idx_obce_originalnihranice ON obce USING GIST(originalnihranice);
CREATE INDEX IF NOT EXISTS idx_obce_generalizovanehranice ON obce USING GIST(generalizovanehranice);

-- Municipality parts (castiobci)
CREATE INDEX IF NOT EXISTS idx_castiobci_geom ON castiobci USING GIST(geom);

-- Cadastral areas (katastralniuzemi)
CREATE INDEX IF NOT EXISTS idx_katastralniuzemi_geom ON katastralniuzemi USING GIST(geom);
CREATE INDEX IF NOT EXISTS idx_katastralniuzemi_originalnihranice ON katastralniuzemi USING GIST(originalnihranice);
CREATE INDEX IF NOT EXISTS idx_katastralniuzemi_generalizovanehranice ON katastralniuzemi USING GIST(generalizovanehranice);

-- Basic settlement units (zsj)
CREATE INDEX IF NOT EXISTS idx_zsj_geom ON zsj USING GIST(geom);
CREATE INDEX IF NOT EXISTS idx_zsj_originalnihranice ON zsj USING GIST(originalnihranice);

-- Districts (okresy)
CREATE INDEX IF NOT EXISTS idx_okresy_geom ON okresy USING GIST(geom);
CREATE INDEX IF NOT EXISTS idx_okresy_originalnihranice ON okresy USING GIST(originalnihranice);
CREATE INDEX IF NOT EXISTS idx_okresy_generalizovanehranice ON okresy USING GIST(generalizovanehranice);

-- Regions (kraje/vusc)
CREATE INDEX IF NOT EXISTS idx_kraje_geom ON kraje USING GIST(geom);
CREATE INDEX IF NOT EXISTS idx_kraje_originalnihranice ON kraje USING GIST(originalnihranice);
CREATE INDEX IF NOT EXISTS idx_kraje_generalizovanehranice ON kraje USING GIST(generalizovanehranice);

CREATE INDEX IF NOT EXISTS idx_vusc_geom ON vusc USING GIST(geom);
CREATE INDEX IF NOT EXISTS idx_vusc_originalnihranice ON vusc USING GIST(originalnihranice);
CREATE INDEX IF NOT EXISTS idx_vusc_generalizovanehranice ON vusc USING GIST(generalizovanehranice);

-- ORP (municipalities with extended powers)
CREATE INDEX IF NOT EXISTS idx_orp_geom ON orp USING GIST(geom);
CREATE INDEX IF NOT EXISTS idx_orp_originalnihranice ON orp USING GIST(originalnihranice);
CREATE INDEX IF NOT EXISTS idx_orp_generalizovanehranice ON orp USING GIST(generalizovanehranice);

-- POU (municipalities with authorized municipal office)
CREATE INDEX IF NOT EXISTS idx_pou_geom ON pou USING GIST(geom);
CREATE INDEX IF NOT EXISTS idx_pou_originalnihranice ON pou USING GIST(originalnihranice);
CREATE INDEX IF NOT EXISTS idx_pou_generalizovanehranice ON pou USING GIST(generalizovanehranice);

-- Cohesion regions (regionysoudrznosti)
CREATE INDEX IF NOT EXISTS idx_regionysoudrznosti_geom ON regionysoudrznosti USING GIST(geom);
CREATE INDEX IF NOT EXISTS idx_regionysoudrznosti_originalnihranice ON regionysoudrznosti USING GIST(originalnihranice);
CREATE INDEX IF NOT EXISTS idx_regionysoudrznosti_generalizovanehranice ON regionysoudrznosti USING GIST(generalizovanehranice);

-- Administrative districts (spravniobvody)
CREATE INDEX IF NOT EXISTS idx_spravniobvody_geom ON spravniobvody USING GIST(geom);
CREATE INDEX IF NOT EXISTS idx_spravniobvody_originalnihranice ON spravniobvody USING GIST(originalnihranice);

-- MOMC (municipal district parts)
CREATE INDEX IF NOT EXISTS idx_momc_geom ON momc USING GIST(geom);
CREATE INDEX IF NOT EXISTS idx_momc_originalnihranice ON momc USING GIST(originalnihranice);

-- MOP (municipal districts)
CREATE INDEX IF NOT EXISTS idx_mop_geom ON mop USING GIST(geom);
CREATE INDEX IF NOT EXISTS idx_mop_originalnihranice ON mop USING GIST(originalnihranice);

-- States (staty)
CREATE INDEX IF NOT EXISTS idx_staty_geom ON staty USING GIST(geom);
CREATE INDEX IF NOT EXISTS idx_staty_originalnihranice ON staty USING GIST(originalnihranice);
CREATE INDEX IF NOT EXISTS idx_staty_generalizovanehranice ON staty USING GIST(generalizovanehranice);

-- Analyze tables for query optimizer
ANALYZE adresnimista;
ANALYZE stavebniobjekty;
ANALYZE parcely;
ANALYZE ulice;
ANALYZE obce;
ANALYZE castiobci;
ANALYZE katastralniuzemi;
ANALYZE zsj;
ANALYZE okresy;
ANALYZE kraje;
ANALYZE vusc;
ANALYZE orp;
ANALYZE pou;
ANALYZE regionysoudrznosti;
ANALYZE spravniobvody;
ANALYZE momc;
ANALYZE mop;
ANALYZE staty;

-- Show index creation status
SELECT
    tablename,
    indexname,
    pg_size_pretty(pg_relation_size(indexname::regclass)) AS index_size
FROM pg_indexes
WHERE schemaname = 'public'
AND indexname LIKE '%geom%' OR indexname LIKE '%hranice%'
ORDER BY tablename, indexname;
