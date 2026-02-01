"""eDesky.cz scraper implementation.

eDesky.cz is a Czech portal aggregating 3,000+ official notice boards.
This module provides clients for both the API and XML endpoints.

API Documentation: https://github.com/edesky/edesky_api

Available endpoints:
- /api/v1/dashboards - List notice boards with metadata (requires API key)
- /desky/{id}.xml - Get documents from a notice board (no API key needed)
- {edesky_url}.txt - Get extracted text for a document
"""

import logging
import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import TYPE_CHECKING, Any
from xml.etree import ElementTree

import httpx

from notice_boards.scraper_config import EdeskyConfig
from notice_boards.scrapers.base import (
    AttachmentData,
    DocumentData,
    NoticeBoardScraper,
    ScraperError,
)

if TYPE_CHECKING:
    from notice_boards.models import NoticeBoard

logger = logging.getLogger(__name__)


@dataclass
class EdeskyDashboard:
    """Notice board metadata from eDesky API."""

    edesky_id: int
    name: str
    category: str | None = None
    ico: str | None = None
    nuts3_id: int | None = None
    nuts3_name: str | None = None
    nuts4_id: int | None = None
    nuts4_name: str | None = None
    parent_id: int | None = None
    parent_name: str | None = None
    url: str | None = None
    latitude: float | None = None
    longitude: float | None = None


@dataclass
class EdeskyDocument:
    """Document from eDesky XML endpoint."""

    edesky_url: str
    edesky_id: int
    name: str
    loaded_at: date
    orig_url: str | None = None
    content: str | None = None
    attachments: list["EdeskyAttachment"] = field(default_factory=list)


@dataclass
class EdeskyAttachment:
    """Attachment from eDesky document."""

    name: str
    url: str


