# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

RUIAN Import - tool for downloading and importing Czech RUIAN (territorial identification, addresses and real estate registry) data into PostgreSQL/PostGIS.

## Development Workflow

**IMPORTANT: After every code change, run tests to ensure nothing is broken:**

```bash
# Quick validation (run after each change)
uv run python -m pytest tests/ -v

# Full validation before committing
uv run ruff check src/ scripts/ tests/
uv run ruff format src/ scripts/ tests/
uv run mypy src/ruian_import/ scripts/
uv run python -m pytest tests/ -v
```

## Commands

```bash
# Install dependencies
uv sync

# Install with dev dependencies
uv sync --all-extras

# Lint
uv run ruff check src/ scripts/ tests/

# Format
uv run ruff format src/ scripts/ tests/

# Type check
uv run mypy src/ruian_import/ scripts/

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
```

## Architecture

```
src/ruian_import/
├── config.py      # DatabaseConfig, DownloadConfig dataclasses
├── downloader.py  # RuianDownloader - fetches VFR files from CUZK
└── importer.py    # RuianImporter - imports VFR to PostGIS via ogr2ogr

scripts/
├── download_ruian.py  # CLI for downloading
└── import_ruian.py    # CLI for importing

tests/
├── test_config.py     # Tests for configuration
├── test_downloader.py # Tests for downloader
└── test_importer.py   # Tests for importer
```

**Data flow:** CUZK API → `RuianDownloader` → `data/*.xml.zip` → `RuianImporter` (ogr2ogr) → PostGIS

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

### Directory Structure

```
web/
└── index.html          # MapLibre frontend with layer controls

martin/
└── martin.yaml         # Martin tile server configuration

scripts/
└── setup_indexes.sql   # Spatial indexes for tile performance
```

### Start Web Map Services

```bash
# Start Martin tile server
podman run -d --name martin -p 3000:3000 \
  -v ./martin/martin.yaml:/config.yaml:ro \
  ghcr.io/maplibre/martin --config /config.yaml

# Serve frontend (development)
cd web && python3 -m http.server 8080

# Open http://localhost:8080
```

### Martin Commands

```bash
# Check health
curl http://localhost:3000/health

# List sources
curl http://localhost:3000/catalog

# Test tile (Brno area, zoom 10)
curl -o /tmp/tile.pbf http://localhost:3000/obce/10/559/351

# View logs
podman logs martin

# Restart after config change
podman restart martin
```

### Tile Server Configuration

The `martin/martin.yaml` configures which tables and geometry columns to serve:

- `adresnimista` - address points (`geom`)
- `stavebniobjekty` - buildings (`originalnihranice`)
- `parcely` - parcels (`originalnihranice`)
- `ulice` - streets (`geom`)
- `obce` - municipalities (`originalnihranice`)
- `okresy` - districts (`generalizovanehranice`)
