"""OFN (Open Formal Norm) scraper implementation.

OFN is the Czech Open Formal Norm for official notice boards.
This module provides a client and scraper for downloading documents
from notice boards that publish data in the OFN JSON-LD format.

OFN Specification: https://ofn.gov.cz/úřední-desky/2021-07-20/

JSON-LD Structure:
    {
        "@context": "https://ofn.gov.cz/úřední-desky/.../kontexty/úřední-deska.jsonld",
        "typ": "Úřední deska",
        "iri": "https://example.cz/opendata",
        "stránka": "https://example.cz/",
        "provozovatel": {"typ": "Osoba", "ičo": "12345678"},
        "informace": [
            {
                "typ": ["Digitální objekt", "Informace na úřední desce"],
                "iri": "https://example.cz/detail?id=123",
                "url": "https://example.cz/detail?id=123",
                "název": {"cs": "Document title"},
                "vyvěšení": {"typ": "Časový okamžik", "datum": "2026-01-15"},
                "relevantní_do": {"typ": "Časový okamžik", "datum": "2026-02-15"},
                "číslo_jednací": "ABC/123/2026",
                "spisová_značka": "SZ-123/2026",
                "agenda": [{"typ": "Agenda", "název": {"cs": "Category name"}}],
                "dokument": [
                    {
                        "typ": "Digitální objekt",
                        "název": {"cs": "filename.pdf"},
                        "url": "https://example.cz/download?id=456"
                    }
                ]
            }
        ]
    }
"""

import contextlib
import hashlib
import logging
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

import httpx

from notice_boards.scraper_config import OfnConfig
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
class OfnAttachment:
    """Attachment from OFN document.

    Attributes:
        name: Attachment filename (from název.cs)
        url: Download URL
    """

    name: str
    url: str


@dataclass
class OfnDocument:
    """Document from OFN feed.

    Attributes:
        iri: Unique IRI of the document
        title: Document title (from název.cs)
        published_at: Publication date (from vyvěšení.datum)
        valid_until: End of validity (from relevantní_do.datum)
        reference_number: Reference number (from číslo_jednací)
        file_reference: File reference (from spisová_značka)
        category: Category name (from agenda[0].název.cs)
        attachments: List of document attachments
        url: Detail page URL
    """

    iri: str
    title: str
    published_at: date
    valid_until: date | None = None
    reference_number: str | None = None
    file_reference: str | None = None
    category: str | None = None
    attachments: list[OfnAttachment] = field(default_factory=list)
    url: str | None = None


@dataclass
class OfnBoard:
    """OFN notice board metadata.

    Attributes:
        iri: IRI of the feed
        page_url: Human-readable page URL (from stránka)
        ico: Organization ICO (from provozovatel.ičo)
        name: Organization name (from provozovatel.název.cs)
        documents: List of documents from the feed
    """

    iri: str
    page_url: str | None = None
    ico: str | None = None
    name: str | None = None
    documents: list[OfnDocument] = field(default_factory=list)


