"""Tests for eDesky scraper."""

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from notice_boards.scraper_config import EdeskyConfig
from notice_boards.scrapers.base import ScraperError
from notice_boards.scrapers.edesky import (
    EdeskyApiClient,
    EdeskyAttachment,
    EdeskyDashboard,
    EdeskyDocument,
    EdeskyScraper,
    EdeskyXmlClient,
)


class TestEdeskyXmlClient:
    """Tests for EdeskyXmlClient."""

    @pytest.fixture
    def client(self) -> EdeskyXmlClient:
        """Create XML client for testing."""
        config = EdeskyConfig(request_timeout=10, max_retries=1)
        return EdeskyXmlClient(config)

    def test_parse_xml_valid(self, client: EdeskyXmlClient) -> None:
        """Test parsing valid XML response."""
        xml_content = """<?xml version="1.0" encoding="UTF-8"?>
        <dashboard edesky_id='62' name='Jihočeský kraj'>
          <documents>
            <document edesky_url='https://edesky.cz/dokument/12345'
                      loaded_at='2026-01-30'
                      name='Test Document'
                      orig_url='https://example.com/doc'>
              <content>Some content</content>
              <attachment name='file.pdf' url='https://example.com/file.pdf'/>
              <attachment name='image.png' url='https://example.com/image.png'/>
            </document>
          </documents>
        </dashboard>
        """

        documents = client._parse_xml(xml_content)

        assert len(documents) == 1
        doc = documents[0]
        assert doc.edesky_id == 12345
        assert doc.edesky_url == "https://edesky.cz/dokument/12345"
        assert doc.name == "Test Document"
        assert doc.loaded_at == date(2026, 1, 30)
        assert doc.orig_url == "https://example.com/doc"
        assert doc.content == "Some content"
        assert len(doc.attachments) == 2
        assert doc.attachments[0].name == "file.pdf"
        assert doc.attachments[0].url == "https://example.com/file.pdf"

    def test_parse_xml_multiple_documents(self, client: EdeskyXmlClient) -> None:
        """Test parsing XML with multiple documents."""
        xml_content = """<?xml version="1.0" encoding="UTF-8"?>
        <dashboard edesky_id='62' name='Test Board'>
          <documents>
            <document edesky_url='https://edesky.cz/dokument/1'
                      loaded_at='2026-01-01' name='Doc 1'/>
            <document edesky_url='https://edesky.cz/dokument/2'
                      loaded_at='2026-01-02' name='Doc 2'/>
            <document edesky_url='https://edesky.cz/dokument/3'
                      loaded_at='2026-01-03' name='Doc 3'/>
          </documents>
        </dashboard>
        """

        documents = client._parse_xml(xml_content)

        assert len(documents) == 3
        assert documents[0].edesky_id == 1
        assert documents[1].edesky_id == 2
        assert documents[2].edesky_id == 3

    def test_parse_xml_empty_documents(self, client: EdeskyXmlClient) -> None:
        """Test parsing XML with no documents."""
        xml_content = """<?xml version="1.0" encoding="UTF-8"?>
        <dashboard edesky_id='62' name='Empty Board'>
          <documents>
          </documents>
        </dashboard>
        """

        documents = client._parse_xml(xml_content)

        assert len(documents) == 0

    def test_parse_xml_invalid(self, client: EdeskyXmlClient) -> None:
        """Test parsing invalid XML raises error."""
        with pytest.raises(ScraperError, match="Failed to parse XML"):
            client._parse_xml("not valid xml <><>")

    def test_parse_xml_missing_url(self, client: EdeskyXmlClient) -> None:
        """Test documents without edesky_url are skipped."""
        xml_content = """<?xml version="1.0" encoding="UTF-8"?>
        <dashboard edesky_id='62' name='Test'>
          <documents>
            <document loaded_at='2026-01-01' name='No URL'/>
            <document edesky_url='https://edesky.cz/dokument/1'
                      loaded_at='2026-01-01' name='Has URL'/>
          </documents>
        </dashboard>
        """

        documents = client._parse_xml(xml_content)

        assert len(documents) == 1
        assert documents[0].name == "Has URL"

    def test_extract_document_id(self, client: EdeskyXmlClient) -> None:
        """Test extracting document ID from URL."""
        assert client._extract_document_id("https://edesky.cz/dokument/12345") == 12345
        assert client._extract_document_id("https://edesky.cz/dokument/1") == 1
        assert client._extract_document_id("http://edesky.cz/dokument/999") == 999
        assert client._extract_document_id("invalid-url") is None
        assert client._extract_document_id("https://edesky.cz/desky/62") is None


