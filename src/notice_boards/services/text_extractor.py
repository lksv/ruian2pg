"""Text extraction service for attachments.

NOTE: This is a placeholder for future implementation.
Uses AttachmentDownloader.get_attachment_content() for unified content access.

Usage:
    from notice_boards.services import TextExtractionService, AttachmentDownloader
    from notice_boards.config import get_db_connection
    from pathlib import Path

    conn = get_db_connection()
    downloader = AttachmentDownloader(conn, Path("data/attachments"))
    service = TextExtractionService(conn, downloader)

    # Extract text (auto-downloads if needed, doesn't persist file)
    text = service.extract_text(attachment_id=123, persist_attachment=False)

    # Extract and also save the attachment
    text = service.extract_text(attachment_id=123, persist_attachment=True)
"""

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from psycopg2.extensions import connection as Connection

    from notice_boards.services.attachment_downloader import AttachmentDownloader
    from notice_boards.storage import StorageBackend


@dataclass
class ExtractionResult:
    """Result of text extraction for single attachment."""

    attachment_id: int
    success: bool
    text_length: int | None = None
    error: str | None = None


@dataclass
class ExtractionStats:
    """Statistics for extraction session."""

    total: int = 0
    extracted: int = 0
    failed: int = 0
    skipped: int = 0

    def __str__(self) -> str:
        return (
            f"Total: {self.total}, "
            f"Extracted: {self.extracted}, "
            f"Failed: {self.failed}, "
            f"Skipped: {self.skipped}"
        )


class TextExtractionService:
    """Service for extracting text from document attachments.

    Uses AttachmentDownloader.get_attachment_content() as unified API
    to get file content - works regardless of whether file is already
    stored or needs to be downloaded.

    Example:
        downloader = AttachmentDownloader(conn, storage_path)
        service = TextExtractionService(conn, downloader)

        # Extract text (auto-downloads if needed, doesn't persist file)
        text = service.extract_text(attachment_id=123, persist_attachment=False)

        # Extract and also save the attachment
        text = service.extract_text(attachment_id=123, persist_attachment=True)
    """

    def __init__(
        self,
        conn: "Connection",
        downloader: "AttachmentDownloader",
        text_storage: "StorageBackend | None" = None,
    ) -> None:
        """Initialize text extraction service.

        Args:
            conn: Database connection.
            downloader: AttachmentDownloader instance for getting content.
            text_storage: Optional storage backend for extracted text files.
        """
        self.conn = conn
        self.downloader = downloader
        self.text_storage = text_storage

    def extract_text(
        self,
        attachment_id: int,
        persist_attachment: bool = False,
    ) -> str | None:
        """Extract text from attachment.

        Uses downloader.get_attachment_content() to get content,
        then extracts text based on mime_type.

        Args:
            attachment_id: Database ID of attachment.
            persist_attachment: If True, also save attachment file to storage.

        Returns:
            Extracted text or None if extraction failed.

        Raises:
            NotImplementedError: Not yet implemented.
        """
        raise NotImplementedError("Text extraction not yet implemented")

    def extract_batch(
        self,
        persist_attachments: bool = False,
        published_after: date | None = None,
        published_before: date | None = None,
        limit: int | None = None,
    ) -> ExtractionStats:
        """Extract text from multiple pending attachments.

        Args:
            persist_attachments: If True, also save files to storage.
            published_after: Filter by document publication date.
            published_before: Filter by document publication date.
            limit: Maximum number to process.

        Returns:
            Extraction statistics.

        Raises:
            NotImplementedError: Not yet implemented.
        """
        raise NotImplementedError("Batch extraction not yet implemented")
