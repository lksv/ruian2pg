"""Tests for text extraction service."""

from datetime import date
from pathlib import Path

import pytest

from notice_boards.models import DownloadStatus, ParseStatus
from notice_boards.parsers.base import CompositeTextExtractor, TextExtractionError, TextExtractor
from notice_boards.services.sqlite_text_storage import SqliteTextStorage
from notice_boards.services.text_extractor import (
    SUPPORTED_MIME_TYPES,
    ExtractionConfig,
    ExtractionResult,
    ExtractionStats,
    PendingExtraction,
    TextExtractionService,
)


class MockTextExtractor(TextExtractor):
    """Mock extractor for testing."""

    def __init__(self, return_value: str | None = "extracted text") -> None:
        self.return_value = return_value
        self.extract_called = False
        self.last_content: bytes | None = None
        self.last_mime_type: str | None = None

    def supports(self, mime_type: str) -> bool:
        return mime_type in SUPPORTED_MIME_TYPES

    def extract(self, content: bytes, mime_type: str) -> str | None:
        self.extract_called = True
        self.last_content = content
        self.last_mime_type = mime_type
        return self.return_value


class MockAttachmentDownloader:
    """Mock downloader for testing."""

    def __init__(self) -> None:
        self.content: bytes | None = b"PDF content"
        self.get_content_called = False
        self.last_attachment_id: int | None = None
        self.last_persist: bool | None = None

    def get_attachment_content(self, attachment_id: int, persist: bool = False) -> bytes | None:
        self.get_content_called = True
        self.last_attachment_id = attachment_id
        self.last_persist = persist
        return self.content


class MockConnection:
    """Mock database connection for testing."""

    def __init__(self) -> None:
        self.committed = False
        self.last_query: str | None = None
        self.last_params: tuple | None = None
        self._cursor = MockCursor(self)
        self.attachment_data: dict[int, dict] = {}

    def cursor(self) -> "MockCursor":
        return self._cursor

    def commit(self) -> None:
        self.committed = True


class MockCursor:
    """Mock cursor for testing."""

    def __init__(self, conn: MockConnection) -> None:
        self.conn = conn
        self.results: list[tuple] = []
        self.rowcount = 0
        self._result_index = 0

    def __enter__(self) -> "MockCursor":
        return self

    def __exit__(self, *_args: object) -> None:
        pass

    def execute(self, query: str, params: tuple | list | None = None) -> None:
        self.conn.last_query = query
        self.conn.last_params = params  # type: ignore

    def fetchone(self) -> tuple | None:
        if self._result_index < len(self.results):
            result = self.results[self._result_index]
            self._result_index += 1
            return result
        return None

    def fetchall(self) -> list[tuple]:
        return self.results


class TestExtractionConfig:
    """Tests for ExtractionConfig dataclass."""

    def test_defaults(self) -> None:
        """Test default configuration values."""
        config = ExtractionConfig()

        assert config.prefer_stored is True
        assert config.persist_after_stream is False
        assert config.output_format == "markdown"
        assert config.max_file_size_bytes == 100 * 1024 * 1024
        assert config.use_ocr is True
        assert config.ocr_backend == "tesserocr"
        assert config.force_full_page_ocr is False
        assert config.extraction_timeout == 300
        assert config.published_after is None
        assert config.published_before is None
        assert config.batch_size == 100
        assert config.verbose is False

    def test_custom_values(self) -> None:
        """Test custom configuration values."""
        config = ExtractionConfig(
            use_ocr=False,
            ocr_backend="tesserocr",
            max_file_size_bytes=50 * 1024 * 1024,
            published_after=date(2024, 1, 1),
        )

        assert config.use_ocr is False
        assert config.ocr_backend == "tesserocr"
        assert config.max_file_size_bytes == 50 * 1024 * 1024
        assert config.published_after == date(2024, 1, 1)


