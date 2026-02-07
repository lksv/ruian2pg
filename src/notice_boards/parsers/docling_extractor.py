"""Docling-based text extraction with OCR support.

Uses Docling library (v2.70+) for document conversion with optional OCR
for scanned documents and images.

Docling supports:
- PDF documents (text layer and/or OCR)
- Office documents (DOCX, XLSX, PPTX)
- Images (PNG, JPEG, etc.)
- HTML documents

Example:
    from notice_boards.parsers.docling_extractor import DoclingExtractor

    extractor = DoclingExtractor(use_ocr=True)
    if extractor.supports("application/pdf"):
        text = extractor.extract(pdf_bytes, "application/pdf")
"""

import io
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from notice_boards.parsers.base import TextExtractionError, TextExtractor

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


@dataclass
class DoclingConfig:
    """Configuration for Docling extractor."""

    # Enable OCR for scanned documents
    use_ocr: bool = True

    # OCR backend: "tesserocr", "easyocr", "rapidocr", "ocrmac"
    ocr_backend: str = "tesserocr"

    # Force full-page OCR even for documents with text layer
    force_full_page_ocr: bool = False

    # Output format: "markdown", "text", "html"
    output_format: str = "markdown"

    # Maximum pages to process (0 = unlimited)
    max_pages: int = 0

    # Languages for OCR (ISO format, e.g., "cs-CZ", "en-US")
    ocr_languages: list[str] = field(default_factory=lambda: ["cs-CZ", "en-US"])


# Supported MIME types and their Docling format mappings
SUPPORTED_MIME_TYPES: dict[str, str] = {
    # PDF
    "application/pdf": "pdf",
    "application/x-pdf": "pdf",
    # Microsoft Office
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
    "application/msword": "doc",
    "application/vnd.ms-excel": "xls",
    "application/vnd.ms-powerpoint": "ppt",
    # Images
    "image/png": "image",
    "image/jpeg": "image",
    "image/jpg": "image",
    "image/tiff": "image",
    "image/bmp": "image",
    "image/gif": "image",
    "image/webp": "image",
    # HTML
    "text/html": "html",
    "application/xhtml+xml": "html",
}


def _is_docling_available() -> bool:
    """Check if Docling library is available."""
    try:
        import docling  # noqa: F401

        return True
    except ImportError:
        return False


class DoclingExtractor(TextExtractor):
    """Extract text from documents using Docling library.

    Supports PDF, Office documents, images with OCR capability.
    Falls back gracefully when Docling is not installed.

    Example:
        extractor = DoclingExtractor(config=DoclingConfig(use_ocr=True))
        if extractor.supports("application/pdf"):
            text = extractor.extract(pdf_bytes, "application/pdf")
    """

    SUPPORTED_TYPES = frozenset(SUPPORTED_MIME_TYPES.keys())

    def __init__(self, config: DoclingConfig | None = None) -> None:
        """Initialize Docling extractor.

        Args:
            config: Docling configuration options.
        """
        self.config = config or DoclingConfig()
        self._converter: object | None = None
        self._docling_available: bool | None = None

    @property
    def docling_available(self) -> bool:
        """Check if Docling is available (cached)."""
        if self._docling_available is None:
            self._docling_available = _is_docling_available()
        return self._docling_available

    def supports(self, mime_type: str) -> bool:
        """Check if this extractor supports the given MIME type.

        Args:
            mime_type: MIME type to check

        Returns:
            True if Docling is available and supports this type
        """
        if not self.docling_available:
            return False
        return mime_type.lower() in self.SUPPORTED_TYPES

    def _get_converter(self) -> object:
        """Get or create Docling document converter."""
        if self._converter is not None:
            return self._converter

        try:
            from docling.datamodel.base_models import InputFormat
            from docling.datamodel.pipeline_options import (
                EasyOcrOptions,
                OcrMacOptions,
                PdfPipelineOptions,
                RapidOcrOptions,
                TesseractOcrOptions,
            )
            from docling.document_converter import DocumentConverter, PdfFormatOption
        except ImportError as err:
            raise TextExtractionError(
                "Docling is not installed. Install with: pip install 'docling[easyocr]'"
            ) from err

        # Configure OCR options based on backend
        from docling.datamodel.pipeline_options import OcrOptions

        ocr_options: OcrOptions | None = None

        if self.config.use_ocr:
            if self.config.ocr_backend == "easyocr":
                ocr_options = EasyOcrOptions(
                    force_full_page_ocr=self.config.force_full_page_ocr,
                    lang=self.config.ocr_languages,
                )
            elif self.config.ocr_backend == "tesserocr":
                ocr_options = TesseractOcrOptions(
                    force_full_page_ocr=self.config.force_full_page_ocr,
                    lang=self.config.ocr_languages,
                )
            elif self.config.ocr_backend == "rapidocr":
                ocr_options = RapidOcrOptions(
                    force_full_page_ocr=self.config.force_full_page_ocr,
                )
            elif self.config.ocr_backend == "ocrmac":
                ocr_options = OcrMacOptions(
                    force_full_page_ocr=self.config.force_full_page_ocr,
                    lang=self.config.ocr_languages,
                )

        # Configure PDF pipeline
        pipeline_kwargs: dict[str, object] = {"do_ocr": self.config.use_ocr}
        if ocr_options is not None:
            pipeline_kwargs["ocr_options"] = ocr_options
        pdf_options = PdfPipelineOptions(**pipeline_kwargs)  # type: ignore[arg-type]

        # Create converter with format options
        self._converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=pdf_options),
            }
        )

        return self._converter

    def extract(self, content: bytes, mime_type: str) -> str | None:
        """Extract text from document content using Docling.

        Args:
            content: Raw file content as bytes
            mime_type: MIME type of the document

        Returns:
            Extracted text as string, or None if extraction failed

        Raises:
            TextExtractionError: If document conversion fails
        """
        if not self.supports(mime_type):
            return None

        try:
            from docling.document_converter import DocumentConverter
            from docling_core.types.io import DocumentStream
        except ImportError as err:
            raise TextExtractionError(
                "Docling is not installed. Install with: pip install 'docling[easyocr]'"
            ) from err

        try:
            converter = self._get_converter()
            assert isinstance(converter, DocumentConverter)

            # Create document stream from bytes
            doc_stream = io.BytesIO(content)

            # Determine filename from MIME type
            format_name = SUPPORTED_MIME_TYPES.get(mime_type.lower(), "pdf")
            filename = f"document.{format_name}"
            if format_name == "image":
                # Use appropriate extension for images
                if "png" in mime_type:
                    filename = "document.png"
                elif "jpeg" in mime_type or "jpg" in mime_type:
                    filename = "document.jpg"
                elif "tiff" in mime_type:
                    filename = "document.tiff"
                else:
                    filename = "document.png"

            # Create DocumentStream for Docling
            input_doc = DocumentStream(name=filename, stream=doc_stream)

            # Convert document
            result = converter.convert(input_doc)

            # Export to requested format
            if self.config.output_format == "markdown":
                return str(result.document.export_to_markdown())
            elif self.config.output_format == "html":
                return str(result.document.export_to_html())
            else:  # text
                return str(result.document.export_to_text())

        except Exception as e:
            logger.warning(f"Docling extraction failed: {e}")
            raise TextExtractionError(f"Failed to extract text with Docling: {e}") from e

    def close(self) -> None:
        """Release Docling resources."""
        self._converter = None
