"""Service for downloading missing attachment content.

Downloads attachment files for records that have metadata (orig_url)
but no content (empty storage_path).

Usage as library:
    from notice_boards.services import AttachmentDownloader, DownloadConfig
    from notice_boards.config import get_db_connection
    from pathlib import Path

    config = DownloadConfig(max_size_bytes=50 * 1024 * 1024)
    downloader = AttachmentDownloader(
        conn=get_db_connection(),
        storage_path=Path("data/attachments"),
        config=config,
    )

    # Download all pending attachments
    stats = downloader.download_all()
    print(f"Downloaded: {stats.downloaded}, Failed: {stats.failed}")

    # Download for specific board
    stats = downloader.download_by_board(board_id=123)

    # Get pending attachments without downloading
    pending = downloader.get_pending_attachments(limit=100)

    # Filter by document publication date
    config = DownloadConfig(
        published_after=date(2024, 1, 1),
        published_before=date(2024, 12, 31),
    )
    downloader = AttachmentDownloader(conn, storage_path, config)
    stats = downloader.download_all()

    # Mark old attachments as removed
    count = downloader.mark_removed([1, 2, 3])

    # Get content (from storage or by downloading)
    content = downloader.get_attachment_content(attachment_id=123, persist=True)
"""

import logging
import mimetypes
import os
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

from notice_boards.models import DownloadStatus
from notice_boards.storage import FilesystemStorage, StorageBackend

if TYPE_CHECKING:
    from psycopg2.extensions import connection as Connection

logger = logging.getLogger(__name__)


@dataclass
class DownloadConfig:
    """Configuration for attachment downloads."""

    # Maximum file size to download (default: 50MB)
    max_size_bytes: int = field(
        default_factory=lambda: int(os.getenv("ATTACHMENT_MAX_SIZE", str(50 * 1024 * 1024)))
    )

    # Request timeout in seconds
    request_timeout: int = field(default_factory=lambda: int(os.getenv("ATTACHMENT_TIMEOUT", "60")))

    # Number of retries for failed requests
    max_retries: int = field(default_factory=lambda: int(os.getenv("ATTACHMENT_MAX_RETRIES", "3")))

    # Delay between retries in seconds
    retry_delay: float = field(
        default_factory=lambda: float(os.getenv("ATTACHMENT_RETRY_DELAY", "1.0"))
    )

    # User-Agent header for requests
    user_agent: str = field(
        default_factory=lambda: os.getenv(
            "ATTACHMENT_USER_AGENT",
            "ruian2pg-scraper/1.0 (+https://github.com/lksv/ruian2pg)",
        )
    )

    # Skip SSL verification (some servers have invalid certs)
    skip_ssl_verify: bool = field(
        default_factory=lambda: os.getenv("ATTACHMENT_SKIP_SSL_VERIFY", "false").lower()
        in ("true", "1", "yes")
    )

    # Batch size for database queries
    batch_size: int = field(default_factory=lambda: int(os.getenv("ATTACHMENT_BATCH_SIZE", "100")))

    # Verbose logging
    verbose: bool = False

    # Date filters for document published_at
    published_after: date | None = None
    published_before: date | None = None


@dataclass
class PendingAttachment:
    """Attachment record pending download."""

    id: int
    document_id: int
    notice_board_id: int
    orig_url: str
    filename: str
    mime_type: str | None
    board_name: str | None = None


@dataclass
class DownloadResult:
    """Result of a single attachment download."""

    attachment_id: int
    success: bool
    file_size: int | None = None
    sha256_hash: str | None = None
    storage_path: str | None = None
    error: str | None = None


@dataclass
class DownloadStats:
    """Statistics for a download session."""

    total_pending: int = 0
    processed: int = 0
    downloaded: int = 0
    skipped: int = 0
    failed: int = 0
    total_bytes: int = 0

    def __str__(self) -> str:
        return (
            f"Processed: {self.processed}/{self.total_pending}, "
            f"Downloaded: {self.downloaded}, "
            f"Skipped: {self.skipped}, "
            f"Failed: {self.failed}, "
            f"Total size: {self.total_bytes / (1024 * 1024):.1f} MB"
        )


