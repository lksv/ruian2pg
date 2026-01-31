"""Reference extraction from document text.

This module contains dataclasses for extracted references and a stub
ReferenceExtractor class. The actual extraction logic will be implemented
via LLM with tools.
"""

from dataclasses import dataclass


@dataclass
class ParcelRef:
    """Extracted parcel reference from document text.

    Attributes:
        cadastral_area_code: Cadastral area code (e.g., 610372)
        cadastral_area_name: Cadastral area name (e.g., "Veveří")
        parcel_number: Main parcel number (e.g., 592)
        parcel_sub_number: Sub-number if any (e.g., 2 for "592/2")
        raw_text: Original text from document (e.g., "parcela č. 592/2 v k.ú. Veveří")
        text_start: Start position in source text
        text_end: End position in source text
        confidence: Extraction confidence score (0.0 - 1.0)
    """

    cadastral_area_code: int | None
    cadastral_area_name: str | None
    parcel_number: int
    parcel_sub_number: int | None
    raw_text: str
    text_start: int
    text_end: int
    confidence: float = 1.0


@dataclass
class AddressRef:
    """Extracted address reference from document text.

    Attributes:
        municipality_name: Municipality name (e.g., "Brno")
        street_name: Street name (e.g., "Kounicova")
        house_number: House number / číslo popisné (e.g., 67)
        orientation_number: Orientation number / číslo orientační (e.g., 12)
        postal_code: Postal code / PSČ (e.g., 60200)
        raw_text: Original text from document
        text_start: Start position in source text
        text_end: End position in source text
        confidence: Extraction confidence score (0.0 - 1.0)
    """

    municipality_name: str | None
    street_name: str | None
    house_number: int | None
    orientation_number: int | None
    postal_code: int | None
    raw_text: str
    text_start: int
    text_end: int
    confidence: float = 1.0


@dataclass
class StreetRef:
    """Extracted street reference from document text.

    Attributes:
        municipality_name: Municipality name (e.g., "Brno")
        street_name: Street name (e.g., "Kounicova")
        raw_text: Original text from document
        text_start: Start position in source text
        text_end: End position in source text
        confidence: Extraction confidence score (0.0 - 1.0)
    """

    municipality_name: str | None
    street_name: str
    raw_text: str
    text_start: int
    text_end: int
    confidence: float = 1.0


@dataclass
class LvRef:
    """Extracted ownership sheet (LV) reference from document text.

    Attributes:
        cadastral_area_code: Cadastral area code
        cadastral_area_name: Cadastral area name
        lv_number: Ownership sheet number (číslo listu vlastnictví)
        raw_text: Original text from document
        text_start: Start position in source text
        text_end: End position in source text
        confidence: Extraction confidence score (0.0 - 1.0)
    """

    cadastral_area_code: int | None
    cadastral_area_name: str | None
    lv_number: int
    raw_text: str
    text_start: int
    text_end: int
    confidence: float = 1.0


class ReferenceExtractor:
    """Extract references to parcels, addresses, streets from text.

    This is a stub class. The actual extraction logic will be implemented
    via LLM with tools that can:
    1. Parse text to find potential references
    2. Validate references using RuianValidator
    3. Return structured extraction results

    Example patterns that should be recognized:
    - Parcels: "parcela č. 592/2 v k.ú. Veveří", "pozemek parc.č. 1234"
    - Addresses: "Kounicova 67, Brno", "Brno, ul. Kounicova 67/12"
    - Streets: "ulice Kounicova", "v ulici Cejl"
    - LV: "LV č. 1234 pro k.ú. Veveří"
    """

    def extract_parcels(self, text: str) -> list[ParcelRef]:
        """Extract parcel references from text.

        Args:
            text: Document text to analyze

        Returns:
            List of extracted parcel references

        Raises:
            NotImplementedError: Always - will be implemented via LLM
        """
        _ = text
        raise NotImplementedError("Will be implemented via LLM")

    def extract_addresses(self, text: str) -> list[AddressRef]:
        """Extract address references from text.

        Args:
            text: Document text to analyze

        Returns:
            List of extracted address references

        Raises:
            NotImplementedError: Always - will be implemented via LLM
        """
        _ = text
        raise NotImplementedError("Will be implemented via LLM")

    def extract_streets(self, text: str) -> list[StreetRef]:
        """Extract street references from text.

        Args:
            text: Document text to analyze

        Returns:
            List of extracted street references

        Raises:
            NotImplementedError: Always - will be implemented via LLM
        """
        _ = text
        raise NotImplementedError("Will be implemented via LLM")

    def extract_lvs(self, text: str) -> list[LvRef]:
        """Extract ownership sheet (LV) references from text.

        Args:
            text: Document text to analyze

        Returns:
            List of extracted LV references

        Raises:
            NotImplementedError: Always - will be implemented via LLM
        """
        _ = text
        raise NotImplementedError("Will be implemented via LLM")

    def extract_all(
        self, text: str
    ) -> tuple[list[ParcelRef], list[AddressRef], list[StreetRef], list[LvRef]]:
        """Extract all types of references from text.

        Args:
            text: Document text to analyze

        Returns:
            Tuple of (parcel_refs, address_refs, street_refs, lv_refs)

        Raises:
            NotImplementedError: Always - will be implemented via LLM
        """
        _ = text
        raise NotImplementedError("Will be implemented via LLM")
