"""Configuration for RUIAN import."""

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class DatabaseConfig:
    """PostgreSQL/PostGIS database configuration."""

    host: str = field(default_factory=lambda: os.getenv("RUIAN_DB_HOST", "localhost"))
    port: int = field(default_factory=lambda: int(os.getenv("RUIAN_DB_PORT", "5432")))
    database: str = field(default_factory=lambda: os.getenv("RUIAN_DB_NAME", "ruian"))
    user: str = field(default_factory=lambda: os.getenv("RUIAN_DB_USER", "ruian"))
    password: str = field(default_factory=lambda: os.getenv("RUIAN_DB_PASSWORD", "ruian"))

    @property
    def connection_string(self) -> str:
        """Return psycopg2 connection string."""
        return (
            f"host={self.host} port={self.port} dbname={self.database} "
            f"user={self.user} password={self.password}"
        )

    @property
    def ogr_connection_string(self) -> str:
        """Return OGR PostgreSQL connection string."""
        return (
            f"PG:host={self.host} port={self.port} dbname={self.database} "
            f"user={self.user} password={self.password}"
        )


@dataclass
class DownloadConfig:
    """Configuration for downloading RUIAN data."""

    # Base URL for VFR file list (ST - state level data)
    list_url: str = (
        "https://vdp.cuzk.gov.cz/vdp/ruian/vymennyformat"
        "?crPrirustky&crKopie=true&page&casovyRozsah=U&datum"
        "&upStatAzZsj=true&upObecAPodrazene=false&uzemniPrvky=ST"
        "&dsZakladni=false&dsKompletni=true&datovaSada=K"
        "&vyZakladni=false&vyZakladniAGenHranice=false"
        "&vyZakladniAOrigHranice=true&vyVlajkyAZnaky=false"
        "&vyber=vyZakladniAOrigHranice&kodVusc&kodOrp&kodOb"
        "&mediaType=text"
    )

    # URL for municipality (OB) file list - all municipalities with detailed data
    ob_list_url: str = (
        "https://vdp.cuzk.gov.cz/vdp/ruian/vymennyformat"
        "?crKopie=true&casovyRozsah=U&upObecAPodrazene=true"
        "&uzemniPrvky=OB&dsKompletni=true&datovaSada=K"
        "&vyZakladniAOrigHranice=true&vyber=vyZakladniAOrigHranice"
        "&mediaType=text"
    )

    # Base URL for downloading files
    base_download_url: str = "https://vdp.cuzk.gov.cz/vymenny_format/soucasna"

    # Local data directory
    data_dir: Path = field(default_factory=lambda: Path("data"))

    # HTTP timeout in seconds
    timeout: int = 300

    # Chunk size for streaming downloads
    chunk_size: int = 8192

    # Maximum concurrent downloads for parallel downloading
    max_concurrent_downloads: int = 5


def get_project_root() -> Path:
    """Return the project root directory."""
    return Path(__file__).parent.parent.parent


def get_data_dir() -> Path:
    """Return the data directory, creating it if necessary."""
    data_dir = get_project_root() / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir
