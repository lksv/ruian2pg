"""Tests for OFN (Open Formal Norm) scraper."""

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from notice_boards.scraper_config import OfnConfig
from notice_boards.scrapers.ofn import (
    OfnAttachment,
    OfnBoard,
    OfnClient,
    OfnDocument,
    OfnScraper,
)


class TestOfnClient:
    """Tests for OfnClient."""

    @pytest.fixture
    def client(self) -> OfnClient:
        """Create OFN client for testing."""
        config = OfnConfig(request_timeout=10, max_retries=1)
        return OfnClient(config)

    def test_parse_feed_valid(self, client: OfnClient) -> None:
        """Test parsing valid OFN JSON-LD feed."""
        data = {
            "@context": "https://ofn.gov.cz/úřední-desky/.../kontexty/úřední-deska.jsonld",
            "typ": "Úřední deska",
            "iri": "https://edeska.brno.cz/eDeska01/opendata",
            "stránka": "https://edeska.brno.cz/eDeska01",
            "provozovatel": {"typ": "Osoba", "ičo": "44992785"},
            "informace": [
                {
                    "typ": ["Digitální objekt", "Informace na úřední desce"],
                    "iri": "https://edeska.brno.cz/eDeska01/eDeskaDetail.jsp?detailId=47130",
                    "url": "https://edeska.brno.cz/eDeska01/eDeskaDetail.jsp?detailId=47130",
                    "název": {"cs": "Test Document"},
                    "vyvěšení": {"typ": "Časový okamžik", "datum": "2026-01-29"},
                    "relevantní_do": {"typ": "Časový okamžik", "datum": "2026-02-13"},
                    "číslo_jednací": "MMB/0051320/2026",
                    "agenda": [{"typ": "Agenda", "název": {"cs": "Externí dokumenty"}}],
                    "dokument": [
                        {
                            "typ": "Digitální objekt",
                            "název": {"cs": "document.pdf"},
                            "url": "https://edeska.brno.cz/download.jsp?id=47131",
                        },
                    ],
                },
            ],
        }

        board = client._parse_feed(data, "https://test.url/opendata")

        assert board.iri == "https://edeska.brno.cz/eDeska01/opendata"
        assert board.page_url == "https://edeska.brno.cz/eDeska01"
        assert board.ico == "44992785"
        assert len(board.documents) == 1

        doc = board.documents[0]
        assert doc.iri == "https://edeska.brno.cz/eDeska01/eDeskaDetail.jsp?detailId=47130"
        assert doc.title == "Test Document"
        assert doc.published_at == date(2026, 1, 29)
        assert doc.valid_until == date(2026, 2, 13)
        assert doc.reference_number == "MMB/0051320/2026"
        assert doc.category == "Externí dokumenty"
        assert len(doc.attachments) == 1
        assert doc.attachments[0].name == "document.pdf"

    def test_parse_feed_multiple_documents(self, client: OfnClient) -> None:
        """Test parsing feed with multiple documents."""
        data = {
            "iri": "https://test.url/opendata",
            "informace": [
                {
                    "iri": "https://test.url/doc/1",
                    "název": {"cs": "Doc 1"},
                    "vyvěšení": {"datum": "2026-01-01"},
                },
                {
                    "iri": "https://test.url/doc/2",
                    "název": {"cs": "Doc 2"},
                    "vyvěšení": {"datum": "2026-01-02"},
                },
                {
                    "iri": "https://test.url/doc/3",
                    "název": {"cs": "Doc 3"},
                    "vyvěšení": {"datum": "2026-01-03"},
                },
            ],
        }

        board = client._parse_feed(data, "https://test.url/opendata")

        assert len(board.documents) == 3
        assert board.documents[0].title == "Doc 1"
        assert board.documents[1].title == "Doc 2"
        assert board.documents[2].title == "Doc 3"

    def test_parse_feed_empty_documents(self, client: OfnClient) -> None:
        """Test parsing feed with no documents."""
        data = {
            "iri": "https://test.url/opendata",
            "informace": [],
        }

        board = client._parse_feed(data, "https://test.url/opendata")

        assert len(board.documents) == 0

    def test_parse_feed_missing_informace(self, client: OfnClient) -> None:
        """Test parsing feed without informace key."""
        data = {
            "iri": "https://test.url/opendata",
        }

        board = client._parse_feed(data, "https://test.url/opendata")

        assert len(board.documents) == 0

    def test_parse_document_missing_iri(self, client: OfnClient) -> None:
        """Test document without IRI is skipped."""
        info = {
            "název": {"cs": "No IRI"},
            "vyvěšení": {"datum": "2026-01-01"},
        }

        doc = client._parse_document(info)

        assert doc is None

    def test_parse_document_missing_date(self, client: OfnClient) -> None:
        """Test document without publication date is skipped."""
        info = {
            "iri": "https://test.url/doc/1",
            "název": {"cs": "No Date"},
        }

        doc = client._parse_document(info)

        assert doc is None

    def test_parse_document_invalid_date(self, client: OfnClient) -> None:
        """Test document with invalid date format is skipped."""
        info = {
            "iri": "https://test.url/doc/1",
            "název": {"cs": "Bad Date"},
            "vyvěšení": {"datum": "not-a-date"},
        }

        doc = client._parse_document(info)

        assert doc is None

    def test_parse_document_optional_fields(self, client: OfnClient) -> None:
        """Test document with optional fields."""
        info = {
            "iri": "https://test.url/doc/1",
            "název": {"cs": "Full Doc"},
            "vyvěšení": {"datum": "2026-01-15"},
            "relevantní_do": {"datum": "2026-02-15"},
            "číslo_jednací": "ABC/123/2026",
            "spisová_značka": "SZ-456/2026",
            "agenda": [{"název": {"cs": "Test Category"}}],
            "url": "https://test.url/detail/1",
        }

        doc = client._parse_document(info)

        assert doc is not None
        assert doc.valid_until == date(2026, 2, 15)
        assert doc.reference_number == "ABC/123/2026"
        assert doc.file_reference == "SZ-456/2026"
        assert doc.category == "Test Category"
        assert doc.url == "https://test.url/detail/1"

    def test_parse_document_multiple_attachments(self, client: OfnClient) -> None:
        """Test parsing document with multiple attachments."""
        info = {
            "iri": "https://test.url/doc/1",
            "název": {"cs": "Multi Attach"},
            "vyvěšení": {"datum": "2026-01-15"},
            "dokument": [
                {"název": {"cs": "file1.pdf"}, "url": "https://test.url/file1.pdf"},
                {"název": {"cs": "file2.docx"}, "url": "https://test.url/file2.docx"},
                {"název": {"cs": "image.png"}, "url": "https://test.url/image.png"},
            ],
        }

        doc = client._parse_document(info)

        assert doc is not None
        assert len(doc.attachments) == 3
        assert doc.attachments[0].name == "file1.pdf"
        assert doc.attachments[1].name == "file2.docx"
        assert doc.attachments[2].name == "image.png"

    def test_get_localized_text_dict(self, client: OfnClient) -> None:
        """Test extracting text from localized dict."""
        assert client._get_localized_text({"cs": "Czech text"}) == "Czech text"
        assert client._get_localized_text({"en": "English"}) == "English"
        assert client._get_localized_text({"cs": "Czech", "en": "English"}) == "Czech"

    def test_get_localized_text_string(self, client: OfnClient) -> None:
        """Test extracting text from plain string."""
        assert client._get_localized_text("Plain text") == "Plain text"

    def test_get_localized_text_none(self, client: OfnClient) -> None:
        """Test handling None value."""
        assert client._get_localized_text(None) is None

    def test_get_localized_text_empty_dict(self, client: OfnClient) -> None:
        """Test handling empty dict."""
        assert client._get_localized_text({}) is None