class EdeskyApiClient:
    """HTTP client for eDesky API (/api/v1/dashboards).

    This client is used for syncing notice board metadata.
    Requires API key for most operations.
    """

    def __init__(self, config: EdeskyConfig | None = None) -> None:
        """Initialize the API client.

        Args:
            config: Optional configuration, uses defaults if not provided.
        """
        self.config = config or EdeskyConfig()
        self._client: httpx.Client | None = None

    @property
    def client(self) -> httpx.Client:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.Client(
                base_url=self.config.base_url,
                timeout=self.config.request_timeout,
                headers={
                    "User-Agent": self.config.user_agent,
                    "Accept": "application/json",
                },
            )
        return self._client

    def close(self) -> None:
        """Close the HTTP client."""
        if self._client is not None:
            self._client.close()
            self._client = None

    def __enter__(self) -> "EdeskyApiClient":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def get_dashboards(
        self,
        edesky_id: int | None = None,
        include_subordinated: bool = False,
    ) -> list[EdeskyDashboard]:
        """Fetch notice board metadata from API.

        Args:
            edesky_id: Specific board ID to fetch (with subordinates if requested).
            include_subordinated: Include subordinated boards (children).

        Returns:
            List of EdeskyDashboard objects.

        Raises:
            ScraperError: If API request fails.
        """
        if not self.config.api_key:
            raise ScraperError("eDesky API key not configured")

        params: dict[str, str | int] = {
            "api_key": self.config.api_key,
        }

        if edesky_id is not None:
            params["id"] = edesky_id

        if include_subordinated:
            params["include_subordinated"] = 1

        for attempt in range(self.config.max_retries):
            try:
                response = self.client.get("/api/v1/dashboards", params=params)
                response.raise_for_status()

                # API returns XML, not JSON
                content_type = response.headers.get("content-type", "")
                if "xml" in content_type:
                    return self._parse_dashboards_xml(response.text)
                else:
                    # Fallback to JSON parsing
                    data = response.json()
                    return self._parse_dashboards(data)
            except httpx.HTTPStatusError as e:
                logger.warning(f"API request failed (attempt {attempt + 1}): {e}")
                if attempt < self.config.max_retries - 1:
                    time.sleep(self.config.retry_delay * (attempt + 1))
                else:
                    msg = f"API request failed after {self.config.max_retries} attempts"
                    raise ScraperError(f"{msg}: {e}") from e
            except httpx.RequestError as e:
                raise ScraperError(f"Network error: {e}") from e

        return []  # Should not reach here

    def get_all_dashboards(self) -> list[EdeskyDashboard]:
        """Fetch ALL notice boards from eDesky API.

        Uses a hybrid approach:
        1. First fetches via hierarchical top-level IDs (proven reliable)
        2. Then supplements with flat API call to catch standalone entities

        Returns:
            List of EdeskyDashboard objects (deduplicated by edesky_id).

        Raises:
            ScraperError: If API request fails.
        """
        if not self.config.api_key:
            raise ScraperError("eDesky API key not configured")

        # Known top-level eDesky IDs for Czech regions and structural divisions
        top_level_ids = [
            # Top-level structural divisions (covers all municipalities)
            112,  # Čechy (Bohemia) - ~3948 subordinates
            113,  # Morava (Moravia) - ~2477 subordinates
            59,  # Praha (capital city) - 58 subordinates
            1241,  # Instituce - ministries and state institutions (~20 subordinates)
        ]

        all_dashboards: dict[int, EdeskyDashboard] = {}

        # Step 1: Fetch via hierarchical top-level IDs (proven reliable)
        for top_id in top_level_ids:
            try:
                dashboards = self.get_dashboards(
                    edesky_id=top_id,
                    include_subordinated=True,
                )
                for dashboard in dashboards:
                    all_dashboards[dashboard.edesky_id] = dashboard

                logger.info(f"Fetched {len(dashboards)} boards from region/category {top_id}")
            except ScraperError as e:
                logger.warning(f"Failed to fetch boards for ID {top_id}: {e}")
                continue

        hierarchical_count = len(all_dashboards)
        logger.info(f"Hierarchical fetch complete: {hierarchical_count} unique boards")

        # Step 2: Supplement with flat API call to catch standalone entities
        # (entities with parent=None that are not under any hierarchy)
        try:
            dashboards = self.get_dashboards()  # No ID = returns all as flat list
            new_count = 0
            for dashboard in dashboards:
                if dashboard.edesky_id not in all_dashboards:
                    all_dashboards[dashboard.edesky_id] = dashboard
                    new_count += 1

            logger.info(
                f"Flat API call returned {len(dashboards)} boards, "
                f"{new_count} new (standalone entities)"
            )
        except ScraperError as e:
            logger.warning(f"Flat API call failed (standalone entities may be missed): {e}")

        logger.info(f"Total unique boards fetched: {len(all_dashboards)}")
        return list(all_dashboards.values())

    def _parse_dashboards(self, data: dict[str, Any] | list[Any]) -> list[EdeskyDashboard]:
        """Parse API response into EdeskyDashboard objects."""
        dashboards = []

        # API can return a single object or a list
        items = data if isinstance(data, list) else [data]

        for item in items:
            if not isinstance(item, dict):
                continue

            try:
                dashboard = EdeskyDashboard(
                    edesky_id=int(item["id"]),
                    name=item.get("name", ""),
                    category=item.get("category"),
                    ico=item.get("ico"),
                    nuts3_id=int(item["nuts3_id"]) if item.get("nuts3_id") else None,
                    nuts3_name=item.get("nuts3_name"),
                    nuts4_id=int(item["nuts4_id"]) if item.get("nuts4_id") else None,
                    nuts4_name=item.get("nuts4_name"),
                    parent_id=int(item["parent_id"]) if item.get("parent_id") else None,
                    parent_name=item.get("parent_name"),
                    url=item.get("url"),
                    latitude=float(item["latitude"]) if item.get("latitude") else None,
                    longitude=float(item["longitude"]) if item.get("longitude") else None,
                )
                dashboards.append(dashboard)
            except (KeyError, ValueError) as e:
                logger.warning(f"Failed to parse dashboard: {e}")
                continue

        return dashboards

    def _parse_dashboards_xml(self, xml_content: str) -> list[EdeskyDashboard]:
        """Parse XML API response into EdeskyDashboard objects.

        XML structure from /api/v1/dashboards:
            <dashboards>
              <dashboard edesky_id="62" name="Jihočeský kraj" category="samosprava"
                         ovm_ico="70890650" nuts3_id="62" nuts3_name="..."
                         nuts4_id="" nuts4_name="" parent_id="112"
                         parent_name="Čechy" url="..." latitude="49.0"
                         longitude="14.5" ruian_kod="35"/>
              ...
            </dashboards>
        """
        try:
            root = ElementTree.fromstring(xml_content)
        except ElementTree.ParseError as e:
            raise ScraperError(f"Failed to parse XML: {e}") from e

        dashboards = []

        # Find all dashboard elements (could be root or children)
        dashboard_elements = root.findall(".//dashboard")
        if not dashboard_elements and root.tag == "dashboard":
            dashboard_elements = [root]

        for elem in dashboard_elements:
            try:
                edesky_id_str = elem.get("id") or elem.get("edesky_id")
                if not edesky_id_str:
                    continue

                # Extract optional integer/float fields
                nuts3_id_str = elem.get("nuts3_id")
                nuts4_id_str = elem.get("nuts4_id")
                parent_id_str = elem.get("parent_id")
                latitude_str = elem.get("latitude")
                longitude_str = elem.get("longitude")

                dashboard = EdeskyDashboard(
                    edesky_id=int(edesky_id_str),
                    name=elem.get("name", ""),
                    category=elem.get("category"),
                    # API returns ICO as 'ovm_ico' or 'ico'
                    ico=elem.get("ovm_ico") or elem.get("ico"),
                    nuts3_id=int(nuts3_id_str) if nuts3_id_str else None,
                    nuts3_name=elem.get("nuts3_name"),
                    nuts4_id=int(nuts4_id_str) if nuts4_id_str else None,
                    nuts4_name=elem.get("nuts4_name"),
                    parent_id=int(parent_id_str) if parent_id_str else None,
                    parent_name=elem.get("parent_name"),
                    url=elem.get("url"),
                    latitude=float(latitude_str) if latitude_str else None,
                    longitude=float(longitude_str) if longitude_str else None,
                )
                dashboards.append(dashboard)
            except (ValueError, TypeError) as e:
                logger.warning(f"Failed to parse dashboard element: {e}")
                continue

        return dashboards


