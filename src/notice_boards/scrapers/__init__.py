"""Scrapers for notice board sources.

This module contains scraper implementations for different notice board
systems (GINIS, Vismo, eDesky, etc.).

NOTE: Scrapers are NOT implemented yet. This is a placeholder for
future development.
"""

from notice_boards.scrapers.base import DocumentData, NoticeBoardScraper

__all__ = [
    "NoticeBoardScraper",
    "DocumentData",
]
