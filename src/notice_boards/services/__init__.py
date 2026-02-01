"""Notice board services."""

from notice_boards.services.attachment_downloader import (
    AttachmentDownloader,
    DownloadConfig,
    DownloadResult,
    DownloadStats,
    PendingAttachment,
)
from notice_boards.services.text_extractor import (
    ExtractionConfig,
    ExtractionResult,
    ExtractionStats,
    PendingExtraction,
    TextExtractionService,
)

__all__ = [
    "AttachmentDownloader",
    "DownloadConfig",
    "DownloadResult",
    "DownloadStats",
    "ExtractionConfig",
    "ExtractionResult",
    "ExtractionStats",
    "PendingAttachment",
    "PendingExtraction",
    "TextExtractionService",
]