class TestOfnScraper:
    """Tests for OfnScraper."""

    @pytest.fixture
    def scraper(self) -> OfnScraper:
        """Create scraper for testing."""
        config = OfnConfig(request_timeout=10, max_retries=1)
        return OfnScraper(config, download_originals=False)

    def test_supports_ofn(self, scraper: OfnScraper) -> None:
        """Test supports method returns True for ofn."""
        assert scraper.supports("ofn")
        assert scraper.supports("OFN")
        assert scraper.supports("Ofn")

    def test_supports_other_types(self, scraper: OfnScraper) -> None:
        """Test supports method returns False for other types."""
        assert not scraper.supports("edesky")
        assert not scraper.supports("ginis")
        assert not scraper.supports("vismo")

    def test_convert_document(self, scraper: OfnScraper) -> None:
        """Test converting OfnDocument to DocumentData."""
        ofn_doc = OfnDocument(
            iri="https://test.url/doc/12345",
            title="Test Document",
            published_at=date(2026, 1, 15),
            valid_until=date(2026, 2, 15),
            reference_number="ABC/123/2026",
            file_reference="SZ-456/2026",
            category="Test Category",
            url="https://test.url/detail/12345",
            attachments=[
                OfnAttachment(name="file.pdf", url="https://test.url/file.pdf"),
            ],
        )

        doc_data = scraper._convert_document(ofn_doc, "https://feed.url/opendata")

        # External ID should be hash of IRI
        assert doc_data.external_id.startswith("ofn_")
        assert len(doc_data.external_id) == 4 + 16  # "ofn_" + 16 hex chars
        assert doc_data.title == "Test Document"
        assert doc_data.published_at == date(2026, 1, 15)
        assert doc_data.valid_until == date(2026, 2, 15)
        assert doc_data.source_type == "ofn"
        assert doc_data.metadata["ofn_iri"] == "https://test.url/doc/12345"
        assert doc_data.metadata["ofn_url"] == "https://feed.url/opendata"
        assert doc_data.metadata["reference_number"] == "ABC/123/2026"
        assert doc_data.metadata["file_reference"] == "SZ-456/2026"
        assert doc_data.metadata["category"] == "Test Category"
        assert doc_data.metadata["detail_url"] == "https://test.url/detail/12345"
        assert len(doc_data.attachments) == 1
        assert doc_data.attachments[0].filename == "file.pdf"
        assert doc_data.attachments[0].url == "https://test.url/file.pdf"

    def test_convert_document_minimal(self, scraper: OfnScraper) -> None:
        """Test converting document with minimal fields."""
        ofn_doc = OfnDocument(
            iri="https://test.url/doc/1",
            title="Minimal Doc",
            published_at=date(2026, 1, 1),
        )

        doc_data = scraper._convert_document(ofn_doc, "https://feed.url/opendata")

        assert doc_data.title == "Minimal Doc"
        assert doc_data.published_at == date(2026, 1, 1)
        assert doc_data.valid_until is None
        assert "reference_number" not in doc_data.metadata
        assert "file_reference" not in doc_data.metadata
        assert "category" not in doc_data.metadata
        assert len(doc_data.attachments) == 0

    def test_generate_external_id(self, scraper: OfnScraper) -> None:
        """Test external ID generation from IRI."""
        id1 = scraper._generate_external_id("https://test.url/doc/1")
        id2 = scraper._generate_external_id("https://test.url/doc/2")
        id3 = scraper._generate_external_id("https://test.url/doc/1")

        # Same IRI should produce same ID
        assert id1 == id3

        # Different IRIs should produce different IDs
        assert id1 != id2

        # Format check
        assert id1.startswith("ofn_")
        assert len(id1) == 20  # "ofn_" + 16 hex chars

    def test_guess_mime_type(self, scraper: OfnScraper) -> None:
        """Test MIME type guessing from filename."""
        assert scraper._guess_mime_type("document.pdf") == "application/pdf"
        assert scraper._guess_mime_type("image.jpg") == "image/jpeg"
        assert scraper._guess_mime_type("image.jpeg") == "image/jpeg"
        assert scraper._guess_mime_type("photo.png") == "image/png"
        xlsx_mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        assert scraper._guess_mime_type("data.xlsx") == xlsx_mime
        assert scraper._guess_mime_type("archive.zip") == "application/zip"
        assert scraper._guess_mime_type("data.xml") == "application/xml"
        assert scraper._guess_mime_type("unknown.xyz") is None
        assert scraper._guess_mime_type("noextension") is None

    @patch.object(OfnClient, "fetch_feed")
    def test_scrape_by_url(self, mock_fetch: MagicMock, scraper: OfnScraper) -> None:
        """Test scraping by OFN URL."""
        mock_fetch.return_value = OfnBoard(
            iri="https://test.url/opendata",
            documents=[
                OfnDocument(
                    iri="https://test.url/doc/1",
                    title="Doc 1",
                    published_at=date(2026, 1, 1),
                ),
                OfnDocument(
                    iri="https://test.url/doc/2",
                    title="Doc 2",
                    published_at=date(2026, 1, 2),
                ),
            ],
        )

        documents = scraper.scrape_by_url("https://test.url/opendata")

        assert len(documents) == 2
        assert documents[0].title == "Doc 1"
        assert documents[1].title == "Doc 2"
        mock_fetch.assert_called_once_with("https://test.url/opendata")


