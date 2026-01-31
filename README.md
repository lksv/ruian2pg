# RUIAN Import to PostGIS

Import Czech RUIAN (Registr územní identifikace, adres a nemovitostí) data to PostgreSQL/PostGIS.

## Features

- Download VFR (Výměnný formát RÚIAN) files from CUZK
- Import to PostGIS using GDAL/ogr2ogr
- Support for original boundaries (not generalized)
- All administrative levels: State, Regions, Districts, Municipalities, etc.
- **Full country import**: Download and import all 6,258 municipalities with detailed data
- **Parallel downloads**: Configurable number of download workers
- **Resume support**: Continue interrupted imports from where they stopped

## Supported Platforms

| Platform | Architecture | Status |
|----------|--------------|--------|
| macOS    | Intel (x86_64) | ✅ Supported |
| macOS    | Apple Silicon (arm64) | ✅ Supported |
| Linux    | amd64 (x86_64) | ✅ Supported |
| Linux    | arm64 (aarch64) | ✅ Supported |

Tested on:
- macOS Sonoma (Intel & Apple Silicon)
- Ubuntu 22.04/24.04 (amd64 & arm64)
- Debian 12 (amd64 & arm64)
- Hetzner Cloud (CAX - Ampere Altra arm64)
- AWS EC2 (Graviton arm64)

## Requirements

- Python 3.11+
- GDAL with VFR support (`ogr2ogr`)
- PostgreSQL with PostGIS extension
- Podman or Docker (optional, for database container)

## Installation

### 1. Install GDAL dependencies

**macOS (Intel & Apple Silicon):**
```bash
brew install gdal
```

**Ubuntu/Debian (amd64 & arm64):**
```bash
sudo apt-get update
sudo apt-get install gdal-bin python3-gdal
```

**Fedora/RHEL/Rocky (amd64 & arm64):**
```bash
sudo dnf install gdal
```

**Verify VFR support:**
```bash
ogrinfo --formats | grep VFK
```

### 2. Install Python package

```bash
# Using uv
uv sync

# Or using pip
pip install -e .
```

### 3. Start PostGIS database

**Using Docker/Podman (all platforms):**
```bash
# Create volume for data persistence
podman volume create ruian_pgdata

# Start PostGIS container
# On Apple Silicon with Podman emulation: use --platform linux/amd64
# On native ARM64/amd64 servers: omit --platform flag
podman run -d \
  --name ruian-postgis \
  -e POSTGRES_USER=ruian \
  -e POSTGRES_PASSWORD=ruian \
  -e POSTGRES_DB=ruian \
  -p 5432:5432 \
  -v ruian_pgdata:/var/lib/postgresql/data:Z \
  docker.io/postgis/postgis:17-3.5

# Initialize extensions
podman exec -it ruian-postgis psql -U ruian -d ruian -c \
  "CREATE EXTENSION IF NOT EXISTS postgis; CREATE EXTENSION IF NOT EXISTS postgis_topology;"
```

**Native PostgreSQL (Linux):**
```bash
# Ubuntu/Debian
sudo apt-get install postgresql-16 postgresql-16-postgis-3

# Create database
sudo -u postgres createuser ruian
sudo -u postgres createdb -O ruian ruian
sudo -u postgres psql -d ruian -c "CREATE EXTENSION IF NOT EXISTS postgis;"
```

## Development

### Running Tests

```bash
# Run all tests
uv run python -m pytest tests/ -v

# Run with coverage report
uv run python -m pytest tests/ -v --cov=src/ruian_import

# Run specific test file
uv run python -m pytest tests/test_downloader.py -v
```

### Code Quality

```bash
# Lint
uv run ruff check src/ scripts/ tests/

# Format
uv run ruff format src/ scripts/ tests/

# Type check
uv run mypy src/ruian_import/ scripts/
```

## Usage

### Download RUIAN data

