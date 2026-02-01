# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Notice Board Map** - visualizes addresses, parcels, and streets referenced in Czech municipal official notice board documents (úřední desky). Imports RUIAN (territorial registry) data into PostGIS, extracts location references from documents, displays on interactive map.

## Documentation

- @CLAUDE.local.md - local environment setup (not committed)
- @README.md - installation, usage examples
- @ARCHITECTURE.md - system architecture, database schema, Python classes
- @ansible/README.md - production deployment

## Commands

```bash
# Install dependencies
uv sync

# Run tests (do this after every code change)
uv run python -m pytest tests/ -v

# Run single test
uv run python -m pytest tests/test_downloader.py::TestClass::test_method -v

# Lint and format
uv run ruff check src/ scripts/ tests/
uv run ruff format src/ scripts/ tests/

# Type check
uv run python -m mypy src/ruian_import/ src/notice_boards/ scripts/

# Full validation before committing
uv run ruff check src/ scripts/ tests/ && uv run ruff format src/ scripts/ tests/ && uv run python -m mypy src/ruian_import/ src/notice_boards/ scripts/ && uv run python -m pytest tests/ -v
```

### RUIAN Data Operations

```bash
# Download and import state-level data
uv run python scripts/download_ruian.py --latest
uv run python scripts/import_ruian.py --latest

# Download and import all municipalities (full country, ~100GB total)
uv run python scripts/download_ruian.py --municipalities --workers 10
uv run python scripts/import_ruian.py --municipalities --continue
```

### Notice Board Operations

```bash
# Fetch and import notice board list
uv run python scripts/fetch_notice_boards.py -o data/notice_boards.json
uv run python scripts/import_notice_boards.py data/notice_boards.json

# Enrich existing records (match by ICO/name, don't create new)
uv run python scripts/import_notice_boards.py data/notice_boards.json --enrich-only

# Apply database migrations (run in order)
psql -U ruian -d ruian -f scripts/setup_notice_boards_db.sql
psql -U ruian -d ruian -f scripts/migrate_notice_boards_v2.sql
psql -U ruian -d ruian -f scripts/migrate_notice_boards_v3.sql
psql -U ruian -d ruian -f scripts/migrate_notice_boards_v4.sql
psql -U ruian -d ruian -f scripts/migrate_notice_boards_v5.sql
psql -U ruian -d ruian -f scripts/migrate_notice_boards_v6.sql

# Generate test data for map rendering
uv run python scripts/generate_test_references.py --cadastral-name "Veveří"
uv run python scripts/generate_test_references.py --cleanup
```

### eDesky.cz Integration

```bash
# Set API key (get from https://edesky.cz/uzivatel/edit)
export EDESKY_API_KEY=your_api_key

# Sync ALL boards from eDesky with smart matching
uv run python scripts/sync_edesky_boards.py --all --match-existing

# Preview sync without changes (dry-run)
uv run python scripts/sync_edesky_boards.py --all --match-existing --dry-run

# Show statistics
uv run python scripts/sync_edesky_boards.py --stats

# Verbose output
uv run python scripts/sync_edesky_boards.py --all --match-existing --verbose
```

### OFN Document Download

OFN (Open Formal Norm) is the Czech standard for official notice board data. Download documents from boards with OFN JSON-LD feeds:

```bash
# Download from specific OFN feed URL
uv run python scripts/download_ofn_documents.py --url "https://edeska.brno.cz/eDeska01/opendata"

# Download from board by database ID
uv run python scripts/download_ofn_documents.py --board-id 40888

# Download from ALL boards with OFN URL (~197 boards, ~23k documents)
uv run python scripts/download_ofn_documents.py --all-ofn

# Include original attachment files (not just metadata)
uv run python scripts/download_ofn_documents.py --all-ofn --download-originals

# Preview without saving (dry-run)
uv run python scripts/download_ofn_documents.py --url "..." --dry-run --verbose

# Show statistics
uv run python scripts/download_ofn_documents.py --stats
```

**Notes:**
- OFN feeds return only active documents (not archived like eDesky)
- Some feeds have non-standard date formats - these documents are skipped with warning
- Re-running updates existing documents (no duplicates)

### Production: Full Notice Board Reload

To completely reload notice boards on production server:

```bash
# 1. SSH to production
ssh lukas@46.224.67.103
cd ~/ruian2pg

# 2. Truncate notice_boards (cascades to documents, attachments, refs)
docker exec -i ruian-postgis psql -U ruian -d ruian -c 'TRUNCATE notice_boards CASCADE;'

# 3. Load all boards from eDesky (primary source, ~6,500 boards)
set -a && source .env && set +a
uv run python scripts/sync_edesky_boards.py --all

# 4. Enrich with Cesko.Digital data (municipality codes, data boxes, addresses)
uv run python scripts/import_notice_boards.py data/notice_boards.json --enrich-only

# 5. Verify
uv run python scripts/import_notice_boards.py --stats
```