class TestOfnDocument:
    """Tests for OfnDocument dataclass."""

    def test_create_minimal(self) -> None:
        """Test creating document with minimal fields."""
        doc = OfnDocument(
            iri="https://test.url/doc/1",
            title="Test",
            published_at=date(2026, 1, 1),
        )

        assert doc.iri == "https://test.url/doc/1"
        assert doc.title == "Test"
        assert doc.published_at == date(2026, 1, 1)
        assert doc.valid_until is None
        assert doc.reference_number is None
        assert doc.file_reference is None
        assert doc.category is None
        assert doc.attachments == []
        assert doc.url is None

    def test_create_full(self) -> None:
        """Test creating document with all fields."""
        attachments = [
            OfnAttachment(name="file.pdf", url="http://example.com/file.pdf"),
        ]
        doc = OfnDocument(
            iri="https://test.url/doc/1",
            title="Full Doc",
            published_at=date(2026, 1, 1),
            valid_until=date(2026, 2, 1),
            reference_number="REF-123",
            file_reference="FILE-456",
            category="Category",
            url="http://example.com/detail",
            attachments=attachments,
        )

        assert doc.valid_until == date(2026, 2, 1)
        assert doc.reference_number == "REF-123"
        assert doc.file_reference == "FILE-456"
        assert doc.category == "Category"
        assert doc.url == "http://example.com/detail"
        assert len(doc.attachments) == 1


