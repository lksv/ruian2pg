"""Parsers for document text extraction and reference extraction."""

import logging

from notice_boards.parsers.base import CompositeTextExtractor, TextExtractor
from notice_boards.parsers.pdf import PdfPlumberExtractor, PdfTextExtractor
from notice_boards.parsers.references import (
    AddressRef,
    LvRef,
    ParcelRef,
    ReferenceExtractor,
    StreetRef,
)

logger = logging.getLogger(__name__)

__all__ = [
    "TextExtractor",
    "CompositeTextExtractor",
    "PdfTextExtractor",
    "PdfPlumberExtractor",
    "ReferenceExtractor",
    "ParcelRef",
    "AddressRef",
    "StreetRef",
    "LvRef",
    "create_default_extractor",
]


def create_default_extractor(
    use_ocr: bool = True,
    ocr_backend: str = "easyocr",
    force_full_page_ocr: bool = False,
    output_format: str = "markdown",
) -> TextExtractor:
    """Create a default text extractor with fallback chain.

    Creates a composite extractor that tries extractors in order:
    1. DoclingExtractor (if installed) - best quality, OCR support
    2. PdfTextExtractor (PyMuPDF) - fast, text-layer only
    3. PdfPlumberExtractor - good for tables

    Args:
        use_ocr: Enable OCR for scanned documents (Docling only).
        ocr_backend: OCR backend to use ("easyocr", "tesserocr", "rapidocr").
        force_full_page_ocr: Force OCR even for documents with text layer.
        output_format: Output format for Docling ("markdown", "text", "html").

    Returns:
        TextExtractor instance (composite or single extractor)

    Example:
        extractor = create_default_extractor(use_ocr=True)
        text = extractor.extract(pdf_bytes, "application/pdf")
    """
    composite = CompositeTextExtractor()

    # Try Docling first (best quality, OCR support)
    try:
        from notice_boards.parsers.docling_extractor import DoclingConfig, DoclingExtractor

        docling_config = DoclingConfig(
            use_ocr=use_ocr,
            ocr_backend=ocr_backend,
            force_full_page_ocr=force_full_page_ocr,
            output_format=output_format,
        )
        docling_extractor = DoclingExtractor(config=docling_config)

        # Only add if Docling is actually available
        if docling_extractor.docling_available:
            composite.register(docling_extractor)
            logger.debug("Docling extractor registered")
        else:
            logger.debug("Docling not available, skipping")

    except ImportError:
        logger.debug("Docling not installed, skipping")

    # Add PyMuPDF extractor (fast, text-layer only)
    try:
        composite.register(PdfTextExtractor())
        logger.debug("PyMuPDF extractor registered")
    except Exception as e:
        logger.debug(f"PyMuPDF not available: {e}")

    # Add pdfplumber extractor (good for tables)
    try:
        composite.register(PdfPlumberExtractor())
        logger.debug("pdfplumber extractor registered")
    except Exception as e:
        logger.debug(f"pdfplumber not available: {e}")

    return composite