class TestEdeskyScraper:
    """Tests for EdeskyScraper."""

    @pytest.fixture
    def scraper(self) -> EdeskyScraper:
        """Create scraper for testing."""
        config = EdeskyConfig(request_timeout=10, max_retries=1)
        return EdeskyScraper(config, download_text=False, download_originals=False)

    def test_supports_edesky(self, scraper: EdeskyScraper) -> None:
        """Test supports method returns True for edesky."""
        assert scraper.supports("edesky")
        assert scraper.supports("EDESKY")
        assert scraper.supports("Edesky")

    def test_supports_other_types(self, scraper: EdeskyScraper) -> None:
        """Test supports method returns False for other types."""
        assert not scraper.supports("ginis")
        assert not scraper.supports("vismo")
        assert not scraper.supports("ofn")

    def test_convert_document(self, scraper: EdeskyScraper) -> None:
        """Test converting EdeskyDocument to DocumentData."""
        edesky_doc = EdeskyDocument(
            edesky_url="https://edesky.cz/dokument/12345",
            edesky_id=12345,
            name="Test Document",
            loaded_at=date(2026, 1, 30),
            orig_url="https://example.com/doc",
            content="Content text",
            attachments=[
                EdeskyAttachment(name="file.pdf", url="https://example.com/file.pdf"),
            ],
        )

        doc_data = scraper._convert_document(edesky_doc)

        assert doc_data.external_id == "12345"
        assert doc_data.title == "Test Document"
        assert doc_data.published_at == date(2026, 1, 30)
        assert doc_data.metadata["edesky_url"] == "https://edesky.cz/dokument/12345"
        assert doc_data.metadata["orig_url"] == "https://example.com/doc"
        assert doc_data.metadata["edesky_id"] == 12345
        assert len(doc_data.attachments) == 1
        assert doc_data.attachments[0].filename == "file.pdf"
        assert doc_data.attachments[0].url == "https://example.com/file.pdf"

    def test_guess_mime_type(self, scraper: EdeskyScraper) -> None:
        """Test MIME type guessing from filename."""
        assert scraper._guess_mime_type("document.pdf") == "application/pdf"
        assert scraper._guess_mime_type("image.jpg") == "image/jpeg"
        assert scraper._guess_mime_type("image.jpeg") == "image/jpeg"
        assert scraper._guess_mime_type("photo.png") == "image/png"
        xlsx_mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        assert scraper._guess_mime_type("data.xlsx") == xlsx_mime
        assert scraper._guess_mime_type("unknown.xyz") is None
        assert scraper._guess_mime_type("noextension") is None

    @patch.object(EdeskyXmlClient, "get_documents")
    def test_scrape_by_id(self, mock_get_docs: MagicMock, scraper: EdeskyScraper) -> None:
        """Test scraping by eDesky ID."""
        mock_get_docs.return_value = [
            EdeskyDocument(
                edesky_url="https://edesky.cz/dokument/1",
                edesky_id=1,
                name="Doc 1",
                loaded_at=date(2026, 1, 1),
            ),
            EdeskyDocument(
                edesky_url="https://edesky.cz/dokument/2",
                edesky_id=2,
                name="Doc 2",
                loaded_at=date(2026, 1, 2),
            ),
        ]

        documents = scraper.scrape_by_id(62)

        assert len(documents) == 2
        assert documents[0].title == "Doc 1"
        assert documents[1].title == "Doc 2"
        mock_get_docs.assert_called_once_with(62)