class OfnClient:
    """HTTP client for OFN JSON-LD feeds.

    Handles fetching and parsing OFN notice board feeds.
    No authentication is required for OFN feeds.

    Example:
        with OfnClient() as client:
            board = client.fetch_feed("https://edeska.brno.cz/eDeska01/opendata")
            for doc in board.documents:
                print(f"{doc.title}: {len(doc.attachments)} attachments")
    """

    def __init__(self, config: OfnConfig | None = None) -> None:
        """Initialize the client.

        Args:
            config: Optional configuration, uses defaults if not provided.
        """
        self.config = config or OfnConfig()
        self._client: httpx.Client | None = None

    @property
    def client(self) -> httpx.Client:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.Client(
                timeout=self.config.request_timeout,
                headers={
                    "User-Agent": self.config.user_agent,
                    "Accept": "application/json, application/ld+json",
                },
                follow_redirects=True,
                verify=not self.config.skip_ssl_verify,
            )
        return self._client

    def close(self) -> None:
        """Close the HTTP client."""
        if self._client is not None:
            self._client.close()
            self._client = None

    def __enter__(self) -> "OfnClient":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def fetch_feed(self, url: str) -> OfnBoard:
        """Fetch and parse an OFN JSON-LD feed.

        Args:
            url: URL of the OFN feed.

        Returns:
            OfnBoard with metadata and documents.

        Raises:
            ScraperError: If request fails or JSON parsing fails.
        """
        for attempt in range(self.config.max_retries):
            try:
                response = self.client.get(url)
                response.raise_for_status()

                data = response.json()
                return self._parse_feed(data, url)

            except httpx.HTTPStatusError as e:
                logger.warning(f"OFN request failed (attempt {attempt + 1}): {e}")
                if attempt < self.config.max_retries - 1:
                    time.sleep(self.config.retry_delay * (attempt + 1))
                else:
                    msg = f"OFN request failed after {self.config.max_retries} attempts"
                    raise ScraperError(f"{msg}: {e}") from e
            except httpx.RequestError as e:
                raise ScraperError(f"Network error: {e}") from e
            except ValueError as e:
                raise ScraperError(f"Invalid JSON response: {e}") from e

        # Should not reach here
        return OfnBoard(iri=url)

    def download_attachment(self, url: str) -> bytes | None:
        """Download attachment file content.

        Args:
            url: Direct URL to the attachment file.

        Returns:
            File content as bytes or None if download fails.
        """
        try:
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

    def _parse_feed(self, data: dict[str, Any], feed_url: str) -> OfnBoard:
        """Parse JSON-LD feed into OfnBoard.

        Args:
            data: Parsed JSON data.
            feed_url: Original feed URL (used as fallback IRI).

        Returns:
            OfnBoard with parsed documents.
        """
        # Parse board metadata
        iri = data.get("iri") or feed_url
        page_url = data.get("stránka")

        # Parse provozovatel (operator)
        provozovatel = data.get("provozovatel") or {}
        ico = provozovatel.get("ičo")
        name = self._get_localized_text(provozovatel.get("název"))

        # Parse documents
        documents = []
        for info in data.get("informace") or []:
            try:
                doc = self._parse_document(info)
                if doc:
                    documents.append(doc)
            except (KeyError, ValueError) as e:
                logger.warning(f"Failed to parse document: {e}")
                continue

        logger.debug(f"Parsed {len(documents)} documents from {feed_url}")

        return OfnBoard(
            iri=iri,
            page_url=page_url,
            ico=ico,
            name=name,
            documents=documents,
        )

    def _parse_document(self, info: dict[str, Any]) -> OfnDocument | None:
        """Parse a single document from the feed.

        Args:
            info: Document info dict from "informace" array.

        Returns:
            OfnDocument or None if parsing fails.
        """
        # Required fields
        iri = info.get("iri")
        if not iri:
            logger.debug("Document missing IRI, skipping")
            return None

        title = self._get_localized_text(info.get("název")) or ""

        # Parse publication date
        vyveseni = info.get("vyvěšení") or {}
        datum_str = vyveseni.get("datum")
        if not datum_str:
            logger.debug(f"Document {iri} missing publication date, skipping")
            return None

        try:
            published_at = datetime.strptime(datum_str, "%Y-%m-%d").date()
        except ValueError:
            logger.warning(f"Invalid date format: {datum_str}")
            return None

        # Optional fields
        valid_until = None
        relevantni_do = info.get("relevantní_do") or {}
        if relevantni_do.get("datum"):
            with contextlib.suppress(ValueError):
                valid_until = datetime.strptime(relevantni_do["datum"], "%Y-%m-%d").date()

        reference_number = info.get("číslo_jednací")
        file_reference = info.get("spisová_značka")

        # Parse category from agenda
        category = None
        agenda = info.get("agenda") or []
        if agenda and isinstance(agenda, list) and len(agenda) > 0:
            category = self._get_localized_text(agenda[0].get("název"))

        # Parse attachments
        attachments = []
        for dok in info.get("dokument") or []:
            att_name = self._get_localized_text(dok.get("název")) or "attachment"
            att_url = dok.get("url")
            if att_url:
                attachments.append(OfnAttachment(name=att_name, url=att_url))

        url = info.get("url")

        return OfnDocument(
            iri=iri,
            title=title,
            published_at=published_at,
            valid_until=valid_until,
            reference_number=reference_number,
            file_reference=file_reference,
            category=category,
            attachments=attachments,
            url=url,
        )

    def _get_localized_text(
        self, value: dict[str, str] | str | None, lang: str = "cs"
    ) -> str | None:
        """Extract localized text from JSON-LD value.

        OFN uses {"cs": "text"} format for localized strings,
        but sometimes plain strings are used.

        Args:
            value: Either a dict with language keys or a plain string.
            lang: Language code to extract (default: "cs").

        Returns:
            Extracted text or None.
        """
        if value is None:
            return None
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            return value.get(lang) or next(iter(value.values()), None)
        return None


