# Architecture Documentation

This document provides detailed architectural information about the RUIAN Import project.

## System Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              Web Browser                                    │
│                         (MapLibre GL JS)                                    │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ HTTP (vector tiles)
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                              Nginx                                          │
│                    (Reverse Proxy + Tile Cache)                             │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          Martin Tile Server                                 │
│                      (Vector Tile Generation)                               │
│                                                                             │
│  Table Sources:          Function Sources:                                  │
│  - adresnimista          - parcels_with_documents()                         │
│  - stavebniobjekty       - addresses_with_documents()                       │
│  - parcely               - streets_with_documents()                         │
│  - ulice                 - buildings_with_documents()                       │
│  - obce, okresy...                                                          │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ PostgreSQL Protocol
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                      PostgreSQL + PostGIS                                   │
│                                                                             │
│  RUIAN Tables:                    Notice Board Tables:                      │
│  ┌─────────────────────┐          ┌──────────────────────┐                  │
│  │ parcely (25M rows)  │          │ notice_boards        │                  │
│  │ stavebniobjekty     │◄─────────┤ documents            │                  │
│  │ adresnimista        │  refs    │ attachments          │                  │
│  │ ulice               │          │ parcel_refs          │                  │
│  │ obce, okresy...     │          │ address_refs, etc.   │                  │
│  └─────────────────────┘          └──────────────────────┘                  │
└─────────────────────────────────────────────────────────────────────────────┘
                                    ▲
                                    │
        ┌───────────────────────────┼───────────────────────────┐
        │                           │                           │
        │                           │                           │