class TestEdeskyApiClient:
    """Tests for EdeskyApiClient."""

    @pytest.fixture
    def client(self) -> EdeskyApiClient:
        """Create API client for testing."""
        config = EdeskyConfig(
            api_key="test-key",
            request_timeout=10,
            max_retries=1,
        )
        return EdeskyApiClient(config)

    def test_parse_dashboards_single(self, client: EdeskyApiClient) -> None:
        """Test parsing single dashboard from API response."""
        data = {
            "id": 62,
            "name": "Jihočeský kraj",
            "category": "kraj",
            "ico": "70890650",
            "nuts3_id": 1,
            "nuts3_name": "Jihočeský kraj",
            "nuts4_id": None,
            "nuts4_name": None,
        }

        dashboards = client._parse_dashboards(data)

        assert len(dashboards) == 1
        assert dashboards[0].edesky_id == 62
        assert dashboards[0].name == "Jihočeský kraj"
        assert dashboards[0].category == "kraj"
        assert dashboards[0].ico == "70890650"

    def test_parse_dashboards_list(self, client: EdeskyApiClient) -> None:
        """Test parsing list of dashboards from API response."""
        data = [
            {"id": 1, "name": "Board 1"},
            {"id": 2, "name": "Board 2"},
            {"id": 3, "name": "Board 3"},
        ]

        dashboards = client._parse_dashboards(data)

        assert len(dashboards) == 3
        assert dashboards[0].edesky_id == 1
        assert dashboards[1].edesky_id == 2
        assert dashboards[2].edesky_id == 3

    def test_parse_dashboards_invalid_items_skipped(self, client: EdeskyApiClient) -> None:
        """Test that invalid items in response are skipped."""
        data = [
            {"id": 1, "name": "Valid"},
            {"name": "Missing ID"},  # Invalid - no id
            "not a dict",  # Invalid - not a dict
            {"id": 2, "name": "Also Valid"},
        ]

        dashboards = client._parse_dashboards(data)

        assert len(dashboards) == 2
        assert dashboards[0].edesky_id == 1
        assert dashboards[1].edesky_id == 2

    def test_requires_api_key(self) -> None:
        """Test that API calls require an API key."""
        config = EdeskyConfig(api_key="")
        client = EdeskyApiClient(config)

        with pytest.raises(ScraperError, match="API key not configured"):
            client.get_dashboards()


class TestEdeskyDocument:
    """Tests for EdeskyDocument dataclass."""

    def test_create_minimal(self) -> None:
        """Test creating document with minimal fields."""
        doc = EdeskyDocument(
            edesky_url="https://edesky.cz/dokument/1",
            edesky_id=1,
            name="Test",
            loaded_at=date(2026, 1, 1),
        )

        assert doc.edesky_id == 1
        assert doc.orig_url is None
        assert doc.content is None
        assert doc.attachments == []

    def test_create_full(self) -> None:
        """Test creating document with all fields."""
        attachments = [
            EdeskyAttachment(name="file.pdf", url="http://example.com/file.pdf"),
        ]
        doc = EdeskyDocument(
            edesky_url="https://edesky.cz/dokument/1",
            edesky_id=1,
            name="Full Doc",
            loaded_at=date(2026, 1, 1),
            orig_url="http://orig.cz/doc",
            content="Text content",
            attachments=attachments,
        )

        assert doc.orig_url == "http://orig.cz/doc"
        assert doc.content == "Text content"
        assert len(doc.attachments) == 1


class TestEdeskyDashboard:
    """Tests for EdeskyDashboard dataclass."""

    def test_create_minimal(self) -> None:
        """Test creating dashboard with minimal fields."""
        dashboard = EdeskyDashboard(
            edesky_id=62,
            name="Test Board",
        )

        assert dashboard.edesky_id == 62
        assert dashboard.name == "Test Board"
        assert dashboard.category is None
        assert dashboard.nuts3_id is None

    def test_create_full(self) -> None:
        """Test creating dashboard with all fields."""
        dashboard = EdeskyDashboard(
            edesky_id=62,
            name="Jihočeský kraj",
            category="kraj",
            ico="70890650",
            nuts3_id=1,
            nuts3_name="Jihočeský kraj",
            nuts4_id=10,
            nuts4_name="Okres XY",
            parent_id=1,
            parent_name="Parent Board",
            url="http://example.com",
            latitude=49.0,
            longitude=14.5,
        )

        assert dashboard.category == "kraj"
        assert dashboard.nuts3_id == 1
        assert dashboard.latitude == 49.0

    def test_get_all_dashboards_requires_api_key(self) -> None:
        """Test that get_all_dashboards requires API key."""
        config = EdeskyConfig(api_key="")
        client = EdeskyApiClient(config)

        with pytest.raises(ScraperError, match="API key not configured"):
            client.get_all_dashboards()
