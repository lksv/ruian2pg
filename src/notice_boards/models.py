"""Data models for notice board documents.

These are simple dataclasses representing database entities.
No ORM is used - direct SQL queries are preferred.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any


@dataclass
class NoticeBoard:
    """Notice board source - a municipality or public authority."""

    id: int | None = None
    municipality_code: int | None = None
    name: str = ""
    abbreviation: str | None = None
    ico: str | None = None
    source_url: str | None = None
    edesky_url: str | None = None
    ofn_json_url: str | None = None
    source_type: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    address_street: str | None = None
    address_city: str | None = None
    address_district: str | None = None
    address_postal_code: str | None = None
    address_region: str | None = None
    address_point_id: int | None = None
    data_box_id: str | None = None
    emails: list[str] = field(default_factory=list)
    legal_form_code: int | None = None
    legal_form_label: str | None = None
    board_type: str | None = None
    nutslau: str | None = None
    coat_of_arms_url: str | None = None
    is_active: bool = True
    last_scraped_at: datetime | None = None
    scrape_interval_hours: int = 24
    created_at: datetime | None = None
    updated_at: datetime | None = None
    # eDesky integration fields (migration v5)
    edesky_id: int | None = None
    edesky_category: str | None = None
    nuts3_id: int | None = None
    nuts3_name: str | None = None
    nuts4_id: int | None = None
    nuts4_name: str | None = None
    edesky_parent_id: int | None = None
    edesky_parent_name: str | None = None


@dataclass
class DocumentType:
    """Document type classification."""

    id: int | None = None
    source_name: str | None = None
    source_board_id: int | None = None
    code: str = ""
    name: str = ""
    category: str | None = None


@dataclass
class Document:
    """Document from a notice board."""

    id: int | None = None
    notice_board_id: int = 0
    document_type_id: int | None = None
    external_id: str | None = None
    title: str = ""
    description: str | None = None
    published_at: date | None = None
    valid_from: date | None = None
    valid_until: date | None = None
    source_metadata: dict[str, Any] | None = None
    source_document_type: str | None = None
    parse_status: str = "pending"
    parsed_at: datetime | None = None
    parse_error: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    # eDesky integration fields (migration v5)
    edesky_url: str | None = None
    orig_url: str | None = None
    extracted_text_path: str | None = None


@dataclass
class Attachment:
    """Attachment file belonging to a document."""

    id: int | None = None
    document_id: int = 0
    filename: str = ""
    mime_type: str = ""
    file_size_bytes: int | None = None
    storage_path: str = ""
    sha256_hash: str | None = None
    parse_status: str = "pending"
    parsed_at: datetime | None = None
    extracted_text: str | None = None
    parse_error: str | None = None
    position: int = 0
    created_at: datetime | None = None
    # eDesky integration fields (migration v5)
    orig_url: str | None = None


@dataclass
class RefType:
    """Reference type classification."""

    id: int | None = None
    code: str = ""
    name: str = ""
    description: str | None = None


@dataclass
class ParcelRef:
    """Reference to a parcel extracted from a document."""

    id: int | None = None
    attachment_id: int = 0
    ref_type_id: int = 0
    parcel_id: int | None = None
    cadastral_area_code: int | None = None
    parcel_number: int | None = None
    parcel_sub_number: int | None = None
    raw_text: str | None = None
    text_start: int | None = None
    text_end: int | None = None
    confidence: float = 1.0
    created_at: datetime | None = None


@dataclass
class AddressRef:
    """Reference to an address extracted from a document."""

    id: int | None = None
    attachment_id: int = 0
    ref_type_id: int = 0
    address_point_code: int | None = None
    municipality_name: str | None = None
    street_name: str | None = None
    house_number: int | None = None
    orientation_number: int | None = None
    postal_code: int | None = None
    raw_text: str | None = None
    text_start: int | None = None
    text_end: int | None = None
    confidence: float = 1.0
    created_at: datetime | None = None


@dataclass
class StreetRef:
    """Reference to a street extracted from a document."""

    id: int | None = None
    attachment_id: int = 0
    ref_type_id: int = 0
    street_code: int | None = None
    municipality_name: str | None = None
    street_name: str | None = None
    raw_text: str | None = None
    text_start: int | None = None
    text_end: int | None = None
    confidence: float = 1.0
    created_at: datetime | None = None


@dataclass
class LvRef:
    """Reference to an ownership sheet (LV) extracted from a document."""

    id: int | None = None
    attachment_id: int = 0
    ref_type_id: int = 0
    cadastral_area_code: int | None = None
    lv_number: int = 0
    raw_text: str | None = None
    text_start: int | None = None
    text_end: int | None = None
    confidence: float = 1.0
    created_at: datetime | None = None