```bash
# List available files
uv run python scripts/download_ruian.py --list

# Download the latest file
uv run python scripts/download_ruian.py --latest

# Download all available files
uv run python scripts/download_ruian.py --all

# Show local files
uv run python scripts/download_ruian.py --local

# Download all municipalities (OB files) - full country data
uv run python scripts/download_ruian.py --municipalities

# Download with more parallel workers (default: 5)
uv run python scripts/download_ruian.py --municipalities --workers 10

# List available municipality files
uv run python scripts/download_ruian.py --list-municipalities

# Show local municipality files
uv run python scripts/download_ruian.py --local-municipalities
```

### Import to PostGIS

```bash
# Check database connection
uv run python scripts/import_ruian.py --check

# Import the latest file
uv run python scripts/import_ruian.py --latest

# Import all files
uv run python scripts/import_ruian.py --all

# Import specific file
uv run python scripts/import_ruian.py --file data/20251231_ST_UKSH.xml.zip

# Verify import
uv run python scripts/import_ruian.py --verify

# Show table statistics
uv run python scripts/import_ruian.py --stats

# Sample query
uv run python scripts/import_ruian.py --sample obec

# Import all municipality (OB) files - full country data
uv run python scripts/import_ruian.py --municipalities

# Resume interrupted import (skip already imported files)
uv run python scripts/import_ruian.py --municipalities --continue
```

### Database connection options

You can configure database connection via environment variables or command-line arguments:

```bash
# Environment variables
export RUIAN_DB_HOST=localhost
export RUIAN_DB_PORT=5432
export RUIAN_DB_NAME=ruian
export RUIAN_DB_USER=ruian
export RUIAN_DB_PASSWORD=ruian

# Or command-line arguments
uv run python scripts/import_ruian.py --host localhost --port 5432 --dbname ruian --user ruian --password ruian --check
```

## Data Structure

After import, the following tables are created:

| Table | Description | Geometry |
|-------|-------------|----------|
| `stat` | State (Czech Republic) | polygon |
| `regionsoudrznosti` | Cohesion regions | polygon |
| `vusc` | Regions (Kraje) | polygon |
| `okres` | Districts | polygon |
| `orp` | Municipalities with extended powers | polygon |
| `pou` | Municipalities with authorized municipal office | polygon |
| `obec` | Municipalities | polygon |
| `spravniobvod` | Administrative districts | polygon |
| `mop` | City districts/parts | polygon |
| `momc` | City districts/city parts | polygon |
| `castobce` | Parts of municipalities | polygon |
| `katastralniuzemi` | Cadastral areas | polygon |
| `zsj` | Basic settlement units | polygon |
| `ulice` | Streets | linestring |
| `stavebniobjekt` | Building objects | polygon |
| `adresnimisto` | Address points | point |

## Example Queries

```sql
-- Connect to database
podman exec -it ruian-postgis psql -U ruian -d ruian

-- Count addresses (should be ~3 million)
SELECT COUNT(*) FROM adresnimisto;

-- Find municipalities starting with "Prah"
SELECT nazev, kod, ST_AsText(ST_Centroid(geom)) AS centroid
FROM obec
WHERE nazev LIKE 'Prah%';

-- Find all streets in Prague
SELECT u.nazev, o.nazev AS obec
FROM ulice u
JOIN obec o ON ST_Within(u.geom, o.geom)
WHERE o.nazev = 'Praha'
LIMIT 10;

-- Get area of all municipalities in km²
SELECT nazev, ST_Area(geom) / 1000000 AS area_km2
FROM obec
ORDER BY area_km2 DESC
LIMIT 10;
```

## Full Country Import

To import data for all Czech municipalities (detailed addresses, buildings, parcels):

```bash
# 1. Download state-level data (regions, districts)
uv run python scripts/download_ruian.py --latest
uv run python scripts/import_ruian.py --latest

# 2. Download all municipality data (~15-25 GB)
uv run python scripts/download_ruian.py --municipalities --workers 10

# 3. Import all municipality data
uv run python scripts/import_ruian.py --municipalities

# If interrupted, resume from where it stopped:
uv run python scripts/import_ruian.py --municipalities --continue
```