class TestPendingExtraction:
    """Tests for PendingExtraction dataclass."""

    def test_creation(self) -> None:
        """Test creating a PendingExtraction object."""
        pending = PendingExtraction(
            id=1,
            document_id=10,
            notice_board_id=100,
            filename="test.pdf",
            mime_type="application/pdf",
            file_size_bytes=1024,
            storage_path="10/test.pdf",
            orig_url="https://example.com/test.pdf",
            download_status=DownloadStatus.DOWNLOADED,
            board_name="Test Board",
        )

        assert pending.id == 1
        assert pending.document_id == 10
        assert pending.notice_board_id == 100
        assert pending.filename == "test.pdf"
        assert pending.mime_type == "application/pdf"

    def test_creation_with_nuts3_and_published_at(self) -> None:
        """Test creating PendingExtraction with nuts3_id and published_at."""
        pending = PendingExtraction(
            id=1,
            document_id=10,
            notice_board_id=100,
            filename="test.pdf",
            mime_type="application/pdf",
            file_size_bytes=1024,
            storage_path=None,
            orig_url=None,
            download_status=DownloadStatus.DOWNLOADED,
            nuts3_id=116,
            published_at=date(2024, 6, 15),
        )

        assert pending.nuts3_id == 116
        assert pending.published_at == date(2024, 6, 15)

    def test_defaults_nuts3_published_at(self) -> None:
        """Test that nuts3_id and published_at default to None."""
        pending = PendingExtraction(
            id=1,
            document_id=10,
            notice_board_id=100,
            filename="test.pdf",
            mime_type=None,
            file_size_bytes=None,
            storage_path=None,
            orig_url=None,
            download_status="pending",
        )

        assert pending.nuts3_id is None
        assert pending.published_at is None


class TestExtractionResult:
    """Tests for ExtractionResult dataclass."""

    def test_success(self) -> None:
        """Test successful extraction result."""
        result = ExtractionResult(
            attachment_id=1,
            success=True,
            text_length=100,
        )

        assert result.attachment_id == 1
        assert result.success is True
        assert result.text_length == 100
        assert result.error is None
        assert result.error_type is None

    def test_failure(self) -> None:
        """Test failed extraction result."""
        result = ExtractionResult(
            attachment_id=1,
            success=False,
            error="download: HTTP 404",
            error_type="download",
        )

        assert result.success is False
        assert result.error == "download: HTTP 404"
        assert result.error_type == "download"


class TestExtractionStats:
    """Tests for ExtractionStats dataclass."""

    def test_defaults(self) -> None:
        """Test default statistics values."""
        stats = ExtractionStats()

        assert stats.total == 0
        assert stats.extracted == 0
        assert stats.failed == 0
        assert stats.skipped == 0
        assert stats.total_chars == 0

    def test_str_representation(self) -> None:
        """Test string representation of statistics."""
        stats = ExtractionStats(
            total=100,
            extracted=80,
            failed=10,
            skipped=10,
            total_chars=50000,
        )

        result = str(stats)
        assert "Total: 100" in result
        assert "Extracted: 80" in result
        assert "Failed: 10" in result
        assert "Skipped: 10" in result
        assert "50,000" in result


class TestParseStatus:
    """Tests for ParseStatus constants."""

    def test_all_statuses(self) -> None:
        """Test all parse status values are defined."""
        assert ParseStatus.PENDING == "pending"
        assert ParseStatus.PARSING == "parsing"
        assert ParseStatus.COMPLETED == "completed"
        assert ParseStatus.FAILED == "failed"
        assert ParseStatus.SKIPPED == "skipped"

    def test_all_tuple(self) -> None:
        """Test ALL tuple contains all statuses."""
        assert ParseStatus.PENDING in ParseStatus.ALL
        assert ParseStatus.PARSING in ParseStatus.ALL
        assert ParseStatus.COMPLETED in ParseStatus.ALL
        assert ParseStatus.FAILED in ParseStatus.ALL
        assert ParseStatus.SKIPPED in ParseStatus.ALL
        assert len(ParseStatus.ALL) == 5

    def test_terminal_statuses(self) -> None:
        """Test terminal statuses are correct."""
        assert ParseStatus.COMPLETED in ParseStatus.TERMINAL
        assert ParseStatus.SKIPPED in ParseStatus.TERMINAL
        assert ParseStatus.PENDING not in ParseStatus.TERMINAL
        assert ParseStatus.FAILED not in ParseStatus.TERMINAL


