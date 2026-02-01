"""Repository for notice board documents and attachments.

Provides database operations for storing scraped documents with
upsert logic to handle incremental updates.
"""

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from notice_boards.models import NoticeBoard
from notice_boards.scrapers.base import AttachmentData, DocumentData
from notice_boards.storage import FilesystemStorage, StorageBackend

if TYPE_CHECKING:
    from psycopg2.extensions import connection as Connection

logger = logging.getLogger(__name__)


class DocumentRepository:
    """Repository for documents and attachments.

    Handles database operations and file storage for scraped documents.

    Example:
        repo = DocumentRepository(conn, storage)
        doc_id = repo.upsert_document(notice_board_id, doc_data)
        repo.mark_scrape_complete(notice_board_id)
    """

    def __init__(
        self,
        conn: "Connection",
        storage: StorageBackend | None = None,
        text_storage: StorageBackend | None = None,
    ) -> None:
        """Initialize repository.

        Args:
            conn: Database connection.
            storage: Storage backend for attachments (optional).
            text_storage: Storage backend for extracted text (optional).
        """
        self.conn = conn
        self.storage = storage
        self.text_storage = text_storage

    def upsert_document(
        self,
        notice_board_id: int,
        doc_data: DocumentData,
        download_text: bool = False,
    ) -> int:
        """Insert or update a document.

        Uses ON CONFLICT on (notice_board_id, external_id) for upsert.

        Args:
            notice_board_id: ID of the notice board.
            doc_data: Scraped document data.
            download_text: Whether to save extracted text.

        Returns:
            Document ID (new or existing).
        """
        # Extract eDesky-specific fields from metadata
        edesky_url = doc_data.metadata.get("edesky_url")
        orig_url = doc_data.metadata.get("orig_url")
        extracted_text = doc_data.metadata.get("extracted_text")

        # Save extracted text to storage if provided and storage is configured
        extracted_text_path = None
        if download_text and isinstance(extracted_text, str) and self.text_storage:
            text_content: str = extracted_text
            text_path = f"{notice_board_id}/{doc_data.external_id}.txt"
            try:
                self.text_storage.save(text_path, text_content.encode("utf-8"))
                extracted_text_path = text_path
                logger.debug(f"Saved text to {text_path}")
            except Exception as e:
                logger.warning(f"Failed to save text for document {doc_data.external_id}: {e}")

        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO documents (
                    notice_board_id, external_id, title, description,
                    published_at, valid_from, valid_until,
                    source_metadata, source_document_type,
                    edesky_url, orig_url, extracted_text_path,
                    updated_at
                ) VALUES (
                    %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s,
                    %s, %s, %s,
                    NOW()
                )
                ON CONFLICT (notice_board_id, external_id)
                DO UPDATE SET
                    title = EXCLUDED.title,
                    description = EXCLUDED.description,
                    published_at = EXCLUDED.published_at,
                    valid_from = EXCLUDED.valid_from,
                    valid_until = EXCLUDED.valid_until,
                    source_metadata = EXCLUDED.source_metadata,
                    source_document_type = EXCLUDED.source_document_type,
                    edesky_url = EXCLUDED.edesky_url,
                    orig_url = EXCLUDED.orig_url,
                    extracted_text_path = COALESCE(
                        EXCLUDED.extracted_text_path, documents.extracted_text_path
                    ),
                    updated_at = NOW()
                RETURNING id
                """,
                (
                    notice_board_id,
                    doc_data.external_id,
                    doc_data.title[:1024] if doc_data.title else "",
                    doc_data.description,
                    doc_data.published_at,
                    doc_data.valid_from,
                    doc_data.valid_until,
                    self._serialize_metadata(doc_data.metadata),
                    doc_data.source_type,
                    edesky_url,
                    orig_url,
                    extracted_text_path,
                ),
            )
            result = cur.fetchone()
            doc_id: int = result[0] if result else 0

        self.conn.commit()
        return doc_id

    def upsert_attachment(
        self,
        document_id: int,
        att_data: AttachmentData,
        position: int = 0,
    ) -> int | None:
        """Insert or update an attachment.

        If attachment content is provided, saves to storage.
        Uses ON CONFLICT on (document_id, filename) for upsert.

        Args:
            document_id: ID of the parent document.
            att_data: Attachment data from scraping.
            position: Position/order of attachment in document.

        Returns:
            Attachment ID or None if skipped.
        """
        storage_path = ""
        file_size = None
        sha256_hash = None

        # Save content to storage if provided
        if att_data.content and self.storage:
            # Generate storage path
            storage_path = f"{document_id}/{att_data.filename}"
            file_size = len(att_data.content)

            try:
                sha256_hash = self.storage.compute_hash(att_data.content)
                self.storage.save(storage_path, att_data.content)
                logger.debug(f"Saved attachment to {storage_path}")
            except Exception as e:
                logger.warning(f"Failed to save attachment {att_data.filename}: {e}")
                storage_path = ""

        with self.conn.cursor() as cur:
            # Use ON CONFLICT DO NOTHING for deduplication by orig_url
            cur.execute(
                """
                INSERT INTO attachments (
                    document_id, filename, mime_type,
                    file_size_bytes, storage_path, sha256_hash,
                    orig_url, position
                ) VALUES (
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s
                )
                ON CONFLICT (document_id, orig_url)
                WHERE orig_url IS NOT NULL
                DO UPDATE SET
                    filename = EXCLUDED.filename,
                    mime_type = EXCLUDED.mime_type,
                    file_size_bytes = COALESCE(
                        EXCLUDED.file_size_bytes, attachments.file_size_bytes
                    ),
                    storage_path = CASE
                        WHEN EXCLUDED.storage_path != '' THEN EXCLUDED.storage_path
                        ELSE attachments.storage_path
                    END,
                    sha256_hash = COALESCE(EXCLUDED.sha256_hash, attachments.sha256_hash),
                    position = EXCLUDED.position
                RETURNING id
                """,
                (
                    document_id,
                    att_data.filename[:512] if att_data.filename else "unknown",
                    att_data.mime_type or "application/octet-stream",
                    file_size,
                    storage_path,
                    sha256_hash,
                    att_data.url,
                    position,
                ),
            )
            result = cur.fetchone()
            att_id: int | None = result[0] if result else None

        self.conn.commit()
        return att_id

    def get_existing_external_ids(self, notice_board_id: int) -> set[str]:
        """Get external IDs of documents already in database.

        Used for incremental updates to skip already imported documents.

        Args:
            notice_board_id: ID of the notice board.

        Returns:
            Set of external_id values.
        """
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT external_id FROM documents
                WHERE notice_board_id = %s AND external_id IS NOT NULL
                """,
                (notice_board_id,),
            )
            return {row[0] for row in cur.fetchall()}

    def mark_scrape_complete(self, notice_board_id: int) -> None:
        """Update last_scraped_at timestamp for a notice board.

        Args:
            notice_board_id: ID of the notice board.
        """
        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE notice_boards
                SET last_scraped_at = NOW(), updated_at = NOW()
                WHERE id = %s
                """,
                (notice_board_id,),
            )
        self.conn.commit()

    def get_notice_board_by_edesky_id(self, edesky_id: int) -> NoticeBoard | None:
        """Find notice board by eDesky ID.

        Args:
            edesky_id: eDesky board ID.

        Returns:
            NoticeBoard or None if not found.
        """
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, municipality_code, name, ico, edesky_url,
                       edesky_id, edesky_category,
                       nuts3_id, nuts3_name, nuts4_id, nuts4_name,
                       edesky_parent_id, edesky_parent_name
                FROM notice_boards
                WHERE edesky_id = %s
                """,
                (edesky_id,),
            )
            row = cur.fetchone()
            if not row:
                return None

            return NoticeBoard(
                id=row[0],
                municipality_code=row[1],
                name=row[2],
                ico=row[3],
                edesky_url=row[4],
                edesky_id=row[5],
                edesky_category=row[6],
                nuts3_id=row[7],
                nuts3_name=row[8],
                nuts4_id=row[9],
                nuts4_name=row[10],
                edesky_parent_id=row[11],
                edesky_parent_name=row[12],
            )

    def get_notice_board_by_name(self, name: str) -> NoticeBoard | None:
        """Find notice board by name (case-insensitive).

        Args:
            name: Board name to search for.

        Returns:
            NoticeBoard or None if not found.
        """
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, municipality_code, name, ico, edesky_url,
                       edesky_id, edesky_category,
                       nuts3_id, nuts3_name, nuts4_id, nuts4_name,
                       edesky_parent_id, edesky_parent_name
                FROM notice_boards
                WHERE LOWER(name) = LOWER(%s)
                LIMIT 1
                """,
                (name,),
            )
            row = cur.fetchone()
            if not row:
                return None

            return NoticeBoard(
                id=row[0],
                municipality_code=row[1],
                name=row[2],
                ico=row[3],
                edesky_url=row[4],
                edesky_id=row[5],
                edesky_category=row[6],
                nuts3_id=row[7],
                nuts3_name=row[8],
                nuts4_id=row[9],
                nuts4_name=row[10],
                edesky_parent_id=row[11],
                edesky_parent_name=row[12],
            )

    def upsert_notice_board_from_edesky(
        self,
        edesky_id: int,
        name: str,
        category: str | None = None,
        ico: str | None = None,
        nuts3_id: int | None = None,
        nuts3_name: str | None = None,
        nuts4_id: int | None = None,
        nuts4_name: str | None = None,
        parent_id: int | None = None,
        parent_name: str | None = None,
        url: str | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
    ) -> int:
        """Insert or update notice board from eDesky data.

        Uses ON CONFLICT on edesky_id for upsert.

        Args:
            edesky_id: eDesky board ID.
            name: Board name.
            category: Board category (obec, mesto, kraj, etc.).
            ico: Organization IČO.
            nuts3_id: Region ID.
            nuts3_name: Region name.
            nuts4_id: District ID.
            nuts4_name: District name.
            parent_id: Parent board ID.
            parent_name: Parent board name.
            url: Board URL.
            latitude: Latitude coordinate.
            longitude: Longitude coordinate.

        Returns:
            Notice board ID.
        """
        edesky_url = f"https://edesky.cz/desky/{edesky_id}"

        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO notice_boards (
                    name, edesky_id, edesky_url, edesky_category, ico,
                    nuts3_id, nuts3_name, nuts4_id, nuts4_name,
                    edesky_parent_id, edesky_parent_name,
                    source_url, latitude, longitude,
                    updated_at
                ) VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s,
                    %s, %s, %s,
                    NOW()
                )
                ON CONFLICT (edesky_id) WHERE edesky_id IS NOT NULL
                DO UPDATE SET
                    name = EXCLUDED.name,
                    edesky_url = EXCLUDED.edesky_url,
                    edesky_category = EXCLUDED.edesky_category,
                    ico = COALESCE(EXCLUDED.ico, notice_boards.ico),
                    nuts3_id = EXCLUDED.nuts3_id,
                    nuts3_name = EXCLUDED.nuts3_name,
                    nuts4_id = EXCLUDED.nuts4_id,
                    nuts4_name = EXCLUDED.nuts4_name,
                    edesky_parent_id = EXCLUDED.edesky_parent_id,
                    edesky_parent_name = EXCLUDED.edesky_parent_name,
                    source_url = COALESCE(EXCLUDED.source_url, notice_boards.source_url),
                    latitude = COALESCE(EXCLUDED.latitude, notice_boards.latitude),
                    longitude = COALESCE(EXCLUDED.longitude, notice_boards.longitude),
                    updated_at = NOW()
                RETURNING id
                """,
                (
                    name,
                    edesky_id,
                    edesky_url,
                    category,
                    ico,
                    nuts3_id,
                    nuts3_name,
                    nuts4_id,
                    nuts4_name,
                    parent_id,
                    parent_name,
                    url,
                    latitude,
                    longitude,
                ),
            )
            result = cur.fetchone()
            board_id: int = result[0] if result else 0

        self.conn.commit()
        return board_id

    def get_document_count(self, notice_board_id: int | None = None) -> int:
        """Get count of documents.

        Args:
            notice_board_id: Optional filter by notice board.

        Returns:
            Number of documents.
        """
        with self.conn.cursor() as cur:
            if notice_board_id:
                cur.execute(
                    "SELECT COUNT(*) FROM documents WHERE notice_board_id = %s",
                    (notice_board_id,),
                )
            else:
                cur.execute("SELECT COUNT(*) FROM documents")
            result = cur.fetchone()
            return result[0] if result else 0

    def get_attachment_count(self, notice_board_id: int | None = None) -> int:
        """Get count of attachments.

        Args:
            notice_board_id: Optional filter by notice board.

        Returns:
            Number of attachments.
        """
        with self.conn.cursor() as cur:
            if notice_board_id:
                cur.execute(
                    """
                    SELECT COUNT(*) FROM attachments a
                    JOIN documents d ON d.id = a.document_id
                    WHERE d.notice_board_id = %s
                    """,
                    (notice_board_id,),
                )
            else:
                cur.execute("SELECT COUNT(*) FROM attachments")
            result = cur.fetchone()
            return result[0] if result else 0

    def get_boards_with_edesky_id(self) -> list[tuple[int, int, str]]:
        """Get all notice boards with eDesky ID.

        Returns:
            List of (id, edesky_id, name) tuples.
        """
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, edesky_id, name
                FROM notice_boards
                WHERE edesky_id IS NOT NULL
                ORDER BY name
                """
            )
            return [(row[0], row[1], row[2]) for row in cur.fetchall()]

    def get_notice_board_by_edesky_url(self, edesky_url: str) -> NoticeBoard | None:
        """Find notice board by eDesky URL column value.

        Searches the edesky_url column directly. Also tries to match
        by extracting edesky_id from the URL.

        Args:
            edesky_url: eDesky URL (e.g., https://edesky.cz/desky/123).

        Returns:
            NoticeBoard or None if not found.
        """
        # First try exact URL match in edesky_url column
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, municipality_code, name, ico, edesky_url,
                       edesky_id, edesky_category,
                       nuts3_id, nuts3_name, nuts4_id, nuts4_name,
                       edesky_parent_id, edesky_parent_name, data_box_id
                FROM notice_boards
                WHERE edesky_url = %s
                LIMIT 1
                """,
                (edesky_url,),
            )
            row = cur.fetchone()
            if row:
                return NoticeBoard(
                    id=row[0],
                    municipality_code=row[1],
                    name=row[2],
                    ico=row[3],
                    edesky_url=row[4],
                    edesky_id=row[5],
                    edesky_category=row[6],
                    nuts3_id=row[7],
                    nuts3_name=row[8],
                    nuts4_id=row[9],
                    nuts4_name=row[10],
                    edesky_parent_id=row[11],
                    edesky_parent_name=row[12],
                    data_box_id=row[13],
                )

        # Fallback: extract edesky_id from URL and look up by edesky_id
        import re

        match = re.search(r"/desky/(\d+)", edesky_url)
        if match:
            edesky_id = int(match.group(1))
            return self.get_notice_board_by_edesky_id(edesky_id)

        return None

    def get_notice_boards_by_ico(self, ico: str) -> list[NoticeBoard]:
        """Find all notice boards with given ICO.

        Note: One organization (ICO) may have multiple notice boards.

        Args:
            ico: Organization identification number (IČO).

        Returns:
            List of NoticeBoard objects (may be empty or have multiple entries).
        """
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, municipality_code, name, ico, edesky_url,
                       edesky_id, edesky_category,
                       nuts3_id, nuts3_name, nuts4_id, nuts4_name,
                       edesky_parent_id, edesky_parent_name, data_box_id
                FROM notice_boards
                WHERE ico = %s
                ORDER BY name
                """,
                (ico,),
            )
            return [
                NoticeBoard(
                    id=row[0],
                    municipality_code=row[1],
                    name=row[2],
                    ico=row[3],
                    edesky_url=row[4],
                    edesky_id=row[5],
                    edesky_category=row[6],
                    nuts3_id=row[7],
                    nuts3_name=row[8],
                    nuts4_id=row[9],
                    nuts4_name=row[10],
                    edesky_parent_id=row[11],
                    edesky_parent_name=row[12],
                    data_box_id=row[13],
                )
                for row in cur.fetchall()
            ]

    def get_notice_board_by_data_box(self, data_box_id: str) -> NoticeBoard | None:
        """Find notice board by data box ID.

        Data box ID (datová schránka) is unique per organization.

        Args:
            data_box_id: Data box identifier.

        Returns:
            NoticeBoard or None if not found.
        """
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, municipality_code, name, ico, edesky_url,
                       edesky_id, edesky_category,
                       nuts3_id, nuts3_name, nuts4_id, nuts4_name,
                       edesky_parent_id, edesky_parent_name, data_box_id
                FROM notice_boards
                WHERE data_box_id = %s
                LIMIT 1
                """,
                (data_box_id,),
            )
            row = cur.fetchone()
            if not row:
                return None

            return NoticeBoard(
                id=row[0],
                municipality_code=row[1],
                name=row[2],
                ico=row[3],
                edesky_url=row[4],
                edesky_id=row[5],
                edesky_category=row[6],
                nuts3_id=row[7],
                nuts3_name=row[8],
                nuts4_id=row[9],
                nuts4_name=row[10],
                edesky_parent_id=row[11],
                edesky_parent_name=row[12],
                data_box_id=row[13],
            )

    def get_notice_boards_by_name_and_district(
        self, name: str, district: str | None = None
    ) -> list[NoticeBoard]:
        """Find notice boards by normalized name, optionally filtered by district.

        Uses case-insensitive matching.

        Args:
            name: Board name to search for.
            district: Optional district name (NUTS4) to filter by.

        Returns:
            List of matching NoticeBoard objects.
        """
        with self.conn.cursor() as cur:
            if district:
                cur.execute(
                    """
                    SELECT id, municipality_code, name, ico, edesky_url,
                           edesky_id, edesky_category,
                           nuts3_id, nuts3_name, nuts4_id, nuts4_name,
                           edesky_parent_id, edesky_parent_name, data_box_id
                    FROM notice_boards
                    WHERE LOWER(name) = LOWER(%s) AND LOWER(nuts4_name) = LOWER(%s)
                    ORDER BY name
                    """,
                    (name, district),
                )
            else:
                cur.execute(
                    """
                    SELECT id, municipality_code, name, ico, edesky_url,
                           edesky_id, edesky_category,
                           nuts3_id, nuts3_name, nuts4_id, nuts4_name,
                           edesky_parent_id, edesky_parent_name, data_box_id
                    FROM notice_boards
                    WHERE LOWER(name) = LOWER(%s)
                    ORDER BY name
                    """,
                    (name,),
                )

            return [
                NoticeBoard(
                    id=row[0],
                    municipality_code=row[1],
                    name=row[2],
                    ico=row[3],
                    edesky_url=row[4],
                    edesky_id=row[5],
                    edesky_category=row[6],
                    nuts3_id=row[7],
                    nuts3_name=row[8],
                    nuts4_id=row[9],
                    nuts4_name=row[10],
                    edesky_parent_id=row[11],
                    edesky_parent_name=row[12],
                    data_box_id=row[13],
                )
                for row in cur.fetchall()
            ]

    def update_notice_board_edesky_fields(
        self,
        board_id: int,
        edesky_id: int,
        edesky_url: str,
        category: str | None = None,
        ico: str | None = None,
        nuts3_id: int | None = None,
        nuts3_name: str | None = None,
        nuts4_id: int | None = None,
        nuts4_name: str | None = None,
        parent_id: int | None = None,
        parent_name: str | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
    ) -> None:
        """Update existing board with eDesky metadata.

        Uses COALESCE to avoid overwriting existing non-null values.

        Args:
            board_id: Database ID of the notice board to update.
            edesky_id: eDesky board ID.
            edesky_url: eDesky URL.
            category: Board category (obec, mesto, kraj, etc.).
            ico: Organization IČO.
            nuts3_id: Region ID.
            nuts3_name: Region name.
            nuts4_id: District ID.
            nuts4_name: District name.
            parent_id: Parent board ID.
            parent_name: Parent board name.
            latitude: Latitude coordinate.
            longitude: Longitude coordinate.
        """
        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE notice_boards SET
                    edesky_id = %s,
                    edesky_url = COALESCE(edesky_url, %s),
                    edesky_category = COALESCE(edesky_category, %s),
                    ico = COALESCE(ico, %s),
                    nuts3_id = COALESCE(nuts3_id, %s),
                    nuts3_name = COALESCE(nuts3_name, %s),
                    nuts4_id = COALESCE(nuts4_id, %s),
                    nuts4_name = COALESCE(nuts4_name, %s),
                    edesky_parent_id = COALESCE(edesky_parent_id, %s),
                    edesky_parent_name = COALESCE(edesky_parent_name, %s),
                    latitude = COALESCE(latitude, %s),
                    longitude = COALESCE(longitude, %s),
                    updated_at = NOW()
                WHERE id = %s
                """,
                (
                    edesky_id,
                    edesky_url,
                    category,
                    ico,
                    nuts3_id,
                    nuts3_name,
                    nuts4_id,
                    nuts4_name,
                    parent_id,
                    parent_name,
                    latitude,
                    longitude,
                    board_id,
                ),
            )
        self.conn.commit()

    def get_boards_missing_edesky_id(self) -> list[tuple[int, str, str | None, str | None]]:
        """Get boards without edesky_id.

        Useful for identifying boards that need to be matched with eDesky.

        Returns:
            List of (id, name, ico, edesky_url) tuples.
        """
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, name, ico, edesky_url
                FROM notice_boards
                WHERE edesky_id IS NULL
                ORDER BY name
                """
            )
            return [(row[0], row[1], row[2], row[3]) for row in cur.fetchall()]

    def get_notice_board_stats(self) -> dict[str, int]:
        """Get statistics about notice boards.

        Returns:
            Dict with counts for total, with_edesky_id, with_ico, etc.
        """
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    COUNT(edesky_id) AS with_edesky_id,
                    COUNT(ico) AS with_ico,
                    COUNT(edesky_url) AS with_edesky_url,
                    COUNT(nuts3_name) AS with_nuts3,
                    COUNT(nuts4_name) AS with_nuts4
                FROM notice_boards
                """
            )
            row = cur.fetchone()
            if row is None:
                return {
                    "total": 0,
                    "with_edesky_id": 0,
                    "with_ico": 0,
                    "with_edesky_url": 0,
                    "with_nuts3": 0,
                    "with_nuts4": 0,
                }
            return {
                "total": row[0],
                "with_edesky_id": row[1],
                "with_ico": row[2],
                "with_edesky_url": row[3],
                "with_nuts3": row[4],
                "with_nuts4": row[5],
            }

    def _serialize_metadata(self, metadata: dict[str, Any]) -> str | None:
        """Serialize metadata dict to JSON string for storage."""
        if not metadata:
            return None

        import json

        # Filter out extracted_text from metadata (stored separately)
        filtered = {k: v for k, v in metadata.items() if k != "extracted_text"}
        return json.dumps(filtered, ensure_ascii=False) if filtered else None


def create_document_repository(
    conn: "Connection",
    attachments_path: Path | None = None,
    text_path: Path | None = None,
) -> DocumentRepository:
    """Factory function to create a DocumentRepository with storage.

    Args:
        conn: Database connection.
        attachments_path: Path for storing attachments (optional).
        text_path: Path for storing extracted text (optional).

    Returns:
        Configured DocumentRepository instance.
    """
    storage = None
    text_storage = None

    if attachments_path:
        attachments_path.mkdir(parents=True, exist_ok=True)
        storage = FilesystemStorage(attachments_path)

    if text_path:
        text_path.mkdir(parents=True, exist_ok=True)
        text_storage = FilesystemStorage(text_path)

    return DocumentRepository(conn, storage, text_storage)
