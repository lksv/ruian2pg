"""Scrapers for notice board sources.

This module contains scraper implementations for different notice board
systems (GINIS, Vismo, eDesky, OFN, etc.).
"""

from notice_boards.scrapers.base import (
    AttachmentData,
    DocumentData,
    NoticeBoardScraper,
    ScraperError,
)
from notice_boards.scrapers.edesky import (
    EdeskyApiClient,
    EdeskyAttachment,
    EdeskyDashboard,
    EdeskyDocument,
    EdeskyScraper,
    EdeskyXmlClient,
)
from notice_boards.scrapers.ofn import (
    OfnAttachment,
    OfnBoard,
    OfnClient,
    OfnDocument,
    OfnScraper,
)

__all__ = [
    # Base classes
    "NoticeBoardScraper",
    "DocumentData",
    "AttachmentData",
    "ScraperError",
    # eDesky
    "EdeskyApiClient",
    "EdeskyXmlClient",
    "EdeskyScraper",
    "EdeskyDashboard",
    "EdeskyDocument",
    "EdeskyAttachment",
    # OFN
    "OfnClient",
    "OfnScraper",
    "OfnDocument",
    "OfnAttachment",
    "OfnBoard",
]