class TestTextExtractionService:
    """Tests for TextExtractionService."""

    @pytest.fixture
    def mock_conn(self) -> MockConnection:
        """Create mock database connection."""
        return MockConnection()

    @pytest.fixture
    def mock_downloader(self) -> MockAttachmentDownloader:
        """Create mock downloader."""
        return MockAttachmentDownloader()

    @pytest.fixture
    def mock_extractor(self) -> MockTextExtractor:
        """Create mock text extractor."""
        return MockTextExtractor()

    @pytest.fixture
    def service(
        self,
        mock_conn: MockConnection,
        mock_downloader: MockAttachmentDownloader,
        mock_extractor: MockTextExtractor,
    ) -> TextExtractionService:
        """Create TextExtractionService with mocks."""
        return TextExtractionService(
            conn=mock_conn,  # type: ignore
            downloader=mock_downloader,  # type: ignore
            config=ExtractionConfig(),
            extractor=mock_extractor,
        )

    def test_init_default_extractor(
        self, mock_conn: MockConnection, mock_downloader: MockAttachmentDownloader
    ) -> None:
        """Test service creates default extractor when none provided."""
        service = TextExtractionService(
            conn=mock_conn,  # type: ignore
            downloader=mock_downloader,  # type: ignore
        )

        # Should have created a composite extractor
        assert service.extractor is not None
        assert isinstance(service.extractor, CompositeTextExtractor)

    def test_init_custom_extractor(
        self,
        mock_conn: MockConnection,
        mock_downloader: MockAttachmentDownloader,
        mock_extractor: MockTextExtractor,
    ) -> None:
        """Test service uses provided extractor."""
        service = TextExtractionService(
            conn=mock_conn,  # type: ignore
            downloader=mock_downloader,  # type: ignore
            extractor=mock_extractor,
        )

        assert service.extractor is mock_extractor

    def test_extract_text_not_found(self, service: TextExtractionService) -> None:
        """Test extraction when attachment not found."""
        # Mock cursor returns no results
        result = service.extract_text(attachment_id=999)

        assert result.success is False
        assert result.error == "Attachment not found"
        assert result.error_type == "extraction"

    def test_extract_text_unsupported_mime(
        self,
        mock_conn: MockConnection,
        mock_downloader: MockAttachmentDownloader,
        mock_extractor: MockTextExtractor,
    ) -> None:
        """Test extraction skips unsupported MIME types."""
        # Setup mock to return attachment with unsupported MIME type
        mock_conn._cursor.results = [
            (
                1,
                10,
                100,
                "test.xyz",
                "application/x-unknown",
                1024,
                "10/test.xyz",
                None,
                "pending",
                "Test Board",
                116,
                date(2024, 1, 1),
            )
        ]

        service = TextExtractionService(
            conn=mock_conn,  # type: ignore
            downloader=mock_downloader,  # type: ignore
            extractor=mock_extractor,
        )

        result = service.extract_text(attachment_id=1)

        assert result.success is False
        assert result.error_type == "skipped"
        assert "Unsupported MIME type" in (result.error or "")

    def test_extract_text_success(
        self,
        mock_conn: MockConnection,
        mock_downloader: MockAttachmentDownloader,
        mock_extractor: MockTextExtractor,
    ) -> None:
        """Test successful text extraction."""
        # Setup mock to return valid attachment
        mock_conn._cursor.results = [
            (
                1,
                10,
                100,
                "test.pdf",
                "application/pdf",
                1024,
                "10/test.pdf",
                None,
                "downloaded",
                "Test Board",
                116,
                date(2024, 1, 1),
            )
        ]
        mock_extractor.return_value = "Extracted text content"

        service = TextExtractionService(
            conn=mock_conn,  # type: ignore
            downloader=mock_downloader,  # type: ignore
            extractor=mock_extractor,
        )

        result = service.extract_text(attachment_id=1)

        assert result.success is True
        assert result.text_length == len("Extracted text content")
        assert mock_extractor.extract_called is True
        assert mock_downloader.get_content_called is True

    def test_extract_text_download_failure(
        self,
        mock_conn: MockConnection,
        mock_downloader: MockAttachmentDownloader,
        mock_extractor: MockTextExtractor,
    ) -> None:
        """Test extraction when download fails."""
        # Setup mock to return valid attachment but no content
        mock_conn._cursor.results = [
            (
                1,
                10,
                100,
                "test.pdf",
                "application/pdf",
                1024,
                "10/test.pdf",
                "http://example.com/test.pdf",
                "pending",
                "Test Board",
                116,
                date(2024, 1, 1),
            )
        ]
        mock_downloader.content = None

        service = TextExtractionService(
            conn=mock_conn,  # type: ignore
            downloader=mock_downloader,  # type: ignore
            extractor=mock_extractor,
        )

        result = service.extract_text(attachment_id=1)

        assert result.success is False
        assert result.error_type == "download"
        assert "No content available" in (result.error or "")

    def test_extract_text_file_too_large(
        self,
        mock_conn: MockConnection,
        mock_downloader: MockAttachmentDownloader,
        mock_extractor: MockTextExtractor,
    ) -> None:
        """Test extraction skips files that are too large."""
        # Setup mock with large file size
        mock_conn._cursor.results = [
            (
                1,
                10,
                100,
                "test.pdf",
                "application/pdf",
                200 * 1024 * 1024,
                "10/test.pdf",
                None,
                "downloaded",
                "Test Board",
                116,
                date(2024, 1, 1),
            )
        ]

        config = ExtractionConfig(max_file_size_bytes=100 * 1024 * 1024)
        service = TextExtractionService(
            conn=mock_conn,  # type: ignore
            downloader=mock_downloader,  # type: ignore
            config=config,
            extractor=mock_extractor,
        )

        result = service.extract_text(attachment_id=1)

        assert result.success is False
        assert result.error_type == "skipped"
        assert "File too large" in (result.error or "")

    def test_extract_text_extraction_error(
        self,
        mock_conn: MockConnection,
        mock_downloader: MockAttachmentDownloader,
    ) -> None:
        """Test extraction handles extractor errors."""
        # Setup mock to return valid attachment (12 columns: +nuts3_id, +published_at)
        mock_conn._cursor.results = [
            (
                1,
                10,
                100,
                "test.pdf",
                "application/pdf",
                1024,
                "10/test.pdf",
                None,
                "downloaded",
                "Test Board",
                116,
                date(2024, 1, 1),
            )
        ]

        # Create extractor that raises error
        class FailingExtractor(TextExtractor):
            def supports(self, mime_type: str) -> bool:  # noqa: ARG002
                return True

            def extract(self, content: bytes, mime_type: str) -> str | None:  # noqa: ARG002
                raise TextExtractionError("Extraction failed")

        service = TextExtractionService(
            conn=mock_conn,  # type: ignore
            downloader=mock_downloader,  # type: ignore
            extractor=FailingExtractor(),
        )

        result = service.extract_text(attachment_id=1)

        assert result.success is False
        assert result.error_type == "extraction"
        assert "Extraction failed" in (result.error or "")

    def test_mark_parsing(
        self, mock_conn: MockConnection, mock_downloader: MockAttachmentDownloader
    ) -> None:
        """Test mark_parsing updates database correctly."""
        service = TextExtractionService(
            conn=mock_conn,  # type: ignore
            downloader=mock_downloader,  # type: ignore
        )

        service.mark_parsing(attachment_id=1)

        assert mock_conn.committed is True
        assert mock_conn.last_query is not None
        assert "parse_status" in mock_conn.last_query
        assert ParseStatus.PARSING in mock_conn.last_params  # type: ignore

    def test_mark_completed(
        self, mock_conn: MockConnection, mock_downloader: MockAttachmentDownloader
    ) -> None:
        """Test mark_completed updates database correctly."""
        service = TextExtractionService(
            conn=mock_conn,  # type: ignore
            downloader=mock_downloader,  # type: ignore
        )

        service.mark_completed(attachment_id=1, extracted_text="Test text")

        assert mock_conn.committed is True
        assert mock_conn.last_query is not None
        assert "extracted_text" in mock_conn.last_query
        assert "text_length" in mock_conn.last_query
        assert ParseStatus.COMPLETED in mock_conn.last_params  # type: ignore

    def test_mark_completed_with_sqlite_storage(
        self,
        mock_conn: MockConnection,
        mock_downloader: MockAttachmentDownloader,
        tmp_path: Path,
    ) -> None:
        """Test mark_completed stores text in SQLite when storage configured."""
        sqlite_storage = SqliteTextStorage(tmp_path)

        service = TextExtractionService(
            conn=mock_conn,  # type: ignore
            downloader=mock_downloader,  # type: ignore
            sqlite_storage=sqlite_storage,
        )

        pending = PendingExtraction(
            id=1,
            document_id=10,
            notice_board_id=100,
            filename="test.pdf",
            mime_type="application/pdf",
            file_size_bytes=1024,
            storage_path=None,
            orig_url=None,
            download_status="downloaded",
            nuts3_id=116,
            published_at=date(2024, 6, 15),
        )

        service.mark_completed(
            attachment_id=1, extracted_text="Test text from SQLite", pending=pending
        )

        # Verify text was saved to SQLite
        loaded = sqlite_storage.load(pending)
        assert loaded == "Test text from SQLite"

        # Verify DB was updated with NULL extracted_text and text_length
        assert mock_conn.committed is True
        assert mock_conn.last_query is not None
        assert "extracted_text = NULL" in mock_conn.last_query
        assert "text_length" in mock_conn.last_query
        sqlite_storage.close()

    def test_mark_completed_without_pending_falls_back_to_db(
        self,
        mock_conn: MockConnection,
        mock_downloader: MockAttachmentDownloader,
        tmp_path: Path,
    ) -> None:
        """Test mark_completed stores in DB when pending is None even with sqlite_storage."""
        sqlite_storage = SqliteTextStorage(tmp_path)

        service = TextExtractionService(
            conn=mock_conn,  # type: ignore
            downloader=mock_downloader,  # type: ignore
            sqlite_storage=sqlite_storage,
        )

        # Call without pending — should store in DB
        service.mark_completed(attachment_id=1, extracted_text="DB text")

        assert mock_conn.committed is True
        assert mock_conn.last_query is not None
        assert "extracted_text = %s" in mock_conn.last_query
        sqlite_storage.close()

    def test_mark_failed(
        self, mock_conn: MockConnection, mock_downloader: MockAttachmentDownloader
    ) -> None:
        """Test mark_failed updates database correctly."""
        service = TextExtractionService(
            conn=mock_conn,  # type: ignore
            downloader=mock_downloader,  # type: ignore
        )

        service.mark_failed(attachment_id=1, error="Test error", error_type="extraction")

        assert mock_conn.committed is True
        assert mock_conn.last_query is not None
        assert "parse_error" in mock_conn.last_query
        assert ParseStatus.FAILED in mock_conn.last_params  # type: ignore

    def test_mark_skipped(
        self, mock_conn: MockConnection, mock_downloader: MockAttachmentDownloader
    ) -> None:
        """Test mark_skipped updates database correctly."""
        service = TextExtractionService(
            conn=mock_conn,  # type: ignore
            downloader=mock_downloader,  # type: ignore
        )

        service.mark_skipped(attachment_id=1, reason="Unsupported type")

        assert mock_conn.committed is True
        assert mock_conn.last_query is not None
        assert ParseStatus.SKIPPED in mock_conn.last_params  # type: ignore

    def test_reset_to_pending_failed_only(
        self, mock_conn: MockConnection, mock_downloader: MockAttachmentDownloader
    ) -> None:
        """Test reset_to_pending resets only failed by default."""
        mock_conn._cursor.rowcount = 5

        service = TextExtractionService(
            conn=mock_conn,  # type: ignore
            downloader=mock_downloader,  # type: ignore
        )

        count = service.reset_to_pending(failed_only=True)

        assert count == 5
        assert mock_conn.committed is True
        # Check that only failed status is in params
        assert mock_conn.last_params is not None
        status_list = mock_conn.last_params[1]
        assert ParseStatus.FAILED in status_list
        assert ParseStatus.SKIPPED not in status_list

    def test_reset_to_pending_all(
        self, mock_conn: MockConnection, mock_downloader: MockAttachmentDownloader
    ) -> None:
        """Test reset_to_pending can reset all retryable statuses."""
        mock_conn._cursor.rowcount = 10

        service = TextExtractionService(
            conn=mock_conn,  # type: ignore
            downloader=mock_downloader,  # type: ignore
        )

        count = service.reset_to_pending(failed_only=False)

        assert count == 10
        # Check that both failed and skipped are in params
        assert mock_conn.last_params is not None
        status_list = mock_conn.last_params[1]
        assert ParseStatus.FAILED in status_list
        assert ParseStatus.SKIPPED in status_list


