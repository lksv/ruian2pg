"""Notice board services."""

from notice_boards.services.attachment_downloader import (
    AttachmentDownloader,
    DownloadConfig,
    DownloadResult,
    DownloadStats,
    PendingAttachment,
)
from notice_boards.services.text_extractor import (
    ExtractionResult,
    ExtractionStats,
    TextExtractionService,
)

__all__ = [
    "AttachmentDownloader",
    "DownloadConfig",
    "DownloadResult",
    "DownloadStats",
    "ExtractionResult",
    "ExtractionStats",
    "PendingAttachment",
    "TextExtractionService",
]