class EdeskyXmlClient:
    """HTTP client for eDesky XML endpoint (/desky/{id}.xml).

    This client is used for fetching documents from a notice board.
    No API key required.

    XML Response structure:
        <dashboard edesky_id='62' name='Jihočeský kraj'>
          <documents>
            <document edesky_url='https://edesky.cz/dokument/123'
                      loaded_at='2026-01-30'
                      name='Document title'
                      orig_url='https://original-source/...'>
              <content>Optional inline content</content>
              <attachment name='file.pdf' url='https://original/file.pdf'/>
            </document>
          </documents>
        </dashboard>
    """

    def __init__(self, config: EdeskyConfig | None = None) -> None:
        """Initialize the XML client.

        Args:
            config: Optional configuration, uses defaults if not provided.
        """
        self.config = config or EdeskyConfig()
        self._client: httpx.Client | None = None

    @property
    def client(self) -> httpx.Client:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.Client(
                base_url=self.config.base_url,
                timeout=self.config.request_timeout,
                headers={
                    "User-Agent": self.config.user_agent,
                    "Accept": "application/xml",
                },
            )
        return self._client

    def close(self) -> None:
        """Close the HTTP client."""
        if self._client is not None:
            self._client.close()
            self._client = None

    def __enter__(self) -> "EdeskyXmlClient":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def get_documents(self, edesky_id: int) -> list[EdeskyDocument]:
        """Fetch documents from a notice board via XML endpoint.

        Args:
            edesky_id: eDesky board ID.

        Returns:
            List of EdeskyDocument objects (up to 100 most recent).

        Raises:
            ScraperError: If request fails or XML parsing fails.
        """
        url = f"/desky/{edesky_id}.xml"

        for attempt in range(self.config.max_retries):
            try:
                response = self.client.get(url)
                response.raise_for_status()
                return self._parse_xml(response.text)
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404:
                    logger.warning(f"Notice board {edesky_id} not found")
                    return []
                logger.warning(f"XML request failed (attempt {attempt + 1}): {e}")
                if attempt < self.config.max_retries - 1:
                    time.sleep(self.config.retry_delay * (attempt + 1))
                else:
                    raise ScraperError(f"XML request failed: {e}") from e
            except httpx.RequestError as e:
                raise ScraperError(f"Network error: {e}") from e

        return []  # Should not reach here

    def _parse_xml(self, xml_content: str) -> list[EdeskyDocument]:
        """Parse XML response into EdeskyDocument objects."""
        try:
            root = ElementTree.fromstring(xml_content)
        except ElementTree.ParseError as e:
            raise ScraperError(f"Failed to parse XML: {e}") from e

        documents = []

        for doc_elem in root.findall(".//document"):
            edesky_url = doc_elem.get("edesky_url", "")
            if not edesky_url:
                continue

            # Extract edesky_id from URL
            edesky_id = self._extract_document_id(edesky_url)
            if edesky_id is None:
                logger.warning(f"Could not extract document ID from: {edesky_url}")
                continue

            # Parse date
            loaded_at_str = doc_elem.get("loaded_at", "")
            try:
                loaded_at = datetime.strptime(loaded_at_str, "%Y-%m-%d").date()
            except ValueError:
                loaded_at = date.today()

            # Parse attachments
            attachments = []
            for att_elem in doc_elem.findall("attachment"):
                att_name = att_elem.get("name", "")
                att_url = att_elem.get("url", "")
                if att_name and att_url:
                    attachments.append(EdeskyAttachment(name=att_name, url=att_url))

            # Get content if present
            content_elem = doc_elem.find("content")
            content = content_elem.text if content_elem is not None and content_elem.text else None

            doc = EdeskyDocument(
                edesky_url=edesky_url,
                edesky_id=edesky_id,
                name=doc_elem.get("name", ""),
                loaded_at=loaded_at,
                orig_url=doc_elem.get("orig_url"),
                content=content,
                attachments=attachments,
            )
            documents.append(doc)

        return documents

    def _extract_document_id(self, edesky_url: str) -> int | None:
        """Extract document ID from eDesky URL.

        URL format: https://edesky.cz/dokument/12345
        """
        match = re.search(r"/dokument/(\d+)", edesky_url)
        if match:
            return int(match.group(1))
        return None

    def get_document_text(self, edesky_url: str) -> str | None:
        """Download extracted text for a document.

        Args:
            edesky_url: eDesky document URL (e.g., https://edesky.cz/dokument/123).

        Returns:
            Extracted text content or None if not available.
        """
        text_url = f"{edesky_url}.txt"

        try:
            response = self.client.get(text_url)
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return response.text
        except httpx.HTTPStatusError:
            return None
        except httpx.RequestError as e:
            logger.warning(f"Failed to download text from {text_url}: {e}")
            return None

    def download_attachment(self, url: str) -> bytes | None:
        """Download attachment file content.

        Args:
            url: Direct URL to the attachment file.

        Returns:
            File content as bytes or None if download fails.
        """
        try:
            # Use a longer timeout for file downloads
            response = self.client.get(
                url,
                timeout=60.0,
                follow_redirects=True,
            )
            response.raise_for_status()
            return response.content
        except (httpx.HTTPStatusError, httpx.RequestError) as e:
            logger.warning(f"Failed to download attachment from {url}: {e}")
            return None


