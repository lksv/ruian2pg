"""Text extraction service for attachments.

Extracts text from document attachments using Docling (with OCR support)
or fallback extractors (PyMuPDF, pdfplumber).

Two modes:
1. Stored mode - extract from files already in storage (download_status='downloaded')
2. Streaming mode - download and extract on-the-fly without persisting files

Usage:
    from notice_boards.services import TextExtractionService, AttachmentDownloader
    from notice_boards.services.text_extractor import ExtractionConfig
    from notice_boards.config import get_db_connection
    from pathlib import Path

    conn = get_db_connection()
    downloader = AttachmentDownloader(conn, Path("data/attachments"))
    config = ExtractionConfig(use_ocr=True)
    service = TextExtractionService(conn, downloader, config)

    # Extract text (auto-downloads if needed, doesn't persist file)
    result = service.extract_text(attachment_id=123, persist_attachment=False)

    # Extract from stored files only
    stats = service.extract_batch(only_downloaded=True)

    # Streaming mode - download and extract without persisting
    stats = service.extract_batch(persist_attachments=False)
"""

import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import TYPE_CHECKING

from notice_boards.models import DownloadStatus, ParseStatus
from notice_boards.parsers import create_default_extractor
from notice_boards.parsers.base import TextExtractionError, TextExtractor
from notice_boards.storage import StorageBackend

if TYPE_CHECKING:
    from psycopg2.extensions import connection as Connection

    from notice_boards.services.attachment_downloader import AttachmentDownloader

logger = logging.getLogger(__name__)


@dataclass
class ExtractionConfig:
    """Configuration for text extraction."""

    # Prefer stored files over streaming download
    prefer_stored: bool = True

    # Save downloaded file after streaming extraction
    persist_after_stream: bool = False

    # Output format for Docling: "markdown", "text", "html"
    output_format: str = "markdown"

    # Maximum file size to process (default: 100 MB)
    max_file_size_bytes: int = field(default=100 * 1024 * 1024)

    # Enable OCR for scanned documents
    use_ocr: bool = True

    # OCR backend: "tesserocr", "easyocr", "rapidocr", "ocrmac"
    ocr_backend: str = "tesserocr"

    # Force full-page OCR even for documents with text layer
    force_full_page_ocr: bool = False

    # Extraction timeout in seconds
    extraction_timeout: int = 300

    # Date filters for document published_at
    published_after: date | None = None
    published_before: date | None = None

    # Batch size for database queries
    batch_size: int = 100

    # Verbose logging
    verbose: bool = False


@dataclass
class PendingExtraction:
    """Attachment record pending text extraction."""

    id: int
    document_id: int
    notice_board_id: int
    filename: str
    mime_type: str | None
    file_size_bytes: int | None
    storage_path: str | None
    orig_url: str | None
    download_status: str
    board_name: str | None = None


@dataclass
class ExtractionResult:
    """Result of text extraction for single attachment."""

    attachment_id: int
    success: bool
    text_length: int | None = None
    error: str | None = None
    error_type: str | None = None  # "download", "extraction", "timeout", "skipped"


@dataclass
class ExtractionStats:
    """Statistics for extraction session."""

    total: int = 0
    extracted: int = 0
    failed: int = 0
    skipped: int = 0
    total_chars: int = 0

    def __str__(self) -> str:
        return (
            f"Total: {self.total}, "
            f"Extracted: {self.extracted}, "
            f"Failed: {self.failed}, "
            f"Skipped: {self.skipped}, "
            f"Total chars: {self.total_chars:,}"
        )


# MIME types we support for extraction
SUPPORTED_MIME_TYPES = frozenset(
    [
        # PDF
        "application/pdf",
        "application/x-pdf",
        # Microsoft Office
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/msword",
        "application/vnd.ms-excel",
        "application/vnd.ms-powerpoint",
        # Images (with OCR)
        "image/png",
        "image/jpeg",
        "image/jpg",
        "image/tiff",
        "image/bmp",
        "image/gif",
        # HTML
        "text/html",
        "application/xhtml+xml",
        # Plain text
        "text/plain",
    ]
)


