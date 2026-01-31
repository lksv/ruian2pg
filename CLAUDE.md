# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

RUIAN Import - tool for downloading and importing Czech RUIAN (territorial identification, addresses and real estate registry) data into PostgreSQL/PostGIS.

## Development Workflow

**IMPORTANT: After every code change, run tests to ensure nothing is broken:**

```bash
# Quick validation (run after each change)
uv run pytest tests/ -v

# Full validation before committing
uv run ruff check src/ scripts/ tests/
uv run ruff format src/ scripts/ tests/
uv run mypy src/ruian_import/ scripts/
uv run pytest tests/ -v
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
uv run pytest tests/ -v

# Run tests with coverage
uv run pytest tests/ -v --cov=src/ruian_import

# Run single test file
uv run pytest tests/test_downloader.py -v

# Run single test
uv run pytest tests/test_downloader.py::TestRuianDownloaderPatterns::test_ob_file_pattern -v

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
