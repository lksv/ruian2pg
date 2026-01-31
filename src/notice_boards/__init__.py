"""Notice board document processing package.

This package provides tools for downloading documents from official notice boards
of municipalities, parsing references to parcels/addresses/streets, and
displaying them on a map.
"""

from notice_boards.config import DatabaseConfig, StorageConfig
from notice_boards.storage import FilesystemStorage, StorageBackend
from notice_boards.validators import (
    AddressValidationResult,
    ParcelValidationResult,
    RuianValidator,
    StreetValidationResult,
)

__all__ = [
    # Config
    "DatabaseConfig",
    "StorageConfig",
    # Storage
    "StorageBackend",
    "FilesystemStorage",
    # Validators
    "RuianValidator",
    "ParcelValidationResult",
    "AddressValidationResult",
    "StreetValidationResult",
]