class TextExtractionService:
    """Service for extracting text from document attachments.

    Uses AttachmentDownloader.get_attachment_content() as unified API
    to get file content - works regardless of whether file is already
    stored or needs to be downloaded.

    Example:
        downloader = AttachmentDownloader(conn, storage_path)
        config = ExtractionConfig(use_ocr=True)
        service = TextExtractionService(conn, downloader, config)

        # Extract text (auto-downloads if needed)
        result = service.extract_text(attachment_id=123)

        # Batch extraction
        stats = service.extract_batch(board_id=123, limit=100)
    """

    def __init__(
        self,
        conn: "Connection",
        downloader: "AttachmentDownloader",
        config: ExtractionConfig | None = None,
        text_storage: StorageBackend | None = None,
        extractor: TextExtractor | None = None,
    ) -> None:
        """Initialize text extraction service.

        Args:
            conn: Database connection.
            downloader: AttachmentDownloader instance for getting content.
            config: Extraction configuration.
            text_storage: Optional storage backend for extracted text files.
            extractor: Optional custom text extractor (default: create_default_extractor)
        """
        self.conn = conn
        self.downloader = downloader
        self.config = config or ExtractionConfig()
        self.text_storage = text_storage

        # Create default extractor if not provided
        if extractor is not None:
            self.extractor = extractor
        else:
            self.extractor = create_default_extractor(
                use_ocr=self.config.use_ocr,
                ocr_backend=self.config.ocr_backend,
                force_full_page_ocr=self.config.force_full_page_ocr,
                output_format=self.config.output_format,
            )

    # -------------------------------------------------------------------------
    # Query methods
    # -------------------------------------------------------------------------

    def get_pending_count(
        self,
        board_id: int | None = None,
        include_failed: bool = False,
        only_downloaded: bool = False,
        published_after: date | None = None,
        published_before: date | None = None,
    ) -> int:
        """Get count of attachments pending extraction.

        Args:
            board_id: Filter by notice board ID.
            include_failed: Include parse_status='failed' attachments.
            only_downloaded: Only count attachments with download_status='downloaded'.
            published_after: Filter documents published on or after this date.
            published_before: Filter documents published on or before this date.

        Returns:
            Number of pending attachments.
        """
        # Use config date filters if not overridden
        if published_after is None:
            published_after = self.config.published_after
        if published_before is None:
            published_before = self.config.published_before

        statuses = [ParseStatus.PENDING]
        if include_failed:
            statuses.append(ParseStatus.FAILED)

        with self.conn.cursor() as cur:
            query = """
                SELECT COUNT(*)
                FROM attachments a
                JOIN documents d ON d.id = a.document_id
                WHERE a.parse_status = ANY(%s)
            """
            params: list[list[str] | int | date | str] = [statuses]

            if only_downloaded:
                query += " AND a.download_status = %s"
                params.append(DownloadStatus.DOWNLOADED)

            if board_id is not None:
                query += " AND d.notice_board_id = %s"
                params.append(board_id)

            if published_after is not None:
                query += " AND d.published_at >= %s"
                params.append(published_after)

            if published_before is not None:
                query += " AND d.published_at <= %s"
                params.append(published_before)

            cur.execute(query, params)
            result = cur.fetchone()
            return result[0] if result else 0

    def iter_pending_extractions(
        self,
        board_id: int | None = None,
        include_failed: bool = False,
        only_downloaded: bool = False,
        limit: int | None = None,
        offset: int = 0,
        published_after: date | None = None,
        published_before: date | None = None,
    ) -> Iterator[PendingExtraction]:
        """Iterate over attachments pending extraction.

        Args:
            board_id: Filter by notice board ID.
            include_failed: Include parse_status='failed' attachments.
            only_downloaded: Only return attachments with download_status='downloaded'.
            limit: Maximum number of attachments to return.
            offset: Number of attachments to skip.
            published_after: Filter documents published on or after this date.
            published_before: Filter documents published on or before this date.

        Yields:
            PendingExtraction objects.
        """
        # Use config date filters if not overridden
        if published_after is None:
            published_after = self.config.published_after
        if published_before is None:
            published_before = self.config.published_before

        statuses = [ParseStatus.PENDING]
        if include_failed:
            statuses.append(ParseStatus.FAILED)

        with self.conn.cursor() as cur:
            query = """
                SELECT a.id, a.document_id, d.notice_board_id,
                       a.filename, a.mime_type, a.file_size_bytes,
                       a.storage_path, a.orig_url, a.download_status, nb.name
                FROM attachments a
                JOIN documents d ON d.id = a.document_id
                LEFT JOIN notice_boards nb ON nb.id = d.notice_board_id
                WHERE a.parse_status = ANY(%s)
            """
            params: list[list[str] | int | date | str] = [statuses]

            if only_downloaded:
                query += " AND a.download_status = %s"
                params.append(DownloadStatus.DOWNLOADED)

            if board_id is not None:
                query += " AND d.notice_board_id = %s"
                params.append(board_id)

            if published_after is not None:
                query += " AND d.published_at >= %s"
                params.append(published_after)

            if published_before is not None:
                query += " AND d.published_at <= %s"
                params.append(published_before)

            query += " ORDER BY a.id"

            if limit is not None:
                query += " LIMIT %s"
                params.append(limit)

            if offset > 0:
                query += " OFFSET %s"
                params.append(offset)

            cur.execute(query, params)

            for row in cur.fetchall():
                yield PendingExtraction(
                    id=row[0],
                    document_id=row[1],
                    notice_board_id=row[2],
                    filename=row[3] or "unknown",
                    mime_type=row[4],
                    file_size_bytes=row[5],
                    storage_path=row[6],
                    orig_url=row[7],
                    download_status=row[8] or DownloadStatus.PENDING,
                    board_name=row[9],
                )

    def get_pending_extractions(
        self,
        board_id: int | None = None,
        include_failed: bool = False,
        only_downloaded: bool = False,
        limit: int | None = None,
        offset: int = 0,
        published_after: date | None = None,
        published_before: date | None = None,
    ) -> list[PendingExtraction]:
        """Get list of attachments pending extraction.

        Args:
            board_id: Filter by notice board ID.
            include_failed: Include parse_status='failed' attachments.
            only_downloaded: Only return attachments with download_status='downloaded'.
            limit: Maximum number of attachments to return.
            offset: Number of attachments to skip.
            published_after: Filter documents published on or after this date.
            published_before: Filter documents published on or before this date.

        Returns:
            List of PendingExtraction objects.
        """
        return list(
            self.iter_pending_extractions(
                board_id=board_id,
                include_failed=include_failed,
                only_downloaded=only_downloaded,
                limit=limit,
                offset=offset,
                published_after=published_after,
                published_before=published_before,
            )
        )

    # -------------------------------------------------------------------------
    # Single extraction
    # -------------------------------------------------------------------------

    def extract_text(
        self,
        attachment_id: int,
        persist_attachment: bool | None = None,
    ) -> ExtractionResult:
        """Extract text from attachment.

        Uses downloader.get_attachment_content() to get content,
        then extracts text based on mime_type.

        Args:
            attachment_id: Database ID of attachment.
            persist_attachment: If True, save attachment file to storage after download.
                               If None, uses config.persist_after_stream.

        Returns:
            ExtractionResult with success/failure info.
        """
        # Get attachment info
        pending = self._get_attachment_info(attachment_id)
        if pending is None:
            return ExtractionResult(
                attachment_id=attachment_id,
                success=False,
                error="Attachment not found",
                error_type="extraction",
            )

        # Check if MIME type is supported
        mime_type = pending.mime_type or ""
        if mime_type.lower() not in SUPPORTED_MIME_TYPES:
            # Mark as skipped
            self.mark_skipped(attachment_id, f"Unsupported MIME type: {mime_type}")
            return ExtractionResult(
                attachment_id=attachment_id,
                success=False,
                error=f"Unsupported MIME type: {mime_type}",
                error_type="skipped",
            )

        # Check file size limit
        if pending.file_size_bytes and pending.file_size_bytes > self.config.max_file_size_bytes:
            self.mark_skipped(
                attachment_id,
                f"File too large: {pending.file_size_bytes} > {self.config.max_file_size_bytes}",
            )
            return ExtractionResult(
                attachment_id=attachment_id,
                success=False,
                error="File too large",
                error_type="skipped",
            )

        # Mark as parsing
        self.mark_parsing(attachment_id)

        # Determine whether to persist
        persist = (
            persist_attachment
            if persist_attachment is not None
            else self.config.persist_after_stream
        )

        # Get content (from storage or download)
        try:
            content = self.downloader.get_attachment_content(
                attachment_id=attachment_id,
                persist=persist,
            )
        except Exception as e:
            error_msg = f"download: {e}"
            self.mark_failed(attachment_id, error_msg, error_type="download")
            return ExtractionResult(
                attachment_id=attachment_id,
                success=False,
                error=error_msg,
                error_type="download",
            )

        if content is None:
            error_msg = "download: No content available"
            self.mark_failed(attachment_id, error_msg, error_type="download")
            return ExtractionResult(
                attachment_id=attachment_id,
                success=False,
                error=error_msg,
                error_type="download",
            )

        # Check size after download
        if len(content) > self.config.max_file_size_bytes:
            self.mark_skipped(
                attachment_id,
                f"File too large: {len(content)} > {self.config.max_file_size_bytes}",
            )
            return ExtractionResult(
                attachment_id=attachment_id,
                success=False,
                error="File too large",
                error_type="skipped",
            )

        # Extract text
        try:
            text = self.extractor.extract(content, mime_type)
        except TextExtractionError as e:
            error_msg = f"extraction: {e}"
            self.mark_failed(attachment_id, error_msg, error_type="extraction")
            return ExtractionResult(
                attachment_id=attachment_id,
                success=False,
                error=error_msg,
                error_type="extraction",
            )
        except Exception as e:
            error_msg = f"extraction: {e}"
            self.mark_failed(attachment_id, error_msg, error_type="extraction")
            return ExtractionResult(
                attachment_id=attachment_id,
                success=False,
                error=error_msg,
                error_type="extraction",
            )

        if text is None:
            # Extractor returned None - no text found
            self.mark_completed(attachment_id, "")
            return ExtractionResult(
                attachment_id=attachment_id,
                success=True,
                text_length=0,
            )

        # Mark completed with extracted text
        self.mark_completed(attachment_id, text)

        if self.config.verbose:
            logger.info(
                f"Extracted text from attachment {attachment_id}: "
                f"{len(text)} chars from {pending.filename}"
            )

        return ExtractionResult(
            attachment_id=attachment_id,
            success=True,
            text_length=len(text),
        )

    def _get_attachment_info(self, attachment_id: int) -> PendingExtraction | None:
        """Get attachment info from database."""
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT a.id, a.document_id, d.notice_board_id,
                       a.filename, a.mime_type, a.file_size_bytes,
                       a.storage_path, a.orig_url, a.download_status, nb.name
                FROM attachments a
                JOIN documents d ON d.id = a.document_id
                LEFT JOIN notice_boards nb ON nb.id = d.notice_board_id
                WHERE a.id = %s
                """,
                (attachment_id,),
            )
            row = cur.fetchone()
            if row is None:
                return None

            return PendingExtraction(
                id=row[0],
                document_id=row[1],
                notice_board_id=row[2],
                filename=row[3] or "unknown",
                mime_type=row[4],
                file_size_bytes=row[5],
                storage_path=row[6],
                orig_url=row[7],
                download_status=row[8] or DownloadStatus.PENDING,
                board_name=row[9],
            )

    # -------------------------------------------------------------------------
    # Batch extraction
    # -------------------------------------------------------------------------

    def extract_batch(
        self,
        board_id: int | None = None,
        persist_attachments: bool | None = None,
        only_downloaded: bool = False,
        include_failed: bool = False,
        limit: int | None = None,
        published_after: date | None = None,
        published_before: date | None = None,
        on_progress: Callable[[ExtractionResult], None] | None = None,
    ) -> ExtractionStats:
        """Extract text from multiple pending attachments.

        Args:
            board_id: Filter by notice board ID.
            persist_attachments: If True, save files to storage after download.
            only_downloaded: Only process attachments already in storage.
            include_failed: Include previously failed attachments.
            limit: Maximum number to process.
            published_after: Filter by document publication date.
            published_before: Filter by document publication date.
            on_progress: Callback called after each extraction.

        Returns:
            Extraction statistics.
        """
        stats = ExtractionStats()
        stats.total = self.get_pending_count(
            board_id=board_id,
            include_failed=include_failed,
            only_downloaded=only_downloaded,
            published_after=published_after,
            published_before=published_before,
        )

        effective_limit = limit if limit else stats.total

        for pending in self.iter_pending_extractions(
            board_id=board_id,
            include_failed=include_failed,
            only_downloaded=only_downloaded,
            limit=effective_limit,
            published_after=published_after,
            published_before=published_before,
        ):
            result = self.extract_text(
                attachment_id=pending.id,
                persist_attachment=persist_attachments,
            )

            if result.success:
                stats.extracted += 1
                stats.total_chars += result.text_length or 0
            elif result.error_type == "skipped":
                stats.skipped += 1
            else:
                stats.failed += 1

            if on_progress:
                on_progress(result)

        return stats

    # -------------------------------------------------------------------------
    # Status management
    # -------------------------------------------------------------------------

    def mark_parsing(self, attachment_id: int) -> None:
        """Mark attachment as parsing (in progress).

        Args:
            attachment_id: Attachment ID.
        """
        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE attachments
                SET parse_status = %s,
                    parsed_at = %s,
                    parse_error = NULL
                WHERE id = %s
                """,
                (ParseStatus.PARSING, datetime.now(), attachment_id),
            )
        self.conn.commit()

    def mark_completed(self, attachment_id: int, extracted_text: str) -> None:
        """Mark attachment as completed with extracted text.

        Args:
            attachment_id: Attachment ID.
            extracted_text: Extracted text content.
        """
        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE attachments
                SET parse_status = %s,
                    parsed_at = %s,
                    extracted_text = %s,
                    parse_error = NULL
                WHERE id = %s
                """,
                (ParseStatus.COMPLETED, datetime.now(), extracted_text, attachment_id),
            )
        self.conn.commit()

    def mark_failed(
        self,
        attachment_id: int,
        error: str,
        error_type: str = "extraction",
    ) -> None:
        """Mark attachment as failed.

        Args:
            attachment_id: Attachment ID.
            error: Error message.
            error_type: Error type prefix ("download", "extraction", "timeout").
        """
        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE attachments
                SET parse_status = %s,
                    parsed_at = %s,
                    parse_error = %s
                WHERE id = %s
                """,
                (ParseStatus.FAILED, datetime.now(), error, attachment_id),
            )
        self.conn.commit()

    def mark_skipped(self, attachment_id: int, reason: str) -> None:
        """Mark attachment as skipped.

        Args:
            attachment_id: Attachment ID.
            reason: Reason for skipping.
        """
        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE attachments
                SET parse_status = %s,
                    parsed_at = %s,
                    parse_error = %s
                WHERE id = %s
                """,
                (ParseStatus.SKIPPED, datetime.now(), reason, attachment_id),
            )
        self.conn.commit()

    def reset_to_pending(self, failed_only: bool = True) -> int:
        """Reset attachments to pending for retry.

        Args:
            failed_only: If True, only reset 'failed' status.
                        If False, also reset 'skipped'.

        Returns:
            Number of attachments reset.
        """
        statuses = [ParseStatus.FAILED]
        if not failed_only:
            statuses.append(ParseStatus.SKIPPED)

        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE attachments
                SET parse_status = %s,
                    parsed_at = NULL,
                    parse_error = NULL,
                    extracted_text = NULL
                WHERE parse_status = ANY(%s)
                """,
                (ParseStatus.PENDING, statuses),
            )
            count: int = cur.rowcount or 0
        self.conn.commit()
        return count

    # -------------------------------------------------------------------------
    # Statistics
    # -------------------------------------------------------------------------

    def get_stats(self) -> dict[str, int]:
        """Get extraction statistics.

        Returns:
            Dict with counts for total, pending, parsing, completed, failed, skipped.
        """
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    COUNT(CASE WHEN parse_status = 'pending' THEN 1 END) AS pending,
                    COUNT(CASE WHEN parse_status = 'parsing' THEN 1 END) AS parsing,
                    COUNT(CASE WHEN parse_status = 'completed' THEN 1 END) AS completed,
                    COUNT(CASE WHEN parse_status = 'failed' THEN 1 END) AS failed,
                    COUNT(CASE WHEN parse_status = 'skipped' THEN 1 END) AS skipped,
                    COALESCE(SUM(LENGTH(extracted_text)), 0) AS total_chars
                FROM attachments
                """
            )
            row = cur.fetchone()
            if row is None:
                return {
                    "total": 0,
                    "pending": 0,
                    "parsing": 0,
                    "completed": 0,
                    "failed": 0,
                    "skipped": 0,
                    "total_chars": 0,
                }
            return {
                "total": row[0],
                "pending": row[1],
                "parsing": row[2],
                "completed": row[3],
                "failed": row[4],
                "skipped": row[5],
                "total_chars": row[6],
            }

    def get_stats_by_board(self) -> list[dict[str, int | str | None]]:
        """Get extraction statistics grouped by notice board.

        Returns:
            List of dicts with board_id, board_name, and status counts.
        """
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    nb.id AS board_id,
                    nb.name AS board_name,
                    COUNT(a.id) AS total,
                    COUNT(CASE WHEN a.parse_status = 'pending' THEN 1 END) AS pending,
                    COUNT(CASE WHEN a.parse_status = 'completed' THEN 1 END) AS completed,
                    COUNT(CASE WHEN a.parse_status = 'failed' THEN 1 END) AS failed,
                    COUNT(CASE WHEN a.parse_status = 'skipped' THEN 1 END) AS skipped
                FROM notice_boards nb
                JOIN documents d ON d.notice_board_id = nb.id
                JOIN attachments a ON a.document_id = d.id
                GROUP BY nb.id, nb.name
                HAVING COUNT(CASE WHEN a.parse_status IN ('pending', 'failed') THEN 1 END) > 0
                ORDER BY pending DESC
                """
            )
            return [
                {
                    "board_id": row[0],
                    "board_name": row[1],
                    "total": row[2],
                    "pending": row[3],
                    "completed": row[4],
                    "failed": row[5],
                    "skipped": row[6],
                }
                for row in cur.fetchall()
            ]

    def get_stats_by_mime_type(self) -> list[dict[str, int | str | None]]:
        """Get extraction statistics grouped by MIME type.

        Returns:
            List of dicts with mime_type and status counts.
        """
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    mime_type,
                    COUNT(*) AS total,
                    COUNT(CASE WHEN parse_status = 'pending' THEN 1 END) AS pending,
                    COUNT(CASE WHEN parse_status = 'completed' THEN 1 END) AS completed,
                    COUNT(CASE WHEN parse_status = 'failed' THEN 1 END) AS failed,
                    COUNT(CASE WHEN parse_status = 'skipped' THEN 1 END) AS skipped
                FROM attachments
                GROUP BY mime_type
                ORDER BY total DESC
                """
            )
            return [
                {
                    "mime_type": row[0],
                    "total": row[1],
                    "pending": row[2],
                    "completed": row[3],
                    "failed": row[4],
                    "skipped": row[5],
                }
                for row in cur.fetchall()
            ]
