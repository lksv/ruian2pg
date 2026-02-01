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
PDF Documents ──► TextExtractor ──► Text ──► LLM (future) ──► References ──► Validator ──► *_refs tables
       │               │                                           │               │
       │               ├── PdfTextExtractor (PyMuPDF)              │               └── RuianValidator
       │               └── PdfPlumberExtractor                     │                   validates against
       │                                                           │                   RUIAN tables
       └── StorageBackend.save()                                   │
           (FilesystemStorage)                                     └── parcel_refs, address_refs,
                                                                       street_refs, building_refs
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
┌──────────────────┐       ┌─────────────────┐       ┌────────────────┐
│  notice_boards   │       │    documents    │       │  attachments   │
├──────────────────┤       ├─────────────────┤       ├────────────────┤
│ id (PK)          │◄──┐   │ id (PK)         │◄──┐   │ id (PK)        │
│ municipality_code│   │   │ notice_board_id │───┘   │ document_id    │───┐
│ name             │   │   │ document_type_id│       │ filename       │   │
│ ico              │   │   │ title           │       │ storage_path   │   │
│ source_url       │   │   │ published_at    │       │ extracted_text │   │
│ edesky_url       │   │   │ parse_status    │       │ parse_status   │   │
│ ofn_json_url     │   │   └─────────────────┘       └────────────────┘   │
│ board_type       │   │                                    │             │
│ data_box_id      │   │   ┌─────────────────┐              │             │
└──────────────────┘   │   │ document_types  │              │             │
                       │   ├─────────────────┤              │             │
┌──────────────────┐   │   │ id (PK)         │              │             │
│    ref_types     │   │   │ code            │              │             │
├──────────────────┤   │   │ name            │              │             │
│ id (PK)          │   │   │ category        │              │             │
│ code             │   │   └─────────────────┘              │             │
│ name             │   │                                    │             │
└──────────────────┘   │                                    │             │
        │              │                                    │             │
        │              │   ┌──────────────────────────────────────────────┘
        │              │   │
        ▼              │   ▼
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
)

# Example
doc = Document(
    notice_board_id=1,
    title="Rozhodnutí o povolení stavby",
    published_at=date(2024, 1, 15),
    parse_status="pending"
)
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

Extract text from PDF documents.

```python
from notice_boards.parsers.pdf import PdfTextExtractor, PdfPlumberExtractor
from notice_boards.parsers.base import CompositeTextExtractor

# Single extractor
extractor = PdfTextExtractor()  # Uses PyMuPDF
if extractor.supports("application/pdf"):
    text = extractor.extract(pdf_bytes, "application/pdf")

# Alternative extractor (better for tables)
extractor = PdfPlumberExtractor()
text = extractor.extract(pdf_bytes, "application/pdf")

# Composite (tries multiple extractors)
composite = CompositeTextExtractor()
composite.register(PdfTextExtractor())
composite.register(PdfPlumberExtractor())
text = composite.extract(content, mime_type)
```

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
│       ├── models.py           # Dataclasses (NoticeBoard, Document, ...)
│       ├── storage.py          # StorageBackend, FilesystemStorage
│       ├── validators.py       # RuianValidator
│       ├── parsers/
│       │   ├── base.py         # TextExtractor ABC
│       │   ├── pdf.py          # PdfTextExtractor, PdfPlumberExtractor
│       │   └── references.py   # Reference dataclasses (stub)
│       └── scrapers/
│           └── base.py         # NoticeBoardScraper ABC (stub)
│
├── scripts/
│   ├── download_ruian.py       # CLI: download VFR files
│   ├── import_ruian.py         # CLI: import to PostGIS
│   ├── fetch_notice_boards.py  # CLI: fetch notice board list
│   ├── import_notice_boards.py # CLI: import notice boards to DB
│   ├── generate_test_references.py  # Generate test data
│   ├── setup_notice_boards_db.sql   # Initial schema
│   ├── migrate_notice_boards_v2.sql # Migration: nutslau, coat_of_arms
│   ├── migrate_notice_boards_v3.sql # Migration: building_refs
│   ├── migrate_notice_boards_v4.sql # Migration: optimize tile functions
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
