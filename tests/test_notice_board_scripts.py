"""Tests for notice board fetch and import scripts."""

import sys
from pathlib import Path

# Add scripts directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from fetch_notice_boards import (
    NoticeBoardData,
    determine_municipality_type,
    extract_json_distribution_url,
    extract_official_url_from_ofn,
    extract_publisher_name_from_ofn,
    normalize_name,
    parse_cesko_digital_entry,
)
from import_notice_boards import json_to_notice_board

from notice_boards.models import NoticeBoard


class TestExtractJsonDistributionUrl:
    """Tests for extract_json_distribution_url function."""

    def test_extracts_json_by_format(self) -> None:
        dataset = {
            "distribution": [
                {"accessURL": "https://example.com/data.xml", "format": "XML"},
                {"accessURL": "https://example.com/data.json", "format": "JSON"},
            ]
        }
        result = extract_json_distribution_url(dataset)
        assert result == "https://example.com/data.json"

    def test_extracts_json_by_extension(self) -> None:
        dataset = {
            "distribution": [
                {"accessURL": "https://example.com/data.json", "format": None},
            ]
        }
        result = extract_json_distribution_url(dataset)
        assert result == "https://example.com/data.json"

    def test_fallback_to_first_distribution(self) -> None:
        dataset = {
            "distribution": [
                {"accessURL": "https://example.com/data.xml", "format": "XML"},
            ]
        }
        result = extract_json_distribution_url(dataset)
        assert result == "https://example.com/data.xml"

    def test_returns_none_for_empty_distributions(self) -> None:
        dataset = {"distribution": []}
        result = extract_json_distribution_url(dataset)
        assert result is None


class TestExtractOfficialUrlFromOfn:
    """Tests for extract_official_url_from_ofn function."""

    def test_extracts_stranka_field(self) -> None:
        ofn_data = {
            "typ": "Úřední deska",
            "stránka": "https://www.praha.eu/uredni-deska",
        }
        result = extract_official_url_from_ofn(ofn_data)
        assert result == "https://www.praha.eu/uredni-deska"

    def test_returns_none_when_missing(self) -> None:
        ofn_data = {"typ": "Úřední deska"}
        result = extract_official_url_from_ofn(ofn_data)
        assert result is None


class TestExtractPublisherNameFromOfn:
    """Tests for extract_publisher_name_from_ofn function."""

    def test_extracts_from_nested_dict(self) -> None:
        ofn_data = {"provozovatel": {"název": {"cs": "Hlavní město Praha"}}}
        result = extract_publisher_name_from_ofn(ofn_data)
        assert result == "Hlavní město Praha"

    def test_extracts_from_string(self) -> None:
        ofn_data = {"provozovatel": {"název": "Hlavní město Praha"}}
        result = extract_publisher_name_from_ofn(ofn_data)
        assert result == "Hlavní město Praha"

    def test_returns_none_when_missing(self) -> None:
        ofn_data = {}
        result = extract_publisher_name_from_ofn(ofn_data)
        assert result is None


class TestDetermineMunicipalityType:
    """Tests for determine_municipality_type function."""

    def test_detects_mestska_cast(self) -> None:
        result = determine_municipality_type("Městská část Praha 1", {})
        assert result == "mestska_cast"

    def test_detects_mestsky_obvod(self) -> None:
        result = determine_municipality_type("Městský obvod Ostrava-Jih", {})
        assert result == "mestska_cast"

    def test_detects_kraj(self) -> None:
        result = determine_municipality_type("Jihomoravský kraj", {})
        assert result == "kraj"

    def test_detects_mesto_by_prefix(self) -> None:
        result = determine_municipality_type("Město Brno", {})
        assert result == "mesto"

    def test_detects_statutarni_mesto(self) -> None:
        result = determine_municipality_type("Statutární město Ostrava", {})
        assert result == "mesto"

    def test_detects_hlavni_mesto_praha(self) -> None:
        result = determine_municipality_type("Hlavní město Praha", {})
        assert result == "mesto"

    def test_detects_mesto_by_population(self) -> None:
        result = determine_municipality_type("Malé Městečko", {"pocetObyvatel": 5000})
        assert result == "mesto"

    def test_default_is_obec(self) -> None:
        result = determine_municipality_type("Dolní Lhota", {})
        assert result == "obec"


class TestNormalizeName:
    """Tests for normalize_name function."""

    def test_removes_obec_prefix(self) -> None:
        result = normalize_name("Obec Dolní Lhota")
        assert result == "dolní lhota"

    def test_removes_mesto_prefix(self) -> None:
        result = normalize_name("Město Brno")
        assert result == "brno"

    def test_removes_mestska_cast_prefix(self) -> None:
        result = normalize_name("Městská část Praha 1")
        assert result == "praha 1"

    def test_lowercase_and_strip(self) -> None:
        result = normalize_name("  PRAHA  ")
        assert result == "praha"