class AttachmentDownloader:
    """Service for downloading missing attachment content.

    Downloads files for attachments that have orig_url but no content
    (empty storage_path and NULL file_size_bytes).

    Example:
        downloader = AttachmentDownloader(conn, Path("data/attachments"))

        # Download all pending
        stats = downloader.download_all()

        # Download with progress callback
        def on_progress(result):
            print(f"Downloaded: {result.attachment_id}")
        stats = downloader.download_all(on_progress=on_progress)

        # Dry run (query only, no downloads)
        pending = list(downloader.iter_pending_attachments(limit=10))
    """

    def __init__(
        self,
        conn: "Connection",
        storage_path: Path,
        config: DownloadConfig | None = None,
        storage: StorageBackend | None = None,
    ) -> None:
        """Initialize downloader.

        Args:
            conn: Database connection.
            storage_path: Path for storing downloaded files.
            config: Download configuration (optional).
            storage: Storage backend (optional, created from storage_path if not provided).
        """
        self.conn = conn
        self.config = config or DownloadConfig()
        self.storage_path = storage_path

        if storage:
            self.storage = storage
        else:
            storage_path.mkdir(parents=True, exist_ok=True)
            self.storage = FilesystemStorage(storage_path)

        self._client: httpx.Client | None = None

    def __enter__(self) -> "AttachmentDownloader":
        """Context manager entry."""
        self._client = self._create_client()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        """Context manager exit."""
        if self._client:
            self._client.close()
            self._client = None

    def _create_client(self) -> httpx.Client:
        """Create HTTP client with configured settings."""
        return httpx.Client(
            timeout=httpx.Timeout(self.config.request_timeout),
            follow_redirects=True,
            verify=not self.config.skip_ssl_verify,
            headers={"User-Agent": self.config.user_agent},
        )

    @property
    def client(self) -> httpx.Client:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = self._create_client()
        return self._client

    def get_pending_count(
        self,
        board_id: int | None = None,
        document_id: int | None = None,
        published_after: date | None = None,
        published_before: date | None = None,
    ) -> int:
        """Get count of attachments pending download.

        Args:
            board_id: Filter by notice board ID.
            document_id: Filter by document ID.
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

        with self.conn.cursor() as cur:
            query = """
                SELECT COUNT(*)
                FROM attachments a
                JOIN documents d ON d.id = a.document_id
                WHERE a.download_status = %s
                  AND a.orig_url IS NOT NULL
                  AND a.orig_url != ''
            """
            params: list[str | int | date] = [DownloadStatus.PENDING]

            if board_id is not None:
                query += " AND d.notice_board_id = %s"
                params.append(board_id)

            if document_id is not None:
                query += " AND a.document_id = %s"
                params.append(document_id)

            if published_after is not None:
                query += " AND d.published_at >= %s"
                params.append(published_after)

            if published_before is not None:
                query += " AND d.published_at <= %s"
                params.append(published_before)

            cur.execute(query, params)
            result = cur.fetchone()
            return result[0] if result else 0

    def iter_pending_attachments(
        self,
        board_id: int | None = None,
        document_id: int | None = None,
        limit: int | None = None,
        offset: int = 0,
        published_after: date | None = None,
        published_before: date | None = None,
    ) -> Iterator[PendingAttachment]:
        """Iterate over attachments pending download.

        Yields attachments that have download_status='pending' and orig_url.

        Args:
            board_id: Filter by notice board ID.
            document_id: Filter by document ID.
            limit: Maximum number of attachments to return.
            offset: Number of attachments to skip.
            published_after: Filter documents published on or after this date.
            published_before: Filter documents published on or before this date.

        Yields:
            PendingAttachment objects.
        """
        # Use config date filters if not overridden
        if published_after is None:
            published_after = self.config.published_after
        if published_before is None:
            published_before = self.config.published_before

        with self.conn.cursor() as cur:
            query = """
                SELECT a.id, a.document_id, d.notice_board_id,
                       a.orig_url, a.filename, a.mime_type, nb.name
                FROM attachments a
                JOIN documents d ON d.id = a.document_id
                LEFT JOIN notice_boards nb ON nb.id = d.notice_board_id
                WHERE a.download_status = %s
                  AND a.orig_url IS NOT NULL
                  AND a.orig_url != ''
            """
            params: list[str | int | date] = [DownloadStatus.PENDING]

            if board_id is not None:
                query += " AND d.notice_board_id = %s"
                params.append(board_id)

            if document_id is not None:
                query += " AND a.document_id = %s"
                params.append(document_id)

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
                yield PendingAttachment(
                    id=row[0],
                    document_id=row[1],
                    notice_board_id=row[2],
                    orig_url=row[3],
                    filename=row[4] or "unknown",
                    mime_type=row[5],
                    board_name=row[6],
                )

    def get_pending_attachments(
        self,
        board_id: int | None = None,
        document_id: int | None = None,
        limit: int | None = None,
        offset: int = 0,
        published_after: date | None = None,
        published_before: date | None = None,
    ) -> list[PendingAttachment]:
        """Get list of attachments pending download.

        Args:
            board_id: Filter by notice board ID.
            document_id: Filter by document ID.
            limit: Maximum number of attachments to return.
            offset: Number of attachments to skip.
            published_after: Filter documents published on or after this date.
            published_before: Filter documents published on or before this date.

        Returns:
            List of PendingAttachment objects.
        """
        return list(
            self.iter_pending_attachments(
                board_id=board_id,
                document_id=document_id,
                limit=limit,
                offset=offset,
                published_after=published_after,
                published_before=published_before,
            )
        )

    def download_attachment(self, attachment: PendingAttachment) -> DownloadResult:
        """Download a single attachment.

        Args:
            attachment: Attachment to download.

        Returns:
            DownloadResult with success/failure info.
        """
        try:
            # Download content
            content = self._download_url(attachment.orig_url)
            if content is None:
                return DownloadResult(
                    attachment_id=attachment.id,
                    success=False,
                    error="Download failed or empty response",
                )

            # Check size limit
            if len(content) > self.config.max_size_bytes:
                return DownloadResult(
                    attachment_id=attachment.id,
                    success=False,
                    error=f"File too large: {len(content)} bytes > {self.config.max_size_bytes}",
                )

            # Compute hash and save
            sha256_hash = self.storage.compute_hash(content)
            storage_path = f"{attachment.document_id}/{attachment.filename}"

            try:
                self.storage.save(storage_path, content)
            except Exception as e:
                return DownloadResult(
                    attachment_id=attachment.id,
                    success=False,
                    error=f"Storage error: {e}",
                )

            # Update database
            self._update_attachment(
                attachment_id=attachment.id,
                storage_path=storage_path,
                file_size=len(content),
                sha256_hash=sha256_hash,
            )

            if self.config.verbose:
                logger.info(
                    f"Downloaded attachment {attachment.id}: "
                    f"{attachment.filename} ({len(content)} bytes)"
                )

            return DownloadResult(
                attachment_id=attachment.id,
                success=True,
                file_size=len(content),
                sha256_hash=sha256_hash,
                storage_path=storage_path,
            )

        except Exception as e:
            logger.warning(f"Error downloading attachment {attachment.id}: {e}")
            return DownloadResult(
                attachment_id=attachment.id,
                success=False,
                error=str(e),
            )

    def _download_url(self, url: str) -> bytes | None:
        """Download content from URL.

        Args:
            url: URL to download.

        Returns:
            Content bytes or None on failure.
        """
        for attempt in range(self.config.max_retries):
            try:
                response = self.client.get(url)
                response.raise_for_status()
                return response.content
            except httpx.HTTPStatusError as e:
                logger.warning(f"HTTP error downloading {url}: {e.response.status_code}")
                if e.response.status_code in (404, 403, 410):
                    # Don't retry for permanent errors
                    return None
            except httpx.RequestError as e:
                logger.warning(f"Request error downloading {url}: {e}")

            if attempt < self.config.max_retries - 1:
                import time

                time.sleep(self.config.retry_delay)

        return None

    def _update_attachment(
        self,
        attachment_id: int,
        storage_path: str,
        file_size: int,
        sha256_hash: str,
    ) -> None:
        """Update attachment record with downloaded content info."""
        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE attachments
                SET storage_path = %s,
                    file_size_bytes = %s,
                    sha256_hash = %s,
                    download_status = %s
                WHERE id = %s
                """,
                (storage_path, file_size, sha256_hash, DownloadStatus.DOWNLOADED, attachment_id),
            )
        self.conn.commit()

    def download_all(
        self,
        board_id: int | None = None,
        document_id: int | None = None,
        limit: int | None = None,
        on_progress: "Callable[[DownloadResult], None] | None" = None,  # noqa: F821
    ) -> DownloadStats:
        """Download all pending attachments.

        Args:
            board_id: Filter by notice board ID.
            document_id: Filter by document ID.
            limit: Maximum number of attachments to download.
            on_progress: Callback called after each download.

        Returns:
            DownloadStats with totals.
        """
        stats = DownloadStats()
        stats.total_pending = self.get_pending_count(board_id=board_id, document_id=document_id)

        effective_limit = limit if limit else stats.total_pending

        for attachment in self.iter_pending_attachments(
            board_id=board_id,
            document_id=document_id,
            limit=effective_limit,
        ):
            result = self.download_attachment(attachment)
            stats.processed += 1

            if result.success:
                stats.downloaded += 1
                stats.total_bytes += result.file_size or 0
            else:
                stats.failed += 1

            if on_progress:
                on_progress(result)

        return stats

    def download_by_board(
        self,
        board_id: int,
        limit: int | None = None,
        on_progress: "Callable[[DownloadResult], None] | None" = None,  # noqa: F821
    ) -> DownloadStats:
        """Download pending attachments for a specific board.

        Args:
            board_id: Notice board ID.
            limit: Maximum number of attachments to download.
            on_progress: Callback called after each download.

        Returns:
            DownloadStats with totals.
        """
        return self.download_all(
            board_id=board_id,
            limit=limit,
            on_progress=on_progress,
        )

    def download_by_document(
        self,
        document_id: int,
        on_progress: "Callable[[DownloadResult], None] | None" = None,  # noqa: F821
    ) -> DownloadStats:
        """Download pending attachments for a specific document.

        Args:
            document_id: Document ID.
            on_progress: Callback called after each download.

        Returns:
            DownloadStats with totals.
        """
        return self.download_all(
            document_id=document_id,
            on_progress=on_progress,
        )

    def get_stats(self, board_id: int | None = None) -> dict[str, int]:
        """Get attachment statistics.

        Args:
            board_id: Filter by notice board ID (optional).

        Returns:
            Dict with counts for total, downloaded, pending, failed, removed, etc.
        """
        with self.conn.cursor() as cur:
            query = """
                SELECT
                    COUNT(*) AS total,
                    COUNT(CASE WHEN a.download_status = 'downloaded' THEN 1 END) AS downloaded,
                    COUNT(CASE WHEN a.download_status = 'pending' THEN 1 END) AS pending,
                    COUNT(CASE WHEN a.download_status = 'failed' THEN 1 END) AS failed,
                    COUNT(CASE WHEN a.download_status = 'removed' THEN 1 END) AS removed,
                    COALESCE(SUM(a.file_size_bytes), 0) AS total_bytes
                FROM attachments a
            """
            params: list[int] = []
            if board_id is not None:
                query += " JOIN documents d ON d.id = a.document_id WHERE d.notice_board_id = %s"
                params.append(board_id)

            cur.execute(query, params)
            row = cur.fetchone()
            if row is None:
                return {
                    "total": 0,
                    "downloaded": 0,
                    "pending": 0,
                    "failed": 0,
                    "removed": 0,
                    "total_bytes": 0,
                }
            return {
                "total": row[0],
                "downloaded": row[1],
                "pending": row[2],
                "failed": row[3],
                "removed": row[4],
                "total_bytes": row[5],
            }

    def get_stats_by_board(self) -> list[dict[str, int | str | None]]:
        """Get attachment statistics grouped by notice board.

        Returns:
            List of dicts with board_id, board_name, total, downloaded, pending counts.
        """
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    nb.id AS board_id,
                    nb.name AS board_name,
                    COUNT(a.id) AS total,
                    COUNT(CASE WHEN a.download_status = 'downloaded' THEN 1 END) AS downloaded,
                    COUNT(CASE WHEN a.download_status = 'pending' THEN 1 END) AS pending,
                    COUNT(CASE WHEN a.download_status = 'failed' THEN 1 END) AS failed
                FROM notice_boards nb
                JOIN documents d ON d.notice_board_id = nb.id
                JOIN attachments a ON a.document_id = d.id
                GROUP BY nb.id, nb.name
                HAVING COUNT(CASE WHEN a.download_status = 'pending' THEN 1 END) > 0
                ORDER BY pending DESC
                """
            )
            return [
                {
                    "board_id": row[0],
                    "board_name": row[1],
                    "total": row[2],
                    "downloaded": row[3],
                    "pending": row[4],
                    "failed": row[5],
                }
                for row in cur.fetchall()
            ]

    def get_mime_type_from_url(self, url: str) -> str | None:
        """Guess MIME type from URL.

        Args:
            url: URL to check.

        Returns:
            MIME type or None.
        """
        # Extract filename from URL
        from urllib.parse import unquote, urlparse

        path = urlparse(url).path
        filename = unquote(path.split("/")[-1])
        mime_type, _ = mimetypes.guess_type(filename)
        return mime_type

    def get_status_counts(self) -> dict[str, int]:
        """Get counts by download_status.

        Returns:
            Dict with counts for each status.
        """
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT download_status, COUNT(*)
                FROM attachments
                GROUP BY download_status
                """
            )
            return {row[0]: row[1] for row in cur.fetchall()}

    def mark_removed(self, attachment_ids: list[int]) -> int:
        """Mark attachments as removed (won't be downloaded).

        Args:
            attachment_ids: List of attachment IDs to mark.

        Returns:
            Number of attachments marked.
        """
        if not attachment_ids:
            return 0

        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE attachments
                SET download_status = %s
                WHERE id = ANY(%s)
                  AND download_status IN (%s, %s)
                """,
                (
                    DownloadStatus.REMOVED,
                    attachment_ids,
                    DownloadStatus.PENDING,
                    DownloadStatus.FAILED,
                ),
            )
            count: int = cur.rowcount or 0
        self.conn.commit()
        return count

    def mark_failed(self, attachment_id: int, error: str | None = None) -> None:
        """Mark attachment as failed.

        Args:
            attachment_id: Attachment ID.
            error: Optional error message.
        """
        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE attachments
                SET download_status = %s,
                    parse_error = COALESCE(%s, parse_error)
                WHERE id = %s
                """,
                (DownloadStatus.FAILED, error, attachment_id),
            )
        self.conn.commit()

    def reset_to_pending(self, failed_only: bool = True) -> int:
        """Reset attachments to pending for retry.

        Args:
            failed_only: If True, only reset 'failed' status.
                        If False, also reset 'removed'.

        Returns:
            Number of attachments reset.
        """
        statuses = [DownloadStatus.FAILED]
        if not failed_only:
            statuses.append(DownloadStatus.REMOVED)

        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE attachments
                SET download_status = %s,
                    parse_error = NULL
                WHERE download_status = ANY(%s)
                  AND orig_url IS NOT NULL
                  AND orig_url != ''
                """,
                (DownloadStatus.PENDING, statuses),
            )
            count: int = cur.rowcount or 0
        self.conn.commit()
        return count

    def get_attachment_content(
        self,
        attachment_id: int,
        persist: bool = False,
    ) -> bytes | None:
        """Get attachment content - from storage or by downloading.

        Unified API for accessing attachment content. TextExtractionService
        will use this method regardless of whether file is already stored.

        Logic:
        1. If storage_path exists and file is in storage -> return from storage
        2. If no storage_path but orig_url exists -> download
           - If persist=True -> save to storage, update DB
           - If persist=False -> return content without saving
        3. If neither -> return None

        Args:
            attachment_id: Database ID of attachment.
            persist: If downloading, whether to save file to storage.

        Returns:
            File content as bytes, or None if unavailable.
        """
        # Get attachment info from DB
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT a.id, a.document_id, a.storage_path, a.orig_url, a.filename
                FROM attachments a
                WHERE a.id = %s
                """,
                (attachment_id,),
            )
            row = cur.fetchone()
            if row is None:
                logger.warning(f"Attachment {attachment_id} not found")
                return None

        _, document_id, storage_path, orig_url, filename = row

        # Try to load from storage first
        if storage_path:
            try:
                content = self.storage.load(storage_path)
                if content:
                    return content
            except Exception as e:
                logger.warning(f"Failed to load attachment {attachment_id} from storage: {e}")

        # Try to download if we have URL
        if not orig_url:
            logger.warning(f"Attachment {attachment_id} has no orig_url")
            return None

        downloaded = self._download_url(orig_url)
        if downloaded is None:
            logger.warning(f"Failed to download attachment {attachment_id}")
            return None
        content = downloaded

        # Persist if requested
        if persist:
            try:
                sha256_hash = self.storage.compute_hash(content)
                new_storage_path = f"{document_id}/{filename or 'unknown'}"
                self.storage.save(new_storage_path, content)
                self._update_attachment(
                    attachment_id=attachment_id,
                    storage_path=new_storage_path,
                    file_size=len(content),
                    sha256_hash=sha256_hash,
                )
            except Exception as e:
                logger.warning(f"Failed to persist attachment {attachment_id}: {e}")
                # Still return content even if persist failed

        return content

    def get_attachments_by_status(
        self,
        status: str,
        limit: int | None = None,
        published_after: date | None = None,
        published_before: date | None = None,
    ) -> list[PendingAttachment]:
        """Get attachments by download status.

        Args:
            status: Download status to filter by.
            limit: Maximum number of attachments to return.
            published_after: Filter documents published on or after this date.
            published_before: Filter documents published on or before this date.

        Returns:
            List of PendingAttachment objects.
        """
        # Use config date filters if not overridden
        if published_after is None:
            published_after = self.config.published_after
        if published_before is None:
            published_before = self.config.published_before

        with self.conn.cursor() as cur:
            query = """
                SELECT a.id, a.document_id, d.notice_board_id,
                       a.orig_url, a.filename, a.mime_type, nb.name
                FROM attachments a
                JOIN documents d ON d.id = a.document_id
                LEFT JOIN notice_boards nb ON nb.id = d.notice_board_id
                WHERE a.download_status = %s
            """
            params: list[str | int | date] = [status]

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

            cur.execute(query, params)

            return [
                PendingAttachment(
                    id=row[0],
                    document_id=row[1],
                    notice_board_id=row[2],
                    orig_url=row[3] or "",
                    filename=row[4] or "unknown",
                    mime_type=row[5],
                    board_name=row[6],
                )
                for row in cur.fetchall()
            ]

    def mark_removed_by_date(
        self,
        published_before: date,
    ) -> int:
        """Mark attachments as removed based on document publication date.

        Args:
            published_before: Mark attachments for documents published before this date.

        Returns:
            Number of attachments marked.
        """
        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE attachments a
                SET download_status = %s
                FROM documents d
                WHERE a.document_id = d.id
                  AND d.published_at < %s
                  AND a.download_status IN (%s, %s)
                """,
                (
                    DownloadStatus.REMOVED,
                    published_before,
                    DownloadStatus.PENDING,
                    DownloadStatus.FAILED,
                ),
            )
            count: int = cur.rowcount or 0
        self.conn.commit()
        return count
