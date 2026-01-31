"""Tests for RUIAN validators.

These tests require a database with RUIAN data imported.
Tests are skipped if database is not available.
"""

import os
from collections.abc import Generator
from unittest import mock

import pytest

from notice_boards.validators import (
    AddressValidationResult,
    ParcelValidationResult,
    RuianValidator,
    StreetValidationResult,
)


def get_test_connection():
    """Get database connection for testing."""
    try:
        import psycopg2

        host = os.getenv("RUIAN_DB_HOST", "localhost")
        port = os.getenv("RUIAN_DB_PORT", "5432")
        database = os.getenv("RUIAN_DB_NAME", "ruian")
        user = os.getenv("RUIAN_DB_USER", "ruian")
        password = os.getenv("RUIAN_DB_PASSWORD", "ruian")

        conn = psycopg2.connect(
            host=host,
            port=int(port),
            dbname=database,
            user=user,
            password=password,
        )
        return conn
    except Exception:
        return None


def has_ruian_data(conn) -> bool:
    """Check if RUIAN data is available in the database."""
    if conn is None:
        return False
    try:
        with conn.cursor() as cur:
            # Check if parcely table exists and has data
            cur.execute(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                "WHERE table_name = 'parcely')"
            )
            if not cur.fetchone()[0]:
                return False

            cur.execute("SELECT COUNT(*) FROM parcely LIMIT 1")
            return cur.fetchone()[0] > 0
    except Exception:
        return False


# Skip tests if database not available
db_connection = get_test_connection()
has_data = has_ruian_data(db_connection)

requires_db = pytest.mark.skipif(not has_data, reason="Database with RUIAN data not available")


class TestParcelValidationResult:
    """Tests for ParcelValidationResult dataclass."""

    def test_valid_result(self) -> None:
        """Test creating a valid result."""
        result = ParcelValidationResult(
            is_valid=True,
            parcel_id=12345,
            cadastral_area_code=610372,
            cadastral_area_name="Veveří",
        )
        assert result.is_valid
        assert result.parcel_id == 12345
        assert result.error is None

    def test_invalid_result(self) -> None:
        """Test creating an invalid result."""
        result = ParcelValidationResult(
            is_valid=False,
            error="Parcel not found",
        )
        assert not result.is_valid
        assert result.parcel_id is None
        assert result.error == "Parcel not found"


class TestAddressValidationResult:
    """Tests for AddressValidationResult dataclass."""

    def test_valid_result(self) -> None:
        """Test creating a valid result."""
        result = AddressValidationResult(
            is_valid=True,
            address_point_code=12345678,
            municipality_code=582786,
            municipality_name="Brno",
            street_name="Kounicova",
            house_number=67,
        )
        assert result.is_valid
        assert result.address_point_code == 12345678

    def test_invalid_result(self) -> None:
        """Test creating an invalid result."""
        result = AddressValidationResult(
            is_valid=False,
            error="Address not found",
        )
        assert not result.is_valid
        assert result.error == "Address not found"


class TestStreetValidationResult:
    """Tests for StreetValidationResult dataclass."""

    def test_valid_result(self) -> None:
        """Test creating a valid result."""
        result = StreetValidationResult(
            is_valid=True,
            street_code=12345,
            municipality_code=582786,
            municipality_name="Brno",
            street_name="Kounicova",
        )
        assert result.is_valid
        assert result.street_code == 12345