class EdeskyScraper(NoticeBoardScraper):
    """Scraper implementation for eDesky.cz.

    Uses the XML endpoint (/desky/{id}.xml) to fetch documents
    and optionally downloads text and original attachments.

    Example:
        scraper = EdeskyScraper()
        documents = scraper.scrape(board)
        for doc in documents:
            print(f"{doc.title}: {len(doc.attachments)} attachments")
    """

    def __init__(
        self,
        config: EdeskyConfig | None = None,
        download_text: bool = False,
        download_originals: bool = False,
    ) -> None:
        """Initialize the scraper.

        Args:
            config: Optional configuration.
            download_text: Whether to download extracted text from eDesky.
            download_originals: Whether to download original attachment files.
        """
        self.config = config or EdeskyConfig()
        self.download_text = download_text
        self.download_originals = download_originals
        self._xml_client: EdeskyXmlClient | None = None

    @property
    def xml_client(self) -> EdeskyXmlClient:
        """Get or create XML client."""
        if self._xml_client is None:
            self._xml_client = EdeskyXmlClient(self.config)
        return self._xml_client

    def close(self) -> None:
        """Close HTTP clients."""
        if self._xml_client is not None:
            self._xml_client.close()
            self._xml_client = None

    def __enter__(self) -> "EdeskyScraper":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def supports(self, source_type: str) -> bool:
        """Check if this scraper supports the given source type.

        Args:
            source_type: Source type identifier.

        Returns:
            True if source_type is 'edesky'.
        """
        return source_type.lower() == "edesky"

    def scrape(self, board: "NoticeBoard") -> list[DocumentData]:
        """Fetch documents from a notice board.

        Args:
            board: Notice board with edesky_url or edesky_id set.

        Returns:
            List of scraped documents.

        Raises:
            ScraperError: If scraping fails or board has no eDesky reference.
        """
        edesky_id = self._get_edesky_id(board)
        if edesky_id is None:
            raise ScraperError(f"Notice board {board.name} has no eDesky reference")

        logger.info(f"Scraping eDesky board {edesky_id}: {board.name}")

        # Fetch documents via XML endpoint
        edesky_docs = self.xml_client.get_documents(edesky_id)
        logger.info(f"Found {len(edesky_docs)} documents")

        # Convert to DocumentData
        documents = []
        for edesky_doc in edesky_docs:
            doc_data = self._convert_document(edesky_doc)
            documents.append(doc_data)

        return documents

    def scrape_by_id(self, edesky_id: int) -> list[DocumentData]:
        """Fetch documents by eDesky board ID directly.

        Args:
            edesky_id: eDesky notice board ID.

        Returns:
            List of scraped documents.
        """
        logger.info(f"Scraping eDesky board {edesky_id}")

        edesky_docs = self.xml_client.get_documents(edesky_id)
        logger.info(f"Found {len(edesky_docs)} documents")

        documents = []
        for edesky_doc in edesky_docs:
            doc_data = self._convert_document(edesky_doc)
            documents.append(doc_data)

        return documents

    def _get_edesky_id(self, board: "NoticeBoard") -> int | None:
        """Extract eDesky ID from notice board.

        First checks edesky_id attribute, then extracts from edesky_url.
        """
        # Check if we have edesky_id directly (from migration v5)
        if hasattr(board, "edesky_id") and board.edesky_id is not None:
            return board.edesky_id

        # Extract from edesky_url
        if board.edesky_url:
            match = re.search(r"/desky/(\d+)", board.edesky_url)
            if match:
                return int(match.group(1))

        return None

    def _convert_document(self, edesky_doc: EdeskyDocument) -> DocumentData:
        """Convert EdeskyDocument to DocumentData."""
        # Download text if requested
        extracted_text = None
        if self.download_text:
            extracted_text = self.xml_client.get_document_text(edesky_doc.edesky_url)
            if extracted_text:
                logger.debug(f"Downloaded text for document {edesky_doc.edesky_id}")

        # Convert attachments
        attachments = []
        for att in edesky_doc.attachments:
            content = None
            if self.download_originals:
                content = self.xml_client.download_attachment(att.url)
                if content:
                    logger.debug(f"Downloaded attachment: {att.name}")

            mime_type = self._guess_mime_type(att.name)
            attachments.append(
                AttachmentData(
                    filename=att.name,
                    url=att.url,
                    mime_type=mime_type,
                    content=content,
                )
            )

        # Build metadata
        metadata: dict[str, str | int | bool | None] = {
            "edesky_url": edesky_doc.edesky_url,
            "edesky_id": edesky_doc.edesky_id,
            "orig_url": edesky_doc.orig_url,
        }

        if extracted_text:
            metadata["extracted_text"] = extracted_text

        return DocumentData(
            external_id=str(edesky_doc.edesky_id),
            title=edesky_doc.name,
            published_at=edesky_doc.loaded_at,
            metadata=metadata,
            attachments=attachments,
        )

    def _guess_mime_type(self, filename: str) -> str | None:
        """Guess MIME type from filename extension."""
        ext = filename.lower().split(".")[-1] if "." in filename else ""
        mime_map = {
            "pdf": "application/pdf",
            "doc": "application/msword",
            "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "xls": "application/vnd.ms-excel",
            "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "png": "image/png",
            "gif": "image/gif",
            "txt": "text/plain",
            "rtf": "application/rtf",
            "odt": "application/vnd.oasis.opendocument.text",
            "ods": "application/vnd.oasis.opendocument.spreadsheet",
        }
        return mime_map.get(ext)