class OfnScraper(NoticeBoardScraper):
    """Scraper implementation for OFN (Open Formal Norm) notice boards.

    Fetches documents from notice boards that publish data in OFN JSON-LD format.

    Example:
        scraper = OfnScraper()
        documents = scraper.scrape(board)  # board with ofn_json_url set
        for doc in documents:
            print(f"{doc.title}: {len(doc.attachments)} attachments")

        # Or directly by URL:
        documents = scraper.scrape_by_url("https://edeska.brno.cz/eDeska01/opendata")
    """

    def __init__(
        self,
        config: OfnConfig | None = None,
        download_originals: bool = False,
    ) -> None:
        """Initialize the scraper.

        Args:
            config: Optional configuration.
            download_originals: Whether to download original attachment files.
        """
        self.config = config or OfnConfig()
        self.download_originals = download_originals
        self._client: OfnClient | None = None

    @property
    def client(self) -> OfnClient:
        """Get or create OFN client."""
        if self._client is None:
            self._client = OfnClient(self.config)
        return self._client

    def close(self) -> None:
        """Close HTTP clients."""
        if self._client is not None:
            self._client.close()
            self._client = None

    def __enter__(self) -> "OfnScraper":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def supports(self, source_type: str) -> bool:
        """Check if this scraper supports the given source type.

        Args:
            source_type: Source type identifier.

        Returns:
            True if source_type is 'ofn'.
        """
        return source_type.lower() == "ofn"

    def scrape(self, board: "NoticeBoard") -> list[DocumentData]:
        """Fetch documents from a notice board.

        Args:
            board: Notice board with ofn_json_url set.

        Returns:
            List of scraped documents.

        Raises:
            ScraperError: If scraping fails or board has no OFN URL.
        """
        if not board.ofn_json_url:
            raise ScraperError(f"Notice board {board.name} has no OFN URL")

        logger.info(f"Scraping OFN board: {board.name}")
        return self.scrape_by_url(board.ofn_json_url)

    def scrape_by_url(self, ofn_url: str) -> list[DocumentData]:
        """Fetch documents by OFN feed URL directly.

        Args:
            ofn_url: OFN JSON-LD feed URL.

        Returns:
            List of scraped documents.
        """
        logger.info(f"Scraping OFN feed: {ofn_url}")

        board = self.client.fetch_feed(ofn_url)
        logger.info(f"Found {len(board.documents)} documents")

        documents = []
        for ofn_doc in board.documents:
            doc_data = self._convert_document(ofn_doc, ofn_url)
            documents.append(doc_data)

        return documents

    def _convert_document(self, ofn_doc: OfnDocument, ofn_url: str) -> DocumentData:
        """Convert OfnDocument to DocumentData.

        Args:
            ofn_doc: OFN document.
            ofn_url: Original feed URL.

        Returns:
            DocumentData for storage.
        """
        # Generate external_id from IRI using hash
        external_id = self._generate_external_id(ofn_doc.iri)

        # Convert attachments
        attachments = []
        for att in ofn_doc.attachments:
            content = None
            if self.download_originals:
                content = self.client.download_attachment(att.url)
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
            "ofn_iri": ofn_doc.iri,
            "ofn_url": ofn_url,
        }

        if ofn_doc.reference_number:
            metadata["reference_number"] = ofn_doc.reference_number
        if ofn_doc.file_reference:
            metadata["file_reference"] = ofn_doc.file_reference
        if ofn_doc.category:
            metadata["category"] = ofn_doc.category
        if ofn_doc.url:
            metadata["detail_url"] = ofn_doc.url

        return DocumentData(
            external_id=external_id,
            title=ofn_doc.title,
            published_at=ofn_doc.published_at,
            valid_until=ofn_doc.valid_until,
            source_type="ofn",
            metadata=metadata,
            attachments=attachments,
        )

    def _generate_external_id(self, iri: str) -> str:
        """Generate a unique external ID from IRI.

        Uses SHA-256 hash truncated to 16 chars for uniqueness
        while keeping it reasonably short.

        Args:
            iri: Document IRI.

        Returns:
            External ID string.
        """
        hash_bytes = hashlib.sha256(iri.encode("utf-8")).hexdigest()
        return f"ofn_{hash_bytes[:16]}"

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
            "zip": "application/zip",
            "xml": "application/xml",
        }
        return mime_map.get(ext)