class TestSupportedMimeTypes:
    """Tests for SUPPORTED_MIME_TYPES constant."""

    def test_pdf_supported(self) -> None:
        """Test PDF MIME types are supported."""
        assert "application/pdf" in SUPPORTED_MIME_TYPES
        assert "application/x-pdf" in SUPPORTED_MIME_TYPES

    def test_office_supported(self) -> None:
        """Test Office MIME types are supported."""
        docx_mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        assert docx_mime in SUPPORTED_MIME_TYPES
        assert "application/msword" in SUPPORTED_MIME_TYPES

    def test_images_supported(self) -> None:
        """Test image MIME types are supported."""
        assert "image/png" in SUPPORTED_MIME_TYPES
        assert "image/jpeg" in SUPPORTED_MIME_TYPES
        assert "image/tiff" in SUPPORTED_MIME_TYPES

    def test_text_supported(self) -> None:
        """Test text MIME types are supported."""
        assert "text/plain" in SUPPORTED_MIME_TYPES
        assert "text/html" in SUPPORTED_MIME_TYPES


class TestCreateDefaultExtractor:
    """Tests for create_default_extractor factory function."""

    def test_creates_composite_extractor(self) -> None:
        """Test factory creates a composite extractor."""
        from notice_boards.parsers import create_default_extractor

        extractor = create_default_extractor()

        assert isinstance(extractor, CompositeTextExtractor)

    def test_respects_ocr_setting(self) -> None:
        """Test factory respects OCR settings."""
        from notice_boards.parsers import create_default_extractor

        # Should not raise
        extractor = create_default_extractor(use_ocr=False)
        assert extractor is not None

    def test_respects_output_format(self) -> None:
        """Test factory respects output format settings."""
        from notice_boards.parsers import create_default_extractor

        # Should not raise
        extractor = create_default_extractor(output_format="text")
        assert extractor is not None