### Disk and Resource Requirements

| Data Set | Downloaded Files | Database Size | Total Disk |
|----------|-----------------|---------------|------------|
| ST (state structure only) | ~50 MB | ~500 MB | ~1 GB |
| Full country (ST + all OB) | ~15-25 GB | ~50-80 GB | **~100 GB** |

**Recommendations for full country import:**
- Minimum: 160 GB disk space
- Recommended: 200 GB disk space (for safety margin)
- 8+ GB RAM for PostgreSQL
- SSD storage strongly recommended

### Expected Table Counts (full import)

```sql
-- Verify import
SELECT COUNT(*) FROM obce;            -- ~6,258 municipalities
SELECT COUNT(*) FROM katastralniuzemi; -- ~13,000 cadastral areas
SELECT COUNT(*) FROM adresnimista;     -- ~3,000,000 address points
SELECT COUNT(*) FROM stavebniobjekty;  -- ~3,500,000 buildings
SELECT COUNT(*) FROM parcely;          -- ~25,000,000 parcels
```

## Production Deployment

### Recommended Server Configuration

For full country import on a production server:

**Hetzner Cloud (cost-effective):**
- CAX21 (4 vCPU Ampere, 8 GB RAM, 160 GB disk): ~€8/month
- CAX31 (8 vCPU Ampere, 16 GB RAM, 320 GB disk): ~€15/month

**AWS/GCP/Azure:**
- ARM64 instances (Graviton, Ampere) offer better price/performance
- t4g.medium or larger on AWS
- Minimum 200 GB EBS/disk

### PostgreSQL Tuning

For large imports, add to `postgresql.conf`:
```
shared_buffers = 2GB
work_mem = 256MB
maintenance_work_mem = 1GB
effective_cache_size = 6GB
checkpoint_completion_target = 0.9
```

## Web Map Viewer

The project includes an interactive web map for visualizing RUIAN data using vector tiles.

### Architecture

```
Browser (MapLibre GL JS)
    ↓ HTTP: /tiles/{layer}/{z}/{x}/{y}
Martin Tile Server (Docker)
    ↓ PostgreSQL connection
PostGIS Database
```

### Quick Start

```bash
# 1. Ensure PostGIS is running
podman start ruian-postgis

# 2. Start Martin tile server
podman run -d --name martin -p 3000:3000 \
  -v ./martin/martin.yaml:/config.yaml:ro \
  ghcr.io/maplibre/martin --config /config.yaml

# 3. Serve the web frontend
cd web && python3 -m http.server 8080

# 4. Open in browser
open http://localhost:8080
```

### Available Layers

| Layer | Type | Description |
|-------|------|-------------|
| `adresnimista` | points | Address points (zoom 14+) |
| `stavebniobjekty` | polygons | Buildings (zoom 13+) |
| `parcely` | polygons | Land parcels (zoom 15+) |
| `ulice` | lines | Streets (zoom 12+) |
| `obce` | polygons | Municipality boundaries (zoom 8-14) |
| `katastralniuzemi` | polygons | Cadastral areas (zoom 12+) |
| `okresy` | polygons | District boundaries (zoom 6-12) |

### Verify Tile Server

```bash
# Health check
curl http://localhost:3000/health

# List available sources
curl http://localhost:3000/catalog

# Get TileJSON for a layer
curl http://localhost:3000/obce
```

### Production Deployment

For production, configure Martin with the server's database connection in `martin/martin.yaml`:

```yaml
postgres:
  connection_string: 'postgresql://ruian:ruian@localhost:5432/ruian'
```

Use nginx or similar to serve the static frontend and optionally proxy Martin.

## Data Source