┌───────┴───────┐          ┌────────┴────────┐         ┌────────┴────────┐
│ RuianDownloader│          │  RuianImporter  │         │  RuianValidator │
│               │          │                 │         │                 │
│ CUZK API ────►│ VFR files│ ogr2ogr ───────►│ PostGIS │◄──── validate() │
└───────────────┘          └─────────────────┘         └─────────────────┘
```

## Stack Components

| Component | Technology | Purpose |
|-----------|------------|---------|
| **Database** | PostgreSQL 18 + PostGIS 3.6 | Spatial data storage |
| **Tile Server** | Martin | Vector tile generation from PostGIS |
| **Web Server** | Nginx | Reverse proxy, SSL termination, tile caching |
| **Frontend** | MapLibre GL JS | Interactive map rendering |
| **SSL** | Certbot (Let's Encrypt) | Automatic certificate management |
| **Container Runtime** | Docker (prod) / Podman (dev) | Service isolation |
| **Deployment** | Ansible | Infrastructure automation |

## Data Flow

### RUIAN Import Pipeline

```
CUZK API ──► RuianDownloader ──► data/*.xml.zip ──► RuianImporter ──► PostGIS
   │              │                    │                  │              │
   │              │                    │                  │              │
   └─ VFR file   └─ httpx download    └─ ZIP archive    └─ ogr2ogr     └─ EPSG:5514
      listing       with progress         storage          subprocess      coordinate
                                                                           system
```

**File Types:**
- `*_ST_UKSH.xml.zip` - State structure (regions, districts, ORP, POU)
- `*_OB_*_UKSH.xml.zip` - Municipality data (addresses, buildings, parcels, streets)

### Notice Board Document Pipeline

```
Notice Board APIs ──► fetch_notice_boards.py ──► JSON ──► import_notice_boards.py ──► DB
       │                                                                               │
       ├── Česko.Digital API                                                           │
       └── NKOD OFN GraphQL                                                            │
                                                                                       ▼
┌──────────────────────────────────────────────────────────────────────────────────────────┐
│                              Attachment Processing Pipeline                               │
├──────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                          │
│  Documents ──► AttachmentDownloader ──► StorageBackend ──► TextExtractionService         │
│      │              │                       │                    │                       │
│      │              │                       │                    │                       │
│      │         download_status:             │              parse_status:                 │
│      │         pending → downloaded         │              pending → completed           │
│      │         pending → failed             │                    │                       │
│      │         pending → removed            │                    ▼                       │
│      │              │                       │              extracted_text                │
│      │              ▼                       │                    │                       │
│      │         orig_url ──────────────► storage_path             │                       │
│      │                                      │                    │                       │
│      └──────────────────────────────────────┴────────────────────┘                       │
│                                                                                          │
└──────────────────────────────────────────────────────────────────────────────────────────┘
                                             │
                                             ▼
PDF Documents ──► TextExtractor ──► Text ──► LLM (future) ──► References ──► Validator ──► *_refs tables
       │               │                                           │               │
       │               ├── PdfTextExtractor (PyMuPDF)              │               └── RuianValidator
       │               └── PdfPlumberExtractor                     │                   validates against
       │                                                           │                   RUIAN tables
       └── StorageBackend.save()                                   │
           (FilesystemStorage)                                     └── parcel_refs, address_refs,
                                                                       street_refs, building_refs
```

### Attachment Download Status Lifecycle

Attachments have an explicit download lifecycle managed by `download_status` column:

```
                     ┌─────────────────┐
                     │     pending     │ (default state)
                     │   has orig_url  │
                     └────────┬────────┘
                              │
            ┌─────────────────┼─────────────────┐
            │                 │                 │
            │ download()      │ mark_removed()  │
            │ success         │                 │
            ▼                 │                 ▼
   ┌─────────────────┐        │        ┌─────────────────┐
   │   downloaded    │        │        │     removed     │ (terminal)
   │ has storage_path│        │        │  won't download │
   └─────────────────┘        │        └─────────────────┘
                              │                 ▲
                              │                 │
                    download()│                 │ give up
                    failed    │                 │
                              ▼                 │
                     ┌─────────────────┐        │
                     │     failed      │────────┘
                     │   can retry     │
                     └────────┬────────┘
                              │
                              │ reset_to_pending()
                              ▼
                     ┌─────────────────┐
                     │     pending     │
                     └─────────────────┘
```

**States:**
| Status | Description | Next States |
|--------|-------------|-------------|
| `pending` | Awaiting download, has `orig_url` | `downloaded`, `failed`, `removed` |
| `downloaded` | Content saved to `storage_path` | (terminal) |
| `failed` | Download error, can be retried | `pending`, `removed` |
| `removed` | Marked to skip (e.g., too old) | (terminal) |

**Workflow Options:**

1. **Download first, extract later** (persistent storage)
   ```
   download_status: pending → downloaded
   parse_status:             pending → completed
   storage_path:             (saved)
   ```

2. **Stream extraction** (no persistence, saves disk space)
   ```
   download_status: pending (unchanged)
   parse_status:             pending → completed
   storage_path:             (empty)
   extracted_text:           (saved)
   ```

3. **Download, extract, cleanup** (temporary storage)
   ```
   download_status: pending → downloaded → removed
   parse_status:             pending → completed
   storage_path:             (saved) → (deleted)
   ```

## Database Schema

### RUIAN Tables (imported via ogr2ogr)

Tables created automatically by ogr2ogr from VFR files:

| Table | Description | Key Columns | Geometry |
|-------|-------------|-------------|----------|
| `parcely` | Land parcels (~25M rows) | `id`, `kmenovecislo`, `pododdelenicisla`, `katastralniuzemikod` | `originalnihranice` (POLYGON) |
| `stavebniobjekty` | Buildings (~3.5M rows) | `kod`, `cislodomovni[]`, `castobcekod` | `originalnihranice` (MULTIPOLYGON) |
| `adresnimista` | Address points (~3M rows) | `kod`, `cislodomovni`, `cisloorientacni`, `ulicekod`, `obeckod` | `geom` (POINT) |
| `ulice` | Streets | `kod`, `nazev`, `obeckod` | `geom` (MULTILINESTRING) |
| `obce` | Municipalities (~6.3K rows) | `kod`, `nazev`, `okreskod` | `originalnihranice` (MULTIPOLYGON) |
| `katastralniuzemi` | Cadastral areas (~13K rows) | `kod`, `nazev`, `obeckod` | `originalnihranice` (MULTIPOLYGON) |
| `castiobci` | Parts of municipalities | `kod`, `nazev`, `obeckod` | `geom` (POINT) |
| `okresy` | Districts | `kod`, `nazev`, `vusckod` | `generalizovanehranice` (MULTIPOLYGON) |
| `vusc` | Regions (kraje) | `kod`, `nazev` | `generalizovanehranice` (MULTIPOLYGON) |
| `orp` | Extended powers municipalities | `kod`, `nazev`, `vusckod` | `generalizovanehranice` (MULTIPOLYGON) |
| `pou` | Authorized office municipalities | `kod`, `nazev`, `orpkod` | `generalizovanehranice` (MULTIPOLYGON) |

### Notice Board Tables

```
┌──────────────────┐       ┌─────────────────┐       ┌──────────────────┐
│  notice_boards   │       │    documents    │       │   attachments    │
├──────────────────┤       ├─────────────────┤       ├──────────────────┤
│ id (PK)          │◄──┐   │ id (PK)         │◄──┐   │ id (PK)          │
│ municipality_code│   │   │ notice_board_id │───┘   │ document_id      │───┐
│ name             │   │   │ document_type_id│       │ filename         │   │
│ ico              │   │   │ title           │       │ orig_url         │   │
│ source_url       │   │   │ published_at    │       │ storage_path     │   │
│ edesky_url       │   │   │ parse_status    │       │ download_status* │   │
│ ofn_json_url     │   │   └─────────────────┘       │ parse_status     │   │
│ board_type       │   │                             │ extracted_text   │   │
│ data_box_id      │   │   ┌─────────────────┐       └──────────────────┘   │
└──────────────────┘   │   │ document_types  │              │               │
                       │   ├─────────────────┤              │               │
┌──────────────────┐   │   │ id (PK)         │              │               │
│    ref_types     │   │   │ code            │              │               │
├──────────────────┤   │   │ name            │              │               │
│ id (PK)          │   │   │ category        │              │               │
│ code             │   │   └─────────────────┘              │               │
│ name             │   │                                    │               │
└──────────────────┘   │                                    │               │
        │              │                                    │               │
        │              │   ┌────────────────────────────────┘               │
        │              │   │                                                │
        ▼              │   ▼                                                │
┌──────────────────────┴───────────────────────────────────────────────────┐
│                        Reference Tables                                   │
├──────────────────┬──────────────────┬──────────────────┬─────────────────┤
│   parcel_refs    │   address_refs   │   street_refs    │  building_refs  │
├──────────────────┼──────────────────┼──────────────────┼─────────────────┤
│ attachment_id    │ attachment_id    │ attachment_id    │ attachment_id   │
│ ref_type_id      │ ref_type_id      │ ref_type_id      │ ref_type_id     │
│ parcel_id ──────►│ address_point_   │ street_code ────►│ building_code ─►│
│ (parcely.id)     │ code ──────────► │ (ulice.kod)      │ (stavebniobjekty│
│                  │ (adresnimista.   │                  │  .kod)          │
│ cadastral_area_  │  kod)            │ municipality_    │                 │
│ code             │                  │ name             │ municipality_   │
│ parcel_number    │ street_name      │ street_name      │ name            │
│ parcel_sub_number│ house_number     │ raw_text         │ house_number    │
│ confidence       │ confidence       │ confidence       │ confidence      │
└──────────────────┴──────────────────┴──────────────────┴─────────────────┘
                              │
                              ▼
                     ┌──────────────────┐
                     │     lv_refs      │
                     ├──────────────────┤
                     │ attachment_id    │
                     │ ref_type_id      │
                     │ cadastral_area_  │
                     │ code             │
                     │ lv_number        │
                     │ confidence       │
                     └──────────────────┘
```

**`*download_status` values** (migration v7):
- `pending` - awaiting download (default)
- `downloaded` - content saved to storage_path
- `failed` - download failed (can retry)
- `removed` - marked to skip (terminal)

### Martin Function Sources

PostgreSQL functions that generate vector tiles for document references:

| Function | Joins | Returns |
|----------|-------|---------|
| `parcels_with_documents(z,x,y)` | `parcely` ⟷ `parcel_refs` ⟷ `attachments` ⟷ `documents` | Parcels with document info |
| `addresses_with_documents(z,x,y)` | `adresnimista` ⟷ `address_refs` ⟷ ... | Addresses with document info |
| `streets_with_documents(z,x,y)` | `ulice` ⟷ `street_refs` ⟷ ... | Streets with document info |
| `buildings_with_documents(z,x,y)` | `stavebniobjekty` ⟷ `building_refs` ⟷ ... | Buildings with document info |

## Python Classes

### Core RUIAN Module (`src/ruian_import/`)

#### RuianDownloader

Downloads VFR files from CUZK (Czech Office for Surveying, Mapping and Cadastre).

```python
from ruian_import.downloader import RuianDownloader
from ruian_import.config import DownloadConfig

downloader = RuianDownloader(DownloadConfig())

# List available files
urls = downloader.fetch_file_list()        # ST files
urls = downloader.fetch_ob_file_list()     # OB (municipality) files

# Download
path = downloader.download_latest()
paths, failed = downloader.download_all_municipalities(workers=10)
```

#### RuianImporter

Imports VFR files to PostGIS using ogr2ogr subprocess.

```python
from ruian_import.importer import RuianImporter
from ruian_import.config import DatabaseConfig

importer = RuianImporter(DatabaseConfig())

# Check connection
if importer.check_database_connection():
    importer.ensure_extensions()

# Import
importer.import_latest()                              # Latest ST file
importer.import_all_municipalities(resume=True)       # All OB files with resume

# Verify
stats = importer.get_table_stats()
importer.verify_import()
```

### Notice Board Module (`src/notice_boards/`)

#### Data Models (`models.py`)

Pure dataclasses representing database entities (no ORM):

```python
from notice_boards.models import (
    NoticeBoard,      # Municipality notice board source
    Document,         # Document from notice board
    Attachment,       # PDF/image attachment
    DocumentType,     # Document classification
    RefType,          # Reference type (subject, affected, neighbor, etc.)
    ParcelRef,        # Extracted parcel reference
    AddressRef,       # Extracted address reference
    StreetRef,        # Extracted street reference
    LvRef,            # Extracted ownership sheet reference
    DownloadStatus,   # Constants for attachment download lifecycle
    ParseStatus,      # Constants for text extraction lifecycle
)

# Example: Document
doc = Document(
    notice_board_id=1,
    title="Rozhodnutí o povolení stavby",
    published_at=date(2024, 1, 15),
    parse_status="pending"
)

# Example: Attachment with download_status
att = Attachment(
    document_id=1,
    filename="rozhodnuti.pdf",
    orig_url="https://example.com/doc.pdf",
    download_status=DownloadStatus.PENDING,  # 'pending', 'downloaded', 'failed', 'removed'
)

# DownloadStatus constants
DownloadStatus.PENDING     # 'pending' - awaiting download
DownloadStatus.DOWNLOADED  # 'downloaded' - content saved
DownloadStatus.FAILED      # 'failed' - can retry
DownloadStatus.REMOVED     # 'removed' - skip (terminal)
DownloadStatus.ALL         # ('pending', 'downloaded', 'failed', 'removed')
DownloadStatus.TERMINAL    # ('downloaded', 'removed')

# ParseStatus constants (text extraction lifecycle)
ParseStatus.PENDING    # 'pending' - awaiting extraction
ParseStatus.PARSING    # 'parsing' - extraction in progress
ParseStatus.COMPLETED  # 'completed' - text extracted
ParseStatus.FAILED     # 'failed' - can retry
ParseStatus.SKIPPED    # 'skipped' - unsupported type (terminal)
ParseStatus.ALL        # All valid statuses
ParseStatus.TERMINAL   # ('completed', 'skipped')
```

#### RuianValidator (`validators.py`)

Validates extracted references against RUIAN database.

```python
from notice_boards.validators import RuianValidator
from notice_boards.config import get_db_connection

validator = RuianValidator(get_db_connection())

# Validate parcel
result = validator.validate_parcel(
    cadastral_area_name="Veveří",  # or cadastral_area_code=610372
    parcel_number=592,
    parcel_sub_number=2            # for "592/2"
)
if result.is_valid:
    print(f"Parcel ID: {result.parcel_id}")
    print(f"Cadastral area: {result.cadastral_area_name}")

# Validate address
result = validator.validate_address(
    municipality_name="Brno",
    street_name="Kounicova",
    house_number=67,
    orientation_number=None        # optional
)
if result.is_valid:
    print(f"Address code: {result.address_point_code}")

# Validate street
result = validator.validate_street(
    municipality_name="Brno",
    street_name="Kounicova"
)

# Validate building
result = validator.validate_building(
    municipality_name="Brno",
    part_of_municipality_name="Veveří",
    house_number=67
)

# Lookup utilities
code, name = validator.find_cadastral_area(name="Veveří")
code, name = validator.find_municipality(code=582786)
```

#### StorageBackend (`storage.py`)

Abstract storage for document attachments with filesystem implementation.

```python
from pathlib import Path
from notice_boards.storage import FilesystemStorage, StorageError

storage = FilesystemStorage(Path("data/attachments"))

# Save attachment
content = open("document.pdf", "rb").read()
storage.save("2024/01/doc123/file.pdf", content)

# Load attachment
content = storage.load("2024/01/doc123/file.pdf")

# Check existence
if storage.exists("2024/01/doc123/file.pdf"):
    storage.delete("2024/01/doc123/file.pdf")

# Compute hash for deduplication
hash = storage.compute_hash(content)  # SHA-256
```

#### TextExtractor (`parsers/`)

Extract text from documents (PDF, Office, images with OCR).

```python
from notice_boards.parsers import create_default_extractor
from notice_boards.parsers.docling_extractor import DoclingExtractor, DoclingConfig

# Recommended: Use factory function with fallback chain
# Docling (if available) → PyMuPDF → pdfplumber
extractor = create_default_extractor(
    use_ocr=True,
    ocr_backend="tesserocr",  # or "ocrmac" (macOS), "easyocr"
)
text = extractor.extract(pdf_bytes, "application/pdf")

# Direct Docling usage (best quality, OCR support)
config = DoclingConfig(
    use_ocr=True,
    ocr_backend="tesserocr",
    ocr_languages=["cs-CZ", "en-US"],
    output_format="markdown",
)
docling = DoclingExtractor(config)
if docling.supports("application/pdf"):
    text = docling.extract(pdf_bytes, "application/pdf")

# Fallback extractors (no OCR)
from notice_boards.parsers.pdf import PdfTextExtractor, PdfPlumberExtractor

extractor = PdfTextExtractor()   # Fast, text-layer only
extractor = PdfPlumberExtractor()  # Better for tables
```

#### eDesky Integration (`scrapers/edesky.py`)

Clients for fetching notice board metadata and documents from eDesky.cz.

```python
from notice_boards.scrapers.edesky import (
    EdeskyApiClient,    # API client for /api/v1/dashboards
    EdeskyXmlClient,    # XML client for /desky/{id}.xml
    EdeskyScraper,      # Document scraper
    EdeskyDashboard,    # Notice board metadata
    EdeskyDocument,     # Document with attachments
)
from notice_boards.scraper_config import EdeskyConfig

# API client for notice board metadata (requires API key)
config = EdeskyConfig()  # Uses EDESKY_API_KEY env var
with EdeskyApiClient(config) as client:
    # Fetch all boards from a region with subordinates
    dashboards = client.get_dashboards(edesky_id=112, include_subordinated=True)

    # Fetch ALL boards (hybrid: hierarchical + flat API to catch standalone entities)
    all_boards = client.get_all_dashboards()

    for board in dashboards:
        print(f"{board.name} (ID: {board.edesky_id})")
        print(f"  Region: {board.nuts3_name}, District: {board.nuts4_name}")

# XML client for documents (no API key needed)
with EdeskyXmlClient() as client:
    documents = client.get_documents(edesky_id=62)
    for doc in documents:
        print(f"{doc.name}: {len(doc.attachments)} attachments")

    # Download extracted text
    text = client.get_document_text(doc.edesky_url)
```

#### OFN Integration (`scrapers/ofn.py`)

Client and scraper for OFN (Open Formal Norm) JSON-LD feeds.

```python
from notice_boards.scrapers.ofn import (
    OfnClient,       # HTTP client for OFN feeds
    OfnScraper,      # Document scraper
    OfnDocument,     # Document with attachments
    OfnAttachment,   # Attachment metadata
    OfnBoard,        # Feed metadata
)
from notice_boards.scraper_config import OfnConfig

# Direct client usage
config = OfnConfig()
with OfnClient(config) as client:
    board = client.fetch_feed("https://edeska.brno.cz/eDeska01/opendata")
    print(f"Found {len(board.documents)} documents")

    for doc in board.documents:
        print(f"{doc.title}: {len(doc.attachments)} attachments")
        print(f"  Published: {doc.published_at}")
        print(f"  Reference: {doc.reference_number}")

# Scraper usage (returns DocumentData for storage)
scraper = OfnScraper(config, download_originals=True)
with scraper:
    documents = scraper.scrape_by_url("https://edeska.brno.cz/eDeska01/opendata")
    for doc in documents:
        print(f"{doc.external_id}: {doc.title}")
```

**OFN JSON-LD fields mapped:**
- `iri` → `external_id` (SHA-256 hash, prefixed with `ofn_`)
- `název.cs` → `title`
- `vyvěšení.datum` → `published_at`
- `relevantní_do.datum` → `valid_until`
- `číslo_jednací` → `metadata.reference_number`
- `spisová_značka` → `metadata.file_reference`
- `agenda[0].název.cs` → `metadata.category`
- `dokument[].url` → `attachments[].url`

#### AttachmentDownloader (`services/attachment_downloader.py`)

Service for downloading attachment content for records that have metadata but no files.
Manages attachment lifecycle through `download_status` states.

```python
from notice_boards.services import AttachmentDownloader, DownloadConfig
from notice_boards.models import DownloadStatus
from notice_boards.config import get_db_connection
from datetime import date
from pathlib import Path

# Create downloader with date filters
config = DownloadConfig(
    max_size_bytes=50 * 1024 * 1024,  # 50 MB
    request_timeout=60,
    skip_ssl_verify=False,
    published_after=date(2024, 1, 1),   # Filter by document date
    published_before=date(2024, 12, 31),
)
downloader = AttachmentDownloader(
    conn=get_db_connection(),
    storage_path=Path("data/attachments"),
    config=config,
)

# Get statistics by download_status
stats = downloader.get_stats()
print(f"Total: {stats['total']}")
print(f"Downloaded: {stats['downloaded']}, Pending: {stats['pending']}")
print(f"Failed: {stats['failed']}, Removed: {stats['removed']}")

# Get status counts
counts = downloader.get_status_counts()
# {'pending': 100, 'downloaded': 500, 'failed': 10, 'removed': 50}

# Get pending attachments (without downloading)
pending = downloader.get_pending_attachments(limit=10)
for att in pending:
    print(f"{att.id}: {att.filename} from {att.orig_url}")

# Download all pending with progress callback
def on_progress(result):
    if result.success:
        print(f"Downloaded: {result.attachment_id} ({result.file_size} bytes)")
    else:
        print(f"Failed: {result.attachment_id} - {result.error}")

with downloader:
    stats = downloader.download_all(on_progress=on_progress)
    print(f"Completed: {stats.downloaded} downloaded, {stats.failed} failed")

# Download for specific board
stats = downloader.download_by_board(board_id=123)

# Mark old attachments as removed (won't be downloaded)
count = downloader.mark_removed_by_date(date(2020, 1, 1))
print(f"Marked {count} attachments as removed")

# Mark specific attachments as removed
count = downloader.mark_removed([1, 2, 3])

# Reset failed attachments to pending for retry
count = downloader.reset_to_pending(failed_only=True)

# Unified content API (used by TextExtractionService)
content = downloader.get_attachment_content(attachment_id=123, persist=True)
# - Loads from storage if available
# - Downloads from orig_url if not stored
# - persist=True saves to storage after download
```

**Key methods:**
- `get_pending_count()` - Count attachments with `download_status='pending'`
- `iter_pending_attachments()` - Iterate over pending attachments
- `download_attachment()` - Download single attachment
- `download_all()` - Download all pending with optional date filters
- `download_by_board()` - Download for specific notice board
- `get_stats()` - Get counts by `download_status`
- `get_stats_by_board()` - Get statistics grouped by board
- `get_status_counts()` - Get counts per status
- `mark_removed()` - Mark attachments as removed (by ID list)
- `mark_removed_by_date()` - Mark as removed by publication date
- `mark_failed()` - Mark single attachment as failed
- `reset_to_pending()` - Reset failed/removed to pending
- `get_attachment_content()` - Unified API for getting content (download or load)
- `get_attachments_by_status()` - Query attachments by any status

#### TextExtractionService (`services/text_extractor.py`)

Service for extracting text from document attachments using Docling (with OCR) or fallback extractors.

```python
from notice_boards.services import TextExtractionService, AttachmentDownloader
from notice_boards.services.text_extractor import ExtractionConfig
from notice_boards.config import get_db_connection
from pathlib import Path

conn = get_db_connection()
downloader = AttachmentDownloader(conn, Path("data/attachments"))

# Configure with OCR
config = ExtractionConfig(
    use_ocr=True,
    ocr_backend="tesserocr",  # or "ocrmac" (macOS), "easyocr"
    output_format="markdown",
)
service = TextExtractionService(conn, downloader, config)

# Extract text (auto-downloads if needed)
result = service.extract_text(attachment_id=123, persist_attachment=False)
if result.success:
    print(f"Extracted {result.text_length} chars")

# Batch extraction
stats = service.extract_batch(
    only_downloaded=True,  # Only from stored files
    limit=100,
)
print(f"Extracted: {stats.extracted}, Failed: {stats.failed}")

# Status management
service.reset_to_pending(failed_only=True)
```

**Key methods:**
- `extract_text()` - Extract text from single attachment
- `extract_batch()` - Process multiple pending attachments
- `mark_parsing/completed/failed/skipped()` - Status transitions
- `reset_to_pending()` - Reset failed/skipped for retry
- `get_stats()` - Get extraction statistics
- `get_stats_by_mime_type()` - Stats grouped by MIME type

**Workflow integration:**

The `TextExtractionService` uses `AttachmentDownloader.get_attachment_content()` which:
1. Checks if file exists in storage → returns from storage
2. If not stored but has `orig_url` → downloads content
3. If `persist=True` → saves to storage, updates DB
4. If `persist=False` → returns content without saving (streaming mode)

#### DocumentRepository (`repository.py`)

Database operations for scraped documents with upsert logic.

```python
from pathlib import Path
from notice_boards.repository import DocumentRepository, create_document_repository
from notice_boards.config import get_db_connection

# Create with storage backends
repo = create_document_repository(
    conn=get_db_connection(),
    attachments_path=Path("data/attachments"),
    text_path=Path("data/documents"),
)

# Upsert document (INSERT or UPDATE on conflict)
doc_id = repo.upsert_document(notice_board_id=1, doc_data=doc_data)

# Upsert attachment with file storage
att_id = repo.upsert_attachment(document_id=doc_id, att_data=att_data)

# Get existing external IDs for incremental updates
existing = repo.get_existing_external_ids(notice_board_id=1)

# Notice board lookups for matching
board = repo.get_notice_board_by_edesky_id(62)
board = repo.get_notice_board_by_edesky_url("https://edesky.cz/desky/62")
boards = repo.get_notice_boards_by_ico("00064581")
boards = repo.get_notice_boards_by_name_and_district("Brno", "Brno-město")

# Update eDesky metadata
repo.update_notice_board_edesky_fields(
    board_id=1,
    edesky_id=62,
    edesky_url="https://edesky.cz/desky/62",
    category="obec",
    nuts3_id=116, nuts3_name="Jihomoravský kraj",
    nuts4_id=3702, nuts4_name="Okres Brno-město",
)

# Statistics
stats = repo.get_notice_board_stats()
print(f"Total: {stats['total']}, With eDesky ID: {stats['with_edesky_id']}")

# Smart name matching (handles prefix variants and city districts)
board = repo.find_notice_board_by_name_district("Brno-Medlánky", district="Brno-město")
```

**Name matching logic** (`find_notice_board_by_name_district`):

The function handles naming differences between data sources:

1. **Prefix variants**: Adds common prefixes used by eDesky
   - `"Lipnice"` → also tries `"Obec Lipnice"`, `"Město Lipnice"`, `"Městys Lipnice"`

2. **City district patterns**: Special handling for statutory cities
   - `"Brno-Medlánky"` → `"MČ Brno - Medlánky"`
   - `"Praha 1"` → `"MČ Praha 1"`, `"Městská část Praha 1"`
   - `"Ostrava-Poruba"` → `"MČ Ostrava - Poruba"`, `"MČ Poruba"`
   - `"Pardubice I"` → `"MČ Pardubice I"`, `"MČ Pardubice I - střed"`

3. **Exact match required**: Returns `None` if 0 or >1 matches (ambiguous)

### Configuration (`config.py`)

Both modules use dataclass-based configuration with environment variable support:

```python
# RUIAN config
from ruian_import.config import DatabaseConfig, DownloadConfig

db = DatabaseConfig()  # RUIAN_DB_HOST, RUIAN_DB_PORT, etc.
print(db.connection_string)

dl = DownloadConfig()  # Download URLs, timeouts, workers

# Notice board config
from notice_boards.config import DatabaseConfig, StorageConfig, get_db_connection

storage = StorageConfig()  # NOTICE_BOARDS_STORAGE_PATH
conn = get_db_connection()  # Returns psycopg2 connection

# eDesky scraper config
from notice_boards.scraper_config import EdeskyConfig, ScraperConfig

edesky = EdeskyConfig()  # EDESKY_API_KEY, EDESKY_BASE_URL, etc.
scraper = ScraperConfig()  # General scraper settings (max_documents, etc.)
```

## Coordinate Systems

| System | EPSG | Usage |
|--------|------|-------|
| S-JTSK / Krovak East North | 5514 | RUIAN native, database storage |
| Web Mercator | 3857 | Vector tiles for web maps |
| WGS84 | 4326 | Bounding boxes in martin.yaml |

**Important:** Martin tile functions transform coordinates. Always transform the tile envelope (1 bbox) instead of geometry column (millions of rows) to use spatial indexes:

```sql
-- ❌ WRONG: Sequential scan
WHERE ST_Transform(p.geom, 3857) && ST_TileEnvelope(z, x, y)

-- ✅ CORRECT: Uses GIST index
WHERE p.geom && ST_Transform(ST_TileEnvelope(z, x, y), 5514)
```

## Directory Structure

```
ruian2pg/
├── src/
│   ├── ruian_import/           # Core RUIAN module
│   │   ├── config.py           # DatabaseConfig, DownloadConfig
│   │   ├── downloader.py       # RuianDownloader
│   │   └── importer.py         # RuianImporter
│   │
│   └── notice_boards/          # Notice board module
│       ├── config.py           # DatabaseConfig, StorageConfig
│       ├── models.py           # Dataclasses (NoticeBoard, Document, DownloadStatus, ParseStatus, ...)
│       ├── storage.py          # StorageBackend, FilesystemStorage
│       ├── validators.py       # RuianValidator
│       ├── repository.py       # DocumentRepository (DB operations)
│       ├── scraper_config.py   # EdeskyConfig, OfnConfig
│       ├── services/
│       │   ├── __init__.py     # Service exports
│       │   ├── attachment_downloader.py  # AttachmentDownloader
│       │   └── text_extractor.py         # TextExtractionService
│       ├── parsers/
│       │   ├── base.py         # TextExtractor ABC
│       │   ├── pdf.py          # PdfTextExtractor, PdfPlumberExtractor
│       │   ├── docling_extractor.py  # DoclingExtractor (OCR support)
│       │   └── references.py   # Reference dataclasses (stub)
│       └── scrapers/
│           ├── base.py         # NoticeBoardScraper ABC
│           ├── edesky.py       # EdeskyApiClient, EdeskyScraper
│           └── ofn.py          # OfnClient, OfnScraper
│
├── scripts/
│   ├── download_ruian.py       # CLI: download VFR files
│   ├── import_ruian.py         # CLI: import to PostGIS
│   ├── fetch_notice_boards.py  # CLI: fetch notice board list
│   ├── import_notice_boards.py # CLI: import notice boards to DB
│   ├── sync_edesky_boards.py   # CLI: sync with eDesky.cz
│   ├── download_ofn_documents.py    # CLI: download OFN documents
│   ├── download_attachments.py      # CLI: download attachment files
│   ├── extract_text.py              # CLI: extract text from attachments
│   ├── generate_test_references.py  # Generate test data
│   ├── setup_notice_boards_db.sql   # Initial schema
│   ├── migrate_notice_boards_v2.sql # Migration: nutslau, coat_of_arms
│   ├── migrate_notice_boards_v3.sql # Migration: building_refs
│   ├── migrate_notice_boards_v4.sql # Migration: optimize tile functions
│   ├── migrate_notice_boards_v5.sql # Migration: eDesky fields
│   ├── migrate_notice_boards_v6.sql # Migration: remove ICO unique
│   ├── migrate_notice_boards_v7.sql # Migration: download_status
│   ├── migrate_notice_boards_v8.sql # Migration: parse_status states
│   └── setup_indexes.sql       # Spatial indexes
│
├── web/
│   └── index.html              # MapLibre GL JS frontend
│
├── martin/
│   └── martin.yaml             # Martin tile server config
│
├── ansible/                    # Deployment automation
│   ├── inventory/
│   ├── playbooks/
│   └── roles/
│
├── tests/                      # pytest tests
└── data/                       # Downloaded VFR files (gitignored)
```