class TestLoadText:
    """Tests for load_text method."""

    def test_load_text_from_db(
        self,
    ) -> None:
        """Test load_text reads from DB column when no sqlite_storage."""
        conn = MockConnection()
        downloader = MockAttachmentDownloader()
        service = TextExtractionService(
            conn=conn,  # type: ignore
            downloader=downloader,  # type: ignore
        )

        conn._cursor.results = [("Text from DB",)]
        text = service.load_text(attachment_id=1)

        assert text == "Text from DB"
        assert conn.last_query is not None
        assert "extracted_text" in conn.last_query

    def test_load_text_from_sqlite(self, tmp_path: Path) -> None:
        """Test load_text reads from SQLite when configured."""
        conn = MockConnection()
        downloader = MockAttachmentDownloader()
        sqlite_storage = SqliteTextStorage(tmp_path)

        # Save a text to SQLite
        pending = PendingExtraction(
            id=42,
            document_id=10,
            notice_board_id=100,
            filename="test.pdf",
            mime_type="application/pdf",
            file_size_bytes=1024,
            storage_path=None,
            orig_url=None,
            download_status="downloaded",
            nuts3_id=116,
            published_at=date(2024, 6, 15),
        )
        sqlite_storage.save(pending, "Text from SQLite")

        service = TextExtractionService(
            conn=conn,  # type: ignore
            downloader=downloader,  # type: ignore
            sqlite_storage=sqlite_storage,
        )

        # Mock the DB query that gets partition info
        conn._cursor.results = [(116, date(2024, 6, 15))]
        text = service.load_text(attachment_id=42)

        assert text == "Text from SQLite"
        sqlite_storage.close()

    def test_load_text_not_found(self) -> None:
        """Test load_text returns None when text not found."""
        conn = MockConnection()
        downloader = MockAttachmentDownloader()
        service = TextExtractionService(
            conn=conn,  # type: ignore
            downloader=downloader,  # type: ignore
        )

        conn._cursor.results = []
        text = service.load_text(attachment_id=999)

        assert text is None
