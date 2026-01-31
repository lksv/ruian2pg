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
uv run python -m mypy src/ruian_import/ src/notice_boards/ scripts/
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
```

## Architecture

```
src/ruian_import/
├── config.py      # DatabaseConfig, DownloadConfig dataclasses
├── downloader.py  # RuianDownloader - fetches VFR files from CUZK
└── importer.py    # RuianImporter - imports VFR to PostGIS via ogr2ogr

src/notice_boards/
├── config.py      # DatabaseConfig, StorageConfig, get_db_connection()
├── models.py      # Dataclasses for DB entities
├── storage.py     # StorageBackend ABC, FilesystemStorage
├── validators.py  # RuianValidator - validate parcel/address/street refs
├── parsers/
│   ├── base.py        # TextExtractor ABC
│   ├── pdf.py         # PdfTextExtractor, PdfPlumberExtractor
│   └── references.py  # ParcelRef, AddressRef, StreetRef dataclasses (stubs)
└── scrapers/
    └── base.py        # NoticeBoardScraper ABC (stub for future)

scripts/
├── download_ruian.py         # CLI for downloading RUIAN
├── import_ruian.py           # CLI for importing RUIAN
└── setup_notice_boards_db.sql # DB migration for notice boards

tests/
├── test_config.py      # Tests for RUIAN configuration
├── test_downloader.py  # Tests for RUIAN downloader
├── test_importer.py    # Tests for RUIAN importer
├── test_storage.py     # Tests for notice_boards storage
└── test_validators.py  # Tests for notice_boards validators
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

## Notice Board Documents

System for downloading documents from official notice boards of municipalities, parsing references to parcels/addresses/streets and displaying them on a map.

### Database Schema

```bash
# Apply migration
psql -U ruian -d ruian -f scripts/setup_notice_boards_db.sql
```

Tables created:
- `notice_boards` - Notice board sources (municipalities)
- `document_types` - Document type classification
- `documents` - Downloaded documents
- `attachments` - Document attachments (PDFs, etc.)
- `ref_types` - Reference type classification
- `parcel_refs` - Parcel references extracted from documents
- `address_refs` - Address references extracted from documents
- `street_refs` - Street references extracted from documents
- `lv_refs` - Ownership sheet references

Martin function sources:
- `parcels_with_documents(z, x, y)` - Parcels with document references
- `streets_with_documents(z, x, y)` - Streets with document references
- `addresses_with_documents(z, x, y)` - Addresses with document references

### Key Classes

**RuianValidator** (`src/notice_boards/validators.py`):
- `validate_parcel(cadastral_area_code/name, parcel_number, parcel_sub_number)` - Check if parcel exists in RUIAN
- `validate_address(municipality_code/name, street_code/name, house_number, orientation_number)` - Check if address exists
- `validate_street(municipality_code/name, street_name)` - Check if street exists
- `find_cadastral_area(name/code)` - Lookup cadastral area
- `find_municipality(name/code)` - Lookup municipality

**StorageBackend** (`src/notice_boards/storage.py`):
- Abstract interface for storing attachments
- `FilesystemStorage` - Local filesystem implementation
- Methods: `save()`, `load()`, `exists()`, `delete()`, `get_url()`, `compute_hash()`

**TextExtractor** (`src/notice_boards/parsers/base.py`):
- Abstract interface for extracting text from documents
- `PdfTextExtractor` - Extract text from PDFs with text layer (PyMuPDF)
- `PdfPlumberExtractor` - Alternative PDF extractor (pdfplumber)

### Usage Example

```python
from notice_boards.validators import RuianValidator
from notice_boards.config import get_db_connection
from notice_boards.storage import FilesystemStorage
from pathlib import Path

# Validate parcel
validator = RuianValidator(get_db_connection())
result = validator.validate_parcel(
    cadastral_area_name="Veveří",
    parcel_number=592,
    parcel_sub_number=2
)
if result.is_valid:
    print(f"Found parcel ID: {result.parcel_id}")

# Store attachment
storage = FilesystemStorage(Path("data/attachments"))
storage.save("2024/01/doc123/file.pdf", pdf_bytes)
```

### Implementation Status

- ✅ Database schema (all tables and indexes)
- ✅ StorageBackend + FilesystemStorage
- ✅ RuianValidator (parcel, address, street validation)
- ✅ TextExtractor + PDF extractors
- ✅ Martin function sources for map
- ⏳ Reference extractors (stub - will use LLM)
- ⏳ Scrapers (stub - not implemented yet)
