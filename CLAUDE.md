# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Notice Board Map** - a visualization tool that displays addresses, parcels, and streets referenced in documents published on Czech municipal official notice boards (úřední desky).

**Use cases:**
- Discover when your municipality is selling or renting land near your property
- Get notified about real estate auctions in your neighborhood
- Track construction permits and zoning decisions affecting nearby parcels
- Find out about street cleaning schedules or road closures on your street

The project imports Czech RUIAN (territorial identification, addresses and real estate registry) data into PostGIS, then extracts location references from notice board documents and visualizes them on an interactive map.

## Documentation

- @README.md - Project overview, installation, usage examples
- @ARCHITECTURE.md - System architecture, database schema, Python classes
- @ansible/README.md - Production deployment with Ansible

## Development Workflow

**IMPORTANT: After every code change, run tests to ensure nothing is broken:**

```bash
# Quick validation (run after each change)
uv run python -m pytest tests/ -v

# Full validation before committing
uv run ruff check src/ scripts/ tests/
uv run ruff format src/ scripts/ tests/
uv run python -m mypy src/ruian_import/ src/notice_boards/ scripts/
uv run python -m pytest tests/ -v
```

## Commands

```bash
# Install dependencies
uv sync

# Lint
uv run ruff check src/ scripts/ tests/

# Format
uv run ruff format src/ scripts/ tests/

# Type check
uv run python -m mypy src/ruian_import/ src/notice_boards/ scripts/

# Run all tests
uv run python -m pytest tests/ -v

# Run tests with coverage
uv run python -m pytest tests/ -v --cov=src/ruian_import

# Run single test file
uv run python -m pytest tests/test_downloader.py -v

# Run single test
uv run python -m pytest tests/test_downloader.py::TestRuianDownloaderPatterns::test_ob_file_pattern -v

# Download RUIAN data
uv run python scripts/download_ruian.py --latest

# Download all municipalities (parallel)
uv run python scripts/download_ruian.py --municipalities --workers 10

# Import to PostGIS
uv run python scripts/import_ruian.py --latest

# Import all municipalities
uv run python scripts/import_ruian.py --municipalities

# Fetch notice board list (Česko.Digital + NKOD OFN)
uv run python scripts/fetch_notice_boards.py -o data/notice_boards.json

# Import notice boards to database
uv run python scripts/import_notice_boards.py data/notice_boards.json

# Generate test data for map rendering validation
uv run python scripts/generate_test_references.py --cadastral-name "Veveří"

# Cleanup test data
uv run python scripts/generate_test_references.py --cleanup

# Apply database migrations
psql -U ruian -d ruian -f scripts/setup_notice_boards_db.sql
psql -U ruian -d ruian -f scripts/migrate_notice_boards_v2.sql
psql -U ruian -d ruian -f scripts/migrate_notice_boards_v3.sql
psql -U ruian -d ruian -f scripts/migrate_notice_boards_v4.sql
```

## Architecture

**Data flow:** CUZK API → `RuianDownloader` → `data/*.xml.zip` → `RuianImporter` (ogr2ogr) → PostGIS

**Source modules:**
- `src/ruian_import/` - Core RUIAN download and import (config, downloader, importer)
- `src/notice_boards/` - Notice board document processing (validators, storage, parsers, scrapers)
- `scripts/` - CLI tools and SQL migrations

**File types:**
- `*_ST_UKSH.xml.zip` - State-level data (regions, districts)
- `*_OB_*_UKSH.xml.zip` - Municipality-level data (addresses, buildings, parcels)

## Key Dependencies

- `ogr2ogr` (GDAL) - required for VFR import, must be installed separately (`brew install gdal`)
- `psycopg2-binary` - PostgreSQL connection
- `httpx` - HTTP client for downloads

## Database

Default connection: `localhost:5432/ruian` (user: ruian, password: ruian)

Configure via environment variables: `RUIAN_DB_HOST`, `RUIAN_DB_PORT`, `RUIAN_DB_NAME`, `RUIAN_DB_USER`, `RUIAN_DB_PASSWORD`

Coordinate system: S-JTSK / Krovak East North (EPSG:5514)

## Web Map

Interactive map viewer using MapLibre GL JS and Martin tile server.

```bash
# Start Martin tile server
podman run -d --name martin -p 3000:3000 \
  -v ./martin/martin.yaml:/config.yaml:ro \
  ghcr.io/maplibre/martin --config /config.yaml

# Serve frontend (development)
cd web && python3 -m http.server 8080

# Check health
curl http://localhost:3000/health

# List sources
curl http://localhost:3000/catalog
```

**RUIAN base layers:** `adresnimista`, `stavebniobjekty`, `parcely`, `ulice`, `obce`, `okresy`

**Document reference layers (function sources):** `parcels_with_documents`, `addresses_with_documents`, `streets_with_documents`, `buildings_with_documents`

### Spatial Index Best Practices

**IMPORTANT:** When writing PostGIS tile functions, always transform the tile envelope instead of the geometry column to enable spatial index usage:

```sql
-- ❌ WRONG: Bypasses GIST index (transforms ALL geometries)
WHERE ST_Transform(p.geom, 3857) && ST_TileEnvelope(z, x, y)

-- ✅ CORRECT: Uses GIST index (transforms only tile bbox)
WHERE p.geom && ST_Transform(ST_TileEnvelope(z, x, y), 5514)
```

## Notice Board Documents

System for downloading documents from official notice boards, parsing references to parcels/addresses/streets and displaying them on a map.

**Key classes:**
- `RuianValidator` (`src/notice_boards/validators.py`) - Validate parcel/address/street/building references against RUIAN
- `StorageBackend` (`src/notice_boards/storage.py`) - Abstract interface for storing attachments (FilesystemStorage implementation)
- `TextExtractor` (`src/notice_boards/parsers/base.py`) - Extract text from PDFs (PdfTextExtractor, PdfPlumberExtractor)

**Database tables:** `notice_boards`, `documents`, `attachments`, `parcel_refs`, `address_refs`, `street_refs`, `building_refs`, `lv_refs`

## Production Deployment

Automated deployment using Ansible. See **[ansible/README.md](ansible/README.md)** for full documentation.

```bash
cd ansible

# Full deployment
ansible-playbook playbooks/site.yml --vault-password-file .vault_pass

# Deploy specific components
ansible-playbook playbooks/site.yml --vault-password-file .vault_pass --tags nginx
ansible-playbook playbooks/site.yml --vault-password-file .vault_pass --tags postgresql,martin
```

**Stack:** PostgreSQL/PostGIS, Martin tile server, Nginx (with tile caching), Certbot (Let's Encrypt SSL)
