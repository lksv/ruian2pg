"""Configuration for notice board document processing."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from psycopg2.extensions import connection as Connection


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


@dataclass
class StorageConfig:
    """Configuration for document attachment storage."""

    # Base path for file storage
    base_path: Path = field(
        default_factory=lambda: Path(os.getenv("NOTICE_BOARDS_STORAGE_PATH", "data/attachments"))
    )

    # Maximum file size in bytes (default: 100MB)
    max_file_size: int = field(
        default_factory=lambda: int(
            os.getenv("NOTICE_BOARDS_MAX_FILE_SIZE", str(100 * 1024 * 1024))
        )
    )


def get_db_connection() -> "Connection":
    """Get a database connection using default configuration.

    Returns:
        psycopg2 connection object.
    """
    import psycopg2

    config = DatabaseConfig()
    return psycopg2.connect(config.connection_string)


def get_project_root() -> Path:
    """Return the project root directory."""
    return Path(__file__).parent.parent.parent


def get_storage_path() -> Path:
    """Return the storage directory for attachments, creating it if necessary."""
    config = StorageConfig()
    storage_path = get_project_root() / config.base_path
    storage_path.mkdir(parents=True, exist_ok=True)
    return storage_path
