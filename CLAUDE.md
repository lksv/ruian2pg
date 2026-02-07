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
psql -U ruian -d ruian -f scripts/migrate_notice_boards_v7.sql
psql -U ruian -d ruian -f scripts/migrate_notice_boards_v8.sql
psql -U ruian -d ruian -f scripts/migrate_notice_boards_v9.sql

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

### Attachment Download

Download attachment files for documents that have only metadata (orig_url but no content).

**Download Status Lifecycle:**
- `pending` - awaiting download (default)
- `downloaded` - content successfully downloaded
- `failed` - download failed (can be retried)
- `removed` - marked as not to be downloaded (terminal)

```bash
# Show statistics (total, pending, downloaded, failed, removed)
uv run python scripts/download_attachments.py --stats

# Download all pending attachments
uv run python scripts/download_attachments.py --all

# Download for specific board
uv run python scripts/download_attachments.py --board-id 123

# Download with limit
uv run python scripts/download_attachments.py --all --limit 100

# Preview without downloading (dry-run)
uv run python scripts/download_attachments.py --all --dry-run --verbose

# Skip SSL verification for problematic servers
uv run python scripts/download_attachments.py --all --skip-ssl-verify

# Filter by document publication date
uv run python scripts/download_attachments.py --all --published-after 2024-01-01
uv run python scripts/download_attachments.py --all --published-before 2024-12-31

# Mark old attachments as removed (won't be downloaded)
uv run python scripts/download_attachments.py --mark-removed --published-before 2020-01-01

# Reset failed attachments to pending for retry
uv run python scripts/download_attachments.py --reset-failed

# List pending attachments
uv run python scripts/download_attachments.py --list-pending --limit 50
```

**Library usage:**
```python
from notice_boards.services import AttachmentDownloader, DownloadConfig
from notice_boards.config import get_db_connection
from datetime import date
from pathlib import Path

# Basic usage
config = DownloadConfig(max_size_bytes=50 * 1024 * 1024)
downloader = AttachmentDownloader(
    conn=get_db_connection(),
    storage_path=Path("data/attachments"),
    config=config,
)

# Download all pending
stats = downloader.download_all()
print(f"Downloaded: {stats.downloaded}, Failed: {stats.failed}")

# Download for specific board
stats = downloader.download_by_board(board_id=123)

# With date filters
config = DownloadConfig(
    published_after=date(2024, 1, 1),
    published_before=date(2024, 12, 31),
)
downloader = AttachmentDownloader(conn, storage_path, config)
stats = downloader.download_all()

# Mark attachments as removed
count = downloader.mark_removed([1, 2, 3])
count = downloader.mark_removed_by_date(date(2020, 1, 1))

# Reset failed to pending
count = downloader.reset_to_pending(failed_only=True)

# Get status counts
counts = downloader.get_status_counts()
# {'pending': 100, 'downloaded': 500, 'failed': 10, 'removed': 50}

# Get attachment content (unified API for TextExtractionService)
content = downloader.get_attachment_content(attachment_id=123, persist=True)
# - Loads from storage if available
# - Downloads from orig_url if not stored
# - persist=True saves to storage after download
```

### Text Extraction

Extract text from document attachments using Docling (with OCR support) or fallback extractors (PyMuPDF, pdfplumber).

**Parse Status Lifecycle:**
- `pending` - awaiting extraction (default)
- `parsing` - extraction in progress
- `completed` - text successfully extracted
- `failed` - extraction failed (can be retried)
- `skipped` - intentionally skipped (unsupported type)

```bash
# Show statistics
uv run python scripts/extract_text.py --stats

# Show statistics by MIME type
uv run python scripts/extract_text.py --stats-by-mime

# Extract from stored files only (recommended)
uv run python scripts/extract_text.py --all --only-downloaded

# Streaming mode (download and extract without persisting)
uv run python scripts/extract_text.py --all

# Stream + persist file after extraction
uv run python scripts/extract_text.py --all --persist

# Extract for specific board
uv run python scripts/extract_text.py --board-id 123

# Single attachment
uv run python scripts/extract_text.py --attachment-id 456

# Date filters
uv run python scripts/extract_text.py --all --published-after 2024-01-01

# Disable OCR (faster)
uv run python scripts/extract_text.py --all --no-ocr

# Force full-page OCR for scanned documents
uv run python scripts/extract_text.py --all --force-ocr

# Use specific OCR backend (default: tesserocr)
# tesserocr - best for Czech (requires tesseract-ocr system package)
# ocrmac - macOS only (uses Apple Vision, no extra deps)
# easyocr - cross-platform (slower, auto-downloads models)
uv run python scripts/extract_text.py --all --ocr-backend ocrmac

# Dry run (list pending without extracting)
uv run python scripts/extract_text.py --dry-run --limit 50

# Reset failed to pending
uv run python scripts/extract_text.py --reset-failed

# Reset failed and skipped
uv run python scripts/extract_text.py --reset-all

# Store extracted text in compressed SQLite (instead of PostgreSQL)
uv run python scripts/extract_text.py --all --text-storage-path data/texts

# Migrate existing texts from PostgreSQL to SQLite
uv run python scripts/migrate_texts_to_sqlite.py --dry-run
uv run python scripts/migrate_texts_to_sqlite.py --limit 1000
uv run python scripts/migrate_texts_to_sqlite.py
```

**Library usage:**
```python
from notice_boards.services import TextExtractionService, AttachmentDownloader
from notice_boards.services.text_extractor import ExtractionConfig
from notice_boards.config import get_db_connection
from pathlib import Path

conn = get_db_connection()
downloader = AttachmentDownloader(conn, Path("data/attachments"))

# Configure extraction
config = ExtractionConfig(
    use_ocr=True,
    ocr_backend="tesserocr",  # or "ocrmac" (macOS), "easyocr"
    force_full_page_ocr=False,
    output_format="markdown",  # or "text", "html"
    max_file_size_bytes=100 * 1024 * 1024,  # 100 MB
)

service = TextExtractionService(conn, downloader, config)

# With compressed SQLite storage (instead of PG extracted_text column)
from notice_boards.services import SqliteTextStorage
sqlite_storage = SqliteTextStorage(Path("data/texts"))
service = TextExtractionService(conn, downloader, config, sqlite_storage=sqlite_storage)

# Get statistics
stats = service.get_stats()
print(f"Pending: {stats['pending']}, Completed: {stats['completed']}")

# Extract single attachment
result = service.extract_text(attachment_id=123, persist_attachment=True)
if result.success:
    print(f"Extracted {result.text_length} chars")

# Batch extraction with progress callback
def on_progress(result):
    status = "OK" if result.success else f"FAIL: {result.error}"
    print(f"  {result.attachment_id}: {status}")

stats = service.extract_batch(
    only_downloaded=True,  # Only from stored files
    limit=100,
    on_progress=on_progress,
)
print(f"Extracted: {stats.extracted}, Failed: {stats.failed}")

# Status management
service.reset_to_pending(failed_only=True)  # Reset failed
service.reset_to_pending(failed_only=False)  # Reset failed + skipped
```

**Note:** Docling is installed as a main dependency. For OCR on Linux, install system packages:
```bash
# Ubuntu/Debian
sudo apt install tesseract-ocr tesseract-ocr-ces libtesseract-dev

# macOS (use ocrmac backend instead - no extra deps needed)
uv run python scripts/extract_text.py --all --ocr-backend ocrmac
```

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

### Automated OFN Sync

OFN document metadata is downloaded automatically every 4 hours via systemd timer (`ruian-ofn-sync.timer`). This covers ~197 boards with OFN feeds.

```bash
# Check timer status
ssh lukas@46.224.67.103 systemctl status ruian-ofn-sync.timer

# View logs
ssh lukas@46.224.67.103 journalctl -u ruian-ofn-sync.service --since "1 day ago"
```

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
- `zstandard` - zstd compression for SQLite text storage

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
- `SqliteTextStorage` (`src/notice_boards/services/sqlite_text_storage.py`) - compressed text storage in SQLite files with zstd dictionary compression

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