class TestOfnBoard:
    """Tests for OfnBoard dataclass."""

    def test_create_minimal(self) -> None:
        """Test creating board with minimal fields."""
        board = OfnBoard(iri="https://test.url/opendata")

        assert board.iri == "https://test.url/opendata"
        assert board.page_url is None
        assert board.ico is None
        assert board.name is None
        assert board.documents == []

    def test_create_full(self) -> None:
        """Test creating board with all fields."""
        documents = [
            OfnDocument(
                iri="https://test.url/doc/1",
                title="Doc 1",
                published_at=date(2026, 1, 1),
            ),
        ]
        board = OfnBoard(
            iri="https://test.url/opendata",
            page_url="https://test.url",
            ico="12345678",
            name="Test Organization",
            documents=documents,
        )

        assert board.page_url == "https://test.url"
        assert board.ico == "12345678"
        assert board.name == "Test Organization"
        assert len(board.documents) == 1


class TestOfnAttachment:
    """Tests for OfnAttachment dataclass."""

    def test_create(self) -> None:
        """Test creating attachment."""
        att = OfnAttachment(
            name="document.pdf",
            url="https://test.url/document.pdf",
        )

        assert att.name == "document.pdf"
        assert att.url == "https://test.url/document.pdf"


class TestOfnConfig:
    """Tests for OfnConfig."""

    def test_default_values(self) -> None:
        """Test default configuration values."""
        config = OfnConfig()

        assert config.request_timeout == 30
        assert config.max_retries == 3
        assert config.retry_delay == 1.0
        assert "ruian2pg" in config.user_agent
        assert config.skip_ssl_verify is True

    def test_custom_values(self) -> None:
        """Test custom configuration values."""
        config = OfnConfig(
            request_timeout=60,
            max_retries=5,
            retry_delay=2.0,
            user_agent="custom-agent",
            skip_ssl_verify=False,
        )

        assert config.request_timeout == 60
        assert config.max_retries == 5
        assert config.retry_delay == 2.0
        assert config.user_agent == "custom-agent"
        assert config.skip_ssl_verify is False
