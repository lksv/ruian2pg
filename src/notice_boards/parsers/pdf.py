"""PDF text extraction.

Extracts text from PDF documents with text layers.
For scanned PDFs (images), OCR will be needed (not implemented here).
"""

import io
from typing import TYPE_CHECKING

from notice_boards.parsers.base import TextExtractionError, TextExtractor

if TYPE_CHECKING:
    pass


class PdfTextExtractor(TextExtractor):
    """Extract text from PDF documents with text layers.

    Uses PyMuPDF (fitz) for text extraction. This extractor only works
    with PDFs that have a text layer - scanned documents will return
    empty or minimal text.

    For scanned PDFs, use TesseractOcrExtractor or similar OCR-based
    extractor (not implemented yet).

    Example:
        extractor = PdfTextExtractor()
        if extractor.supports("application/pdf"):
            text = extractor.extract(pdf_bytes, "application/pdf")
            print(text)
    """

    # Supported MIME types
    SUPPORTED_TYPES = frozenset(
        [
            "application/pdf",
            "application/x-pdf",
        ]
    )

    def supports(self, mime_type: str) -> bool:
        """Check if this extractor supports the given MIME type.

        Args:
            mime_type: MIME type to check

        Returns:
            True for PDF MIME types
        """
        return mime_type.lower() in self.SUPPORTED_TYPES

    def extract(self, content: bytes, mime_type: str) -> str | None:
        """Extract text from PDF content.

        Args:
            content: Raw PDF file content as bytes
            mime_type: MIME type (should be application/pdf)

        Returns:
            Extracted text as string, or None if extraction failed

        Raises:
            TextExtractionError: If PDF parsing fails
        """
        if not self.supports(mime_type):
            return None

        try:
            import fitz  # PyMuPDF
        except ImportError as err:
            raise TextExtractionError(
                "PyMuPDF (fitz) is not installed. Install with: pip install pymupdf"
            ) from err

        try:
            # Open PDF from bytes
            pdf_stream = io.BytesIO(content)
            doc = fitz.open(stream=pdf_stream, filetype="pdf")

            # Extract text from all pages
            text_parts = []
            for page_num in range(len(doc)):
                page = doc.load_page(page_num)
                text = page.get_text()
                if text.strip():
                    text_parts.append(text)

            doc.close()

            if not text_parts:
                # PDF might be scanned/image-based
                return ""

            return "\n\n".join(text_parts)

        except Exception as e:
            raise TextExtractionError(f"Failed to extract text from PDF: {e}") from e


class PdfPlumberExtractor(TextExtractor):
    """Extract text from PDF using pdfplumber library.

    Alternative PDF extractor using pdfplumber, which may produce
    better results for certain types of PDFs (tables, forms).

    Example:
        extractor = PdfPlumberExtractor()
        text = extractor.extract(pdf_bytes, "application/pdf")
    """

    SUPPORTED_TYPES = frozenset(["application/pdf", "application/x-pdf"])

    def supports(self, mime_type: str) -> bool:
        """Check if this extractor supports the given MIME type."""
        return mime_type.lower() in self.SUPPORTED_TYPES

    def extract(self, content: bytes, mime_type: str) -> str | None:
        """Extract text from PDF content using pdfplumber.

        Args:
            content: Raw PDF file content as bytes
            mime_type: MIME type (should be application/pdf)

        Returns:
            Extracted text as string, or None if extraction failed
        """
        if not self.supports(mime_type):
            return None

        try:
            import pdfplumber
        except ImportError as err:
            raise TextExtractionError(
                "pdfplumber is not installed. Install with: pip install pdfplumber"
            ) from err

        try:
            pdf_stream = io.BytesIO(content)
            text_parts = []

            with pdfplumber.open(pdf_stream) as pdf:
                for page in pdf.pages:
                    text = page.extract_text()
                    if text and text.strip():
                        text_parts.append(text)

            if not text_parts:
                return ""

            return "\n\n".join(text_parts)

        except Exception as e:
            raise TextExtractionError(f"Failed to extract text from PDF: {e}") from e