class TestParseCeskoDigitalEntry:
    """Tests for parse_cesko_digital_entry function."""

    def test_parses_complete_entry(self) -> None:
        entry = {
            "hezkyNazev": "Praha",
            "nazev": "HLAVNÍ MĚSTO PRAHA",
            "zkratka": "PRAHA",
            "ICO": "00064581",
            "eDeskyID": "5529",
            "datovaSchrankaID": "48ia97h",
            "RUIAN": "554782",
            "NUTS_LAU": "CZ0100",
            "souradnice": [50.0755, 14.4378],
            "adresaUradu": {
                "ulice": "Mariánské náměstí",
                "cisloDomovni": "2",
                "cisloOrientacni": "2",
                "obec": "Praha 1",
                "obecKod": "500003",
                "PSC": "11001",
                "castObce": "Staré Město",
                "kraj": "Hlavní město Praha",
                "adresniBod": "12345678",
            },
            "mail": ["posta@praha.eu"],
            "pravniForma": {"type": 801, "label": "Obec"},
            "erb": "https://commons.wikimedia.org/wiki/File:Praha_CoA.svg",
        }
        result = parse_cesko_digital_entry(entry)

        assert isinstance(result, NoticeBoardData)
        assert result.name == "Praha"
        assert result.abbreviation == "PRAHA"
        assert result.ico == "00064581"
        assert result.edesky_url == "https://edesky.cz/desky/5529"
        assert result.data_box_id == "48ia97h"
        assert result.municipality_code == "554782"
        assert result.nutslau == "CZ0100"
        assert result.coordinates == (50.0755, 14.4378)
        assert result.address is not None
        assert result.address.street_name == "Mariánské náměstí 2/2"
        assert result.address.city == "Praha 1"
        assert result.address.district == "Staré Město"
        assert result.address.postal_code == "11001"
        assert result.address.address_point_id == "12345678"
        assert result.email == ["posta@praha.eu"]
        assert result.legal_form_code == 801
        assert result.legal_form_label == "Obec"
        assert result.coat_of_arms_url == "https://commons.wikimedia.org/wiki/File:Praha_CoA.svg"
        assert result.type_ == "obec"

    def test_parses_minimal_entry(self) -> None:
        entry = {"nazev": "Dolní Lhota"}
        result = parse_cesko_digital_entry(entry)

        assert result.name == "Dolní Lhota"
        assert result.ico is None
        assert result.edesky_url is None
        assert result.type_ == "obec"

    def test_handles_email_list(self) -> None:
        entry = {
            "nazev": "Test",
            "mail": ["a@test.cz", "b@test.cz"],
        }
        result = parse_cesko_digital_entry(entry)
        assert result.email == ["a@test.cz", "b@test.cz"]

    def test_municipality_code_fallback_to_obecKod(self) -> None:
        entry = {
            "nazev": "Test Obec",
            "adresaUradu": {
                "obecKod": "123456",
            },
        }
        result = parse_cesko_digital_entry(entry)
        assert result.municipality_code == "123456"

    def test_address_without_street(self) -> None:
        entry = {
            "nazev": "Test",
            "adresaUradu": {
                "cisloDomovni": "123",
                "obec": "Test",
                "PSC": "12345",
            },
        }
        result = parse_cesko_digital_entry(entry)
        assert result.address is not None
        assert result.address.street_name == "123"


class TestJsonToNoticeBoard:
    """Tests for json_to_notice_board function."""

    def test_converts_complete_json(self) -> None:
        data = {
            "name": "Praha",
            "abbreviation": "PRAHA",
            "ico": "00064581",
            "url": "https://www.praha.eu/uredni-deska",
            "ofn_json_url": "https://api.example.com/deska.json",
            "edesky_url": "https://edesky.cz/desky/5529",
            "municipality_code": "554782",
            "nutslau": "CZ0100",
            "coordinates": [50.0755, 14.4378],
            "address": {
                "street_name": "Mariánské náměstí 2/2",
                "city": "Praha 1",
                "district": "Staré Město",
                "postal_code": "11001",
                "region": "Hlavní město Praha",
                "address_point_id": "12345678",
            },
            "data_box_id": "48ia97h",
            "email": ["posta@praha.eu"],
            "legal_form_code": 801,
            "legal_form_label": "Obec",
            "coat_of_arms_url": "https://commons.wikimedia.org/wiki/File:Praha_CoA.svg",
            "type_": "mesto",
        }
        result = json_to_notice_board(data)

        assert isinstance(result, NoticeBoard)
        assert result.name == "Praha"
        assert result.abbreviation == "PRAHA"
        assert result.ico == "00064581"
        assert result.source_url == "https://www.praha.eu/uredni-deska"
        assert result.ofn_json_url == "https://api.example.com/deska.json"
        assert result.edesky_url == "https://edesky.cz/desky/5529"
        assert result.municipality_code == 554782
        assert result.nutslau == "CZ0100"
        assert result.latitude == 50.0755
        assert result.longitude == 14.4378
        assert result.address_street == "Mariánské náměstí 2/2"
        assert result.address_city == "Praha 1"
        assert result.address_district == "Staré Město"
        assert result.address_postal_code == "11001"
        assert result.address_region == "Hlavní město Praha"
        assert result.address_point_id == 12345678
        assert result.data_box_id == "48ia97h"
        assert result.emails == ["posta@praha.eu"]
        assert result.legal_form_code == 801
        assert result.legal_form_label == "Obec"
        assert result.coat_of_arms_url == "https://commons.wikimedia.org/wiki/File:Praha_CoA.svg"
        assert result.board_type == "mesto"

    def test_converts_minimal_json(self) -> None:
        data = {"name": "Test Obec"}
        result = json_to_notice_board(data)

        assert result.name == "Test Obec"
        assert result.ico is None
        assert result.municipality_code is None
        assert result.source_url is None

    def test_handles_missing_address(self) -> None:
        data = {"name": "Test", "ico": "12345678"}
        result = json_to_notice_board(data)

        assert result.address_street is None
        assert result.address_city is None

    def test_handles_null_address(self) -> None:
        data = {"name": "Test", "address": None}
        result = json_to_notice_board(data)

        assert result.address_street is None

    def test_handles_empty_email_list(self) -> None:
        data = {"name": "Test", "email": []}
        result = json_to_notice_board(data)

        assert result.emails == []

    def test_handles_missing_coordinates(self) -> None:
        data = {"name": "Test"}
        result = json_to_notice_board(data)

        assert result.latitude is None
        assert result.longitude is None