Data is downloaded from CUZK (Czech Office for Surveying, Mapping and Cadastre):
- Configuration: https://vdp.cuzk.gov.cz/vdp/ruian/vymennyformat
- File format: VFR (Výměnný formát RÚIAN) - XML in ZIP archive
- Coordinate system: S-JTSK / Krovak East North (EPSG:5514)

## Data Types

| File Type | Description | Contents |
|-----------|-------------|----------|
| ST_UKSH | State structure | Regions, districts, ORP, POU (no detailed municipality data) |
| OB_*_UKSH | Municipality files | Addresses, buildings, parcels, streets for each municipality |

There are approximately **6,258 OB files** (one per municipality).

## Notice Board Documents

The project includes a module for downloading and processing documents from official notice boards of Czech municipalities, parsing references to parcels, addresses, and streets, and displaying them on a map.

### Features

- Download documents from various notice board systems (GINIS, Vismo, eDesky, OFN)
- Extract text from PDF documents
- Parse references to RUIAN entities (parcels, addresses, streets)
- Validate extracted references against RUIAN database
- Display referenced parcels/streets on the web map

### Setup Notice Board Database

```bash
# Apply database migrations
psql -U ruian -d ruian -f scripts/setup_notice_boards_db.sql
psql -U ruian -d ruian -f scripts/migrate_notice_boards_v2.sql
```

### Fetch Notice Board List

Download list of all Czech municipalities with their official notice board URLs from multiple sources:

```bash
# Fetch all data (Česko.Digital + NKOD OFN) - takes ~1 minute
uv run python scripts/fetch_notice_boards.py -o data/notice_boards.json

# Quick fetch (skip OFN, faster)
uv run python scripts/fetch_notice_boards.py --skip-ofn -o data/notice_boards.json

# Verbose output
uv run python scripts/fetch_notice_boards.py -o data/notice_boards.json -v
```

Data sources:
- **Česko.Digital API** - comprehensive municipality data (~6,300 entries)
- **NKOD GraphQL API** - official OFN (Open Formal Norm) datasets with direct URLs to notice boards

### Import Notice Boards to Database

```bash
# Import from JSON file
uv run python scripts/import_notice_boards.py data/notice_boards.json

# Show database statistics
uv run python scripts/import_notice_boards.py --stats
```

Example statistics output:
```
Notice Board Statistics:
  Total:              6,396
  With official URL:  226
  With OFN JSON URL:  228
  With eDesky URL:    6,063
  With RUIAN ref:     6,251

By type:
  obec                 6,390
  kraj                 4
  mesto                2
```

This creates tables for:
- `notice_boards` - Notice board sources (municipalities)
- `documents` - Downloaded documents
- `attachments` - Document attachments (PDFs, etc.)
- `parcel_refs`, `address_refs`, `street_refs` - Extracted references
- Martin function sources for map visualization

### Validate References

```python
from notice_boards.validators import RuianValidator
from notice_boards.config import get_db_connection

validator = RuianValidator(get_db_connection())

# Validate parcel
result = validator.validate_parcel(
    cadastral_area_name="Veveří",
    parcel_number=592,
    parcel_sub_number=2
)
print(f"Parcel valid: {result.is_valid}, ID: {result.parcel_id}")

# Validate address
result = validator.validate_address(
    municipality_name="Brno",
    street_name="Kounicova",
    house_number=67
)
print(f"Address valid: {result.is_valid}, Code: {result.address_point_code}")

# Validate street
result = validator.validate_street(
    municipality_name="Brno",
    street_name="Kounicova"
)
print(f"Street valid: {result.is_valid}, Code: {result.street_code}")
```

### Storage Backend

```python
from pathlib import Path
from notice_boards.storage import FilesystemStorage

storage = FilesystemStorage(Path("data/attachments"))

# Save attachment
storage.save("2024/01/doc123/file.pdf", pdf_content)

# Load attachment
content = storage.load("2024/01/doc123/file.pdf")

# Check if exists
if storage.exists("2024/01/doc123/file.pdf"):
    print("File exists")
```

## License

Data from RUIAN is available under open license from CUZK.
