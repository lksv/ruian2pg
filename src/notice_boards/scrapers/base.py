"""Base classes for notice board scrapers.

NOTE: Scrapers are NOT implemented yet. This module contains abstract
base classes and data structures that will be used when scrapers are
implemented.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from notice_boards.models import NoticeBoard


@dataclass
class AttachmentData:
    """Data for a document attachment from scraping.

    Attributes:
        filename: Original filename
        url: Download URL
        mime_type: MIME type if known
        content: Downloaded content (None if not yet downloaded)
    """

    filename: str
    url: str
    mime_type: str | None = None
    content: bytes | None = None


@dataclass
class DocumentData:
    """Data from a scraped document.

    Represents a document as retrieved from a notice board source.

    Attributes:
        external_id: ID from the source system
        title: Document title
        published_at: Publication date
        valid_from: Start of validity period (optional)
        valid_until: End of validity period (optional)
        description: Document description (optional)
        source_type: Type from source system (optional)
        metadata: Additional metadata from source
        attachments: List of document attachments
    """

    external_id: str
    title: str
    published_at: date
    valid_from: date | None = None
    valid_until: date | None = None
    description: str | None = None
    source_type: str | None = None
    metadata: dict[str, str | int | bool | None] = field(default_factory=dict)
    attachments: list[AttachmentData] = field(default_factory=list)


class NoticeBoardScraper(ABC):
    """Abstract scraper for notice boards.

    Implementations should handle specific notice board systems
    (GINIS, Vismo, eDesky, OFN, etc.).

    NOTE: This is a placeholder. Scrapers are NOT implemented yet.

    Example:
        class GinisScraper(NoticeBoardScraper):
            def scrape(self, board):
                # Fetch documents from GINIS system
                response = httpx.get(board.source_url)
                # Parse and return documents
                return [DocumentData(...), ...]
    """

    @abstractmethod
    def scrape(self, board: "NoticeBoard") -> list[DocumentData]:
        """Fetch new documents from notice board.

        Args:
            board: Notice board to scrape

        Returns:
            List of scraped documents

        Raises:
            ScraperError: If scraping fails
        """
        pass

    @abstractmethod
    def supports(self, source_type: str) -> bool:
        """Check if this scraper supports the given source type.

        Args:
            source_type: Source type (e.g., "ginis", "vismo")

        Returns:
            True if this scraper can handle the source type
        """
        pass


class ScraperError(Exception):
    """Exception raised when scraping fails."""

    pass
