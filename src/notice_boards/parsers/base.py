"""Base classes for text extraction from documents.

Provides an abstract interface for extracting text from different
document types (PDF, Word, images, etc.).
"""

from abc import ABC, abstractmethod


class TextExtractor(ABC):
    """Abstract text extractor for documents.

    Implementations should handle specific document types and
    extract plain text for further processing.

    Example:
        class PdfTextExtractor(TextExtractor):
            def extract(self, content, mime_type):
                if not self.supports(mime_type):
                    return None
                # ... extract text from PDF ...
                return extracted_text

            def supports(self, mime_type):
                return mime_type == "application/pdf"
    """

    @abstractmethod
    def extract(self, content: bytes, mime_type: str) -> str | None:
        """Extract text from document content.

        Args:
            content: Raw file content as bytes
            mime_type: MIME type of the document (e.g., "application/pdf")

        Returns:
            Extracted text as string, or None if extraction not supported
            or failed.
        """
        pass

    @abstractmethod
    def supports(self, mime_type: str) -> bool:
        """Check if this extractor supports the given MIME type.

        Args:
            mime_type: MIME type to check (e.g., "application/pdf")

        Returns:
            True if this extractor can handle the MIME type
        """
        pass


class TextExtractionError(Exception):
    """Exception raised when text extraction fails."""

    pass


class CompositeTextExtractor(TextExtractor):
    """Composite extractor that delegates to specialized extractors.

    Tries each registered extractor in order until one succeeds.

    Example:
        composite = CompositeTextExtractor()
        composite.register(PdfTextExtractor())
        composite.register(DocxTextExtractor())

        text = composite.extract(content, "application/pdf")
    """

    def __init__(self) -> None:
        """Initialize composite extractor with empty extractor list."""
        self._extractors: list[TextExtractor] = []

    def register(self, extractor: TextExtractor) -> None:
        """Register a text extractor.

        Args:
            extractor: TextExtractor instance to register
        """
        self._extractors.append(extractor)

    def extract(self, content: bytes, mime_type: str) -> str | None:
        """Extract text using the first matching extractor.

        Args:
            content: Raw file content as bytes
            mime_type: MIME type of the document

        Returns:
            Extracted text or None if no extractor supports the type
        """
        for extractor in self._extractors:
            if extractor.supports(mime_type):
                result = extractor.extract(content, mime_type)
                if result is not None:
                    return result
        return None

    def supports(self, mime_type: str) -> bool:
        """Check if any registered extractor supports the MIME type.

        Args:
            mime_type: MIME type to check

        Returns:
            True if any registered extractor supports the type
        """
        return any(e.supports(mime_type) for e in self._extractors)