class TestRuianValidatorMocked:
    """Tests for RuianValidator using mocked database."""

    @pytest.fixture
    def mock_connection(self):
        """Create a mock database connection."""
        conn = mock.MagicMock()
        cursor = mock.MagicMock()
        conn.cursor.return_value.__enter__.return_value = cursor
        return conn, cursor

    def test_validate_parcel_missing_cadastral_area(self, mock_connection: tuple) -> None:
        """Test validation fails without cadastral area."""
        conn, _ = mock_connection
        validator = RuianValidator(conn)

        result = validator.validate_parcel(parcel_number=592)

        assert not result.is_valid
        assert "cadastral_area" in result.error.lower()

    def test_validate_parcel_by_code(self, mock_connection: tuple) -> None:
        """Test parcel validation by cadastral area code."""
        conn, cursor = mock_connection
        cursor.fetchone.return_value = (12345, 610372, "Veveří")
        validator = RuianValidator(conn)

        result = validator.validate_parcel(
            cadastral_area_code=610372,
            parcel_number=592,
            parcel_sub_number=2,
        )

        assert result.is_valid
        assert result.parcel_id == 12345
        assert result.cadastral_area_code == 610372
        assert result.cadastral_area_name == "Veveří"

    def test_validate_parcel_by_name(self, mock_connection: tuple) -> None:
        """Test parcel validation by cadastral area name."""
        conn, cursor = mock_connection
        cursor.fetchone.return_value = (12345, 610372, "Veveří")
        validator = RuianValidator(conn)

        result = validator.validate_parcel(
            cadastral_area_name="Veveří",
            parcel_number=592,
        )

        assert result.is_valid
        assert result.parcel_id == 12345

    def test_validate_parcel_not_found(self, mock_connection: tuple) -> None:
        """Test parcel validation when parcel doesn't exist."""
        conn, cursor = mock_connection
        cursor.fetchone.return_value = None
        validator = RuianValidator(conn)

        result = validator.validate_parcel(
            cadastral_area_code=610372,
            parcel_number=999999,
        )

        assert not result.is_valid
        assert "not found" in result.error.lower()

    def test_validate_parcel_database_error(self, mock_connection: tuple) -> None:
        """Test parcel validation handles database errors."""
        conn, cursor = mock_connection
        cursor.execute.side_effect = Exception("Connection lost")
        validator = RuianValidator(conn)

        result = validator.validate_parcel(
            cadastral_area_code=610372,
            parcel_number=592,
        )

        assert not result.is_valid
        assert "database error" in result.error.lower()

    def test_validate_address_missing_numbers(self, mock_connection: tuple) -> None:
        """Test address validation fails without house/orientation number."""
        conn, _ = mock_connection
        validator = RuianValidator(conn)

        result = validator.validate_address(
            municipality_name="Brno",
            street_name="Kounicova",
        )

        assert not result.is_valid
        assert "house_number" in result.error.lower()

    def test_validate_address_success(self, mock_connection: tuple) -> None:
        """Test successful address validation."""
        conn, cursor = mock_connection
        cursor.fetchone.return_value = (
            12345678,  # kod
            582786,  # municipality_code
            "Brno",  # municipality_name
            "Kounicova",  # street_name
            67,  # house_number
            12,  # orientation_number
        )
        validator = RuianValidator(conn)

        result = validator.validate_address(
            municipality_name="Brno",
            street_name="Kounicova",
            house_number=67,
        )

        assert result.is_valid
        assert result.address_point_code == 12345678
        assert result.municipality_name == "Brno"

    def test_validate_street_success(self, mock_connection: tuple) -> None:
        """Test successful street validation."""
        conn, cursor = mock_connection
        cursor.fetchone.return_value = (12345, 582786, "Brno", "Kounicova")
        validator = RuianValidator(conn)

        result = validator.validate_street(
            municipality_name="Brno",
            street_name="Kounicova",
        )

        assert result.is_valid
        assert result.street_code == 12345
        assert result.street_name == "Kounicova"

    def test_validate_street_not_found(self, mock_connection: tuple) -> None:
        """Test street validation when street doesn't exist."""
        conn, cursor = mock_connection
        cursor.fetchone.return_value = None
        validator = RuianValidator(conn)

        result = validator.validate_street(
            municipality_name="Brno",
            street_name="Neexistující ulice",
        )

        assert not result.is_valid
        assert "not found" in result.error.lower()

    def test_validate_lv_returns_false(self, mock_connection: tuple) -> None:
        """Test LV validation returns False (not implemented)."""
        conn, _ = mock_connection
        validator = RuianValidator(conn)

        result = validator.validate_lv(
            cadastral_area_name="Veveří",
            lv_number=1234,
        )

        assert result is False

    def test_find_cadastral_area_by_code(self, mock_connection: tuple) -> None:
        """Test finding cadastral area by code."""
        conn, cursor = mock_connection
        cursor.fetchone.return_value = (610372, "Veveří")
        validator = RuianValidator(conn)

        code, name = validator.find_cadastral_area(code=610372)

        assert code == 610372
        assert name == "Veveří"

    def test_find_cadastral_area_by_name(self, mock_connection: tuple) -> None:
        """Test finding cadastral area by name."""
        conn, cursor = mock_connection
        cursor.fetchone.return_value = (610372, "Veveří")
        validator = RuianValidator(conn)

        code, name = validator.find_cadastral_area(name="Veveří")

        assert code == 610372
        assert name == "Veveří"

    def test_find_cadastral_area_not_found(self, mock_connection: tuple) -> None:
        """Test finding cadastral area that doesn't exist."""
        conn, cursor = mock_connection
        cursor.fetchone.return_value = None
        validator = RuianValidator(conn)

        code, name = validator.find_cadastral_area(name="Nonexistent")

        assert code is None
        assert name is None

    def test_find_municipality_by_code(self, mock_connection: tuple) -> None:
        """Test finding municipality by code."""
        conn, cursor = mock_connection
        cursor.fetchone.return_value = (582786, "Brno")
        validator = RuianValidator(conn)

        code, name = validator.find_municipality(code=582786)

        assert code == 582786
        assert name == "Brno"


@requires_db
class TestRuianValidatorIntegration:
    """Integration tests for RuianValidator with real database.

    These tests are skipped if the database is not available.
    """

    @pytest.fixture
    def validator(self) -> Generator[RuianValidator, None, None]:
        """Create validator with real database connection."""
        conn = get_test_connection()
        if conn is None:
            pytest.skip("Database connection not available")
        yield RuianValidator(conn)
        conn.close()

    def test_find_any_municipality(self, validator: RuianValidator) -> None:
        """Test that we can find at least one municipality."""
        # Query for any municipality
        with validator.db.cursor() as cur:
            cur.execute("SELECT kod, nazev FROM obce LIMIT 1")
            row = cur.fetchone()

        if row:
            code, name = validator.find_municipality(code=row[0])
            assert code == row[0]
            assert name == row[1]

    def test_find_any_street(self, validator: RuianValidator) -> None:
        """Test that we can find at least one street."""
        # Query for any street with a municipality
        with validator.db.cursor() as cur:
            cur.execute(
                """
                SELECT u.nazev, o.nazev
                FROM ulice u
                JOIN obce o ON o.kod = u.obeckod
                LIMIT 1
                """
            )
            row = cur.fetchone()

        if row:
            result = validator.validate_street(
                municipality_name=row[1],
                street_name=row[0],
            )
            assert result.is_valid

    def test_validate_nonexistent_parcel(self, validator: RuianValidator) -> None:
        """Test validating a parcel that definitely doesn't exist."""
        result = validator.validate_parcel(
            cadastral_area_code=999999,
            parcel_number=999999999,
        )
        assert not result.is_valid