**Why this order?**
- eDesky is the primary source with consistent IDs and NUTS3/NUTS4 regions
- Cesko.Digital provides municipality_code (RUIAN link), data_box_id, addresses
- `--enrich-only` matches by ICO or name+district, updates only NULL fields

**Expected results:**
- ~6,500 boards from eDesky (all with edesky_id, edesky_url, NUTS3/NUTS4)
- ~6,300 enriched with Cesko.Digital data (municipality_code, data_box_id)

### Local Development Services

```bash
# Start PostGIS (ensure container exists first, see CLAUDE.local.md)
podman start ruian-postgis

# Start Martin tile server
podman run -d --name martin -p 3000:3000 \
  -v ./martin/martin.yaml:/config.yaml:ro \
  ghcr.io/maplibre/martin --config /config.yaml

# Serve frontend
cd web && python3 -m http.server 8080
```

## Architecture

**Data flow:** CUZK API → `RuianDownloader` → `data/*.xml.zip` → `RuianImporter` (ogr2ogr) → PostGIS

**Source modules:**
- `src/ruian_import/` - RUIAN download/import (config, downloader, importer)
- `src/notice_boards/` - document processing (validators, storage, parsers, scrapers)
- `scripts/` - CLI tools and SQL migrations

**File types:**
- `*_ST_UKSH.xml.zip` - State-level data (regions, districts)
- `*_OB_*_UKSH.xml.zip` - Municipality data (addresses, buildings, parcels)

## Key Dependencies

- `ogr2ogr` (GDAL) - required for VFR import (`brew install gdal`)
- `psycopg2-binary` - PostgreSQL connection
- `httpx` - HTTP downloads

## Database

Default: `localhost:5432/ruian` (user: ruian, password: ruian)

Environment variables: `RUIAN_DB_HOST`, `RUIAN_DB_PORT`, `RUIAN_DB_NAME`, `RUIAN_DB_USER`, `RUIAN_DB_PASSWORD`

Coordinate system: S-JTSK / Krovak East North (EPSG:5514)

### Spatial Index Best Practices

**IMPORTANT:** When writing PostGIS tile functions, transform the tile envelope (not geometry column) to use spatial indexes:

```sql
-- ❌ WRONG: Bypasses GIST index
WHERE ST_Transform(p.geom, 3857) && ST_TileEnvelope(z, x, y)

-- ✅ CORRECT: Uses GIST index
WHERE p.geom && ST_Transform(ST_TileEnvelope(z, x, y), 5514)
```

## Key Classes

- `RuianDownloader` (`src/ruian_import/downloader.py`) - downloads VFR files from CUZK
- `RuianImporter` (`src/ruian_import/importer.py`) - imports to PostGIS via ogr2ogr
- `RuianValidator` (`src/notice_boards/validators.py`) - validates parcel/address/street references against RUIAN
- `StorageBackend` (`src/notice_boards/storage.py`) - abstract attachment storage (FilesystemStorage impl)
- `TextExtractor` (`src/notice_boards/parsers/base.py`) - PDF text extraction
- `EdeskyApiClient` (`src/notice_boards/scrapers/edesky.py`) - eDesky.cz API client for notice board metadata
- `EdeskyScraper` (`src/notice_boards/scrapers/edesky.py`) - scraper for eDesky documents
- `OfnClient` (`src/notice_boards/scrapers/ofn.py`) - HTTP client for OFN JSON-LD feeds
- `OfnScraper` (`src/notice_boards/scrapers/ofn.py`) - scraper for OFN notice board documents
- `DocumentRepository` (`src/notice_boards/repository.py`) - database operations for documents/attachments

## Database Tables

**RUIAN (from ogr2ogr):** `parcely`, `stavebniobjekty`, `adresnimista`, `ulice`, `obce`, `katastralniuzemi`, `okresy`, `vusc`

**Notice boards:** `notice_boards`, `documents`, `attachments`, `parcel_refs`, `address_refs`, `street_refs`, `building_refs`, `lv_refs`

**Martin layers:** `parcels_with_documents`, `addresses_with_documents`, `streets_with_documents`, `buildings_with_documents`

## Production Deployment

See **[ansible/README.md](ansible/README.md)** for Ansible deployment.

```bash
cd ansible
ansible-playbook playbooks/site.yml --vault-password-file .vault_pass
ansible-playbook playbooks/site.yml --vault-password-file .vault_pass --tags nginx
```

**Stack:** PostgreSQL/PostGIS, Martin, Nginx (tile caching), Certbot (Let's Encrypt)
