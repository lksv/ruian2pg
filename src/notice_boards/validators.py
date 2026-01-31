"""RUIAN validators for verifying extracted references.

These validators check if extracted references (parcels, addresses, streets)
actually exist in the RUIAN database. Used by LLM tools to verify extractions.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from psycopg2.extensions import connection as Connection


@dataclass
class ParcelValidationResult:
    """Result of parcel validation."""

    is_valid: bool
    parcel_id: int | None = None
    cadastral_area_code: int | None = None
    cadastral_area_name: str | None = None
    error: str | None = None


@dataclass
class AddressValidationResult:
    """Result of address validation."""

    is_valid: bool
    address_point_code: int | None = None
    municipality_code: int | None = None
    municipality_name: str | None = None
    street_name: str | None = None
    house_number: int | None = None
    orientation_number: int | None = None
    error: str | None = None


@dataclass
class StreetValidationResult:
    """Result of street validation."""

    is_valid: bool
    street_code: int | None = None
    municipality_code: int | None = None
    municipality_name: str | None = None
    street_name: str | None = None
    error: str | None = None


class RuianValidator:
    """Validate extracted references against RUIAN database.

    Used by LLM tools to verify if extraction was correct.

    Example:
        validator = RuianValidator(db_connection)

        # Validate parcel by cadastral area name
        result = validator.validate_parcel(
            cadastral_area_name="Veveří",
            parcel_number=592,
            parcel_sub_number=2
        )
        if result.is_valid:
            print(f"Found parcel with ID: {result.parcel_id}")

        # Validate address
        result = validator.validate_address(
            municipality_name="Brno",
            street_name="Kounicova",
            house_number=67
        )
    """

    def __init__(self, db_connection: "Connection") -> None:
        """Initialize validator with database connection.

        Args:
            db_connection: psycopg2 connection object
        """
        self.db = db_connection

    def validate_parcel(
        self,
        *,
        cadastral_area_code: int | None = None,
        cadastral_area_name: str | None = None,
        parcel_number: int,
        parcel_sub_number: int | None = None,
    ) -> ParcelValidationResult:
        """Check if parcel exists in RUIAN.

        Parcels in RUIAN are identified by:
        - Cadastral area (katastrální území) - by code or name
        - Parcel number (kmenové číslo) - e.g., 592
        - Optionally sub-number (poddělení čísla) - e.g., 2 for "592/2"

        Args:
            cadastral_area_code: Cadastral area code (e.g., 610372)
            cadastral_area_name: Cadastral area name (e.g., "Veveří")
            parcel_number: Main parcel number (kmenové číslo)
            parcel_sub_number: Sub-number if any (poddělení čísla)

        Returns:
            Validation result with parcel_id if found.

        Note:
            Either cadastral_area_code or cadastral_area_name must be provided.
            The RUIAN table 'parcely' uses:
            - kmenovecislo: main parcel number
            - pododdelenicisla: sub-number (NULL if not subdivided)
            - katastralniuzemikod: cadastral area code
        """
        if cadastral_area_code is None and cadastral_area_name is None:
            return ParcelValidationResult(
                is_valid=False,
                error="Either cadastral_area_code or cadastral_area_name must be provided",
            )

        try:
            with self.db.cursor() as cur:
                # Build query based on available parameters
                if cadastral_area_code is not None:
                    # Direct lookup by cadastral area code
                    if parcel_sub_number is not None:
                        cur.execute(
                            """
                            SELECT p.id, p.katastralniuzemikod, ku.nazev
                            FROM parcely p
                            LEFT JOIN katastralniuzemi ku ON ku.kod = p.katastralniuzemikod
                            WHERE p.katastralniuzemikod = %s
                              AND p.kmenovecislo = %s
                              AND p.pododdelenicisla = %s
                            LIMIT 1
                            """,
                            (cadastral_area_code, parcel_number, parcel_sub_number),
                        )
                    else:
                        cur.execute(
                            """
                            SELECT p.id, p.katastralniuzemikod, ku.nazev
                            FROM parcely p
                            LEFT JOIN katastralniuzemi ku ON ku.kod = p.katastralniuzemikod
                            WHERE p.katastralniuzemikod = %s
                              AND p.kmenovecislo = %s
                              AND p.pododdelenicisla IS NULL
                            LIMIT 1
                            """,
                            (cadastral_area_code, parcel_number),
                        )
                else:
                    # Lookup by cadastral area name (case-insensitive)
                    if parcel_sub_number is not None:
                        cur.execute(
                            """
                            SELECT p.id, p.katastralniuzemikod, ku.nazev
                            FROM parcely p
                            JOIN katastralniuzemi ku ON ku.kod = p.katastralniuzemikod
                            WHERE LOWER(ku.nazev) = LOWER(%s)
                              AND p.kmenovecislo = %s
                              AND p.pododdelenicisla = %s
                            LIMIT 1
                            """,
                            (cadastral_area_name, parcel_number, parcel_sub_number),
                        )
                    else:
                        cur.execute(
                            """
                            SELECT p.id, p.katastralniuzemikod, ku.nazev
                            FROM parcely p
                            JOIN katastralniuzemi ku ON ku.kod = p.katastralniuzemikod
                            WHERE LOWER(ku.nazev) = LOWER(%s)
                              AND p.kmenovecislo = %s
                              AND p.pododdelenicisla IS NULL
                            LIMIT 1
                            """,
                            (cadastral_area_name, parcel_number),
                        )

                row = cur.fetchone()
                if row:
                    return ParcelValidationResult(
                        is_valid=True,
                        parcel_id=row[0],
                        cadastral_area_code=row[1],
                        cadastral_area_name=row[2],
                    )
                else:
                    return ParcelValidationResult(
                        is_valid=False,
                        error="Parcel not found in RUIAN",
                    )

        except Exception as e:
            return ParcelValidationResult(
                is_valid=False,
                error=f"Database error: {e}",
            )

    def validate_address(
        self,
        *,
        municipality_code: int | None = None,
        municipality_name: str | None = None,
        street_code: int | None = None,
        street_name: str | None = None,
        house_number: int | None = None,
        orientation_number: int | None = None,
        postal_code: int | None = None,
    ) -> AddressValidationResult:
        """Check if address exists in RUIAN.

        Addresses in RUIAN are identified by various combinations:
        - Municipality (by code or name)
        - Street (by code or name)
        - House number (číslo popisné/evidenční)
        - Orientation number (číslo orientační)
        - Postal code (PSČ)

        Args:
            municipality_code: Municipality code (e.g., 582786 for Brno)
            municipality_name: Municipality name (e.g., "Brno")
            street_code: Street code from RUIAN
            street_name: Street name (e.g., "Kounicova")
            house_number: House number (číslo popisné/evidenční)
            orientation_number: Orientation number (číslo orientační)
            postal_code: Postal code (PSČ)

        Returns:
            Validation result with address_point_code if found.

        Note:
            The RUIAN table 'adresnimista' uses:
            - kod: address point code (primary identifier)
            - cislodomovni: house number
            - cisloorientacni: orientation number
            - psc: postal code
            Related tables: obce (municipalities), ulice (streets)
        """
        # At minimum we need some identifying information
        if house_number is None and orientation_number is None:
            return AddressValidationResult(
                is_valid=False,
                error="At least house_number or orientation_number must be provided",
            )

        try:
            with self.db.cursor() as cur:
                # Build dynamic query based on available parameters
                conditions = []
                params: list[int | str] = []

                # House number
                if house_number is not None:
                    conditions.append("am.cislodomovni = %s")
                    params.append(house_number)

                # Orientation number
                if orientation_number is not None:
                    conditions.append("am.cisloorientacni = %s")
                    params.append(orientation_number)

                # Postal code
                if postal_code is not None:
                    conditions.append("am.psc = %s")
                    params.append(postal_code)

                # Municipality
                if municipality_code is not None:
                    conditions.append("o.kod = %s")
                    params.append(municipality_code)
                elif municipality_name is not None:
                    conditions.append("LOWER(o.nazev) = LOWER(%s)")
                    params.append(municipality_name)

                # Street
                if street_code is not None:
                    conditions.append("u.kod = %s")
                    params.append(street_code)
                elif street_name is not None:
                    conditions.append("LOWER(u.nazev) = LOWER(%s)")
                    params.append(street_name)

                where_clause = " AND ".join(conditions)

                query = f"""
                    SELECT
                        am.kod,
                        o.kod AS municipality_code,
                        o.nazev AS municipality_name,
                        u.nazev AS street_name,
                        am.cislodomovni,
                        am.cisloorientacni
                    FROM adresnimista am
                    LEFT JOIN ulice u ON u.kod = am.ulicekod
                    LEFT JOIN obce o ON o.kod = am.obeckod
                    WHERE {where_clause}
                    LIMIT 1
                """

                cur.execute(query, params)
                row = cur.fetchone()

                if row:
                    return AddressValidationResult(
                        is_valid=True,
                        address_point_code=row[0],
                        municipality_code=row[1],
                        municipality_name=row[2],
                        street_name=row[3],
                        house_number=row[4],
                        orientation_number=row[5],
                    )
                else:
                    return AddressValidationResult(
                        is_valid=False,
                        error="Address not found in RUIAN",
                    )

        except Exception as e:
            return AddressValidationResult(
                is_valid=False,
                error=f"Database error: {e}",
            )

    def validate_street(
        self,
        *,
        municipality_code: int | None = None,
        municipality_name: str | None = None,
        street_name: str,
    ) -> StreetValidationResult:
        """Check if street exists in RUIAN.

        Args:
            municipality_code: Municipality code
            municipality_name: Municipality name
            street_name: Street name (e.g., "Kounicova")

        Returns:
            Validation result with street_code if found.

        Note:
            Either municipality_code or municipality_name should be provided
            for unambiguous matching, as street names can repeat across
            different municipalities.

            The RUIAN table 'ulice' uses:
            - kod: street code (primary identifier)
            - nazev: street name
            - obeckod: municipality code
        """
        try:
            with self.db.cursor() as cur:
                # Build query based on available parameters
                if municipality_code is not None:
                    cur.execute(
                        """
                        SELECT u.kod, o.kod, o.nazev, u.nazev
                        FROM ulice u
                        LEFT JOIN obce o ON o.kod = u.obeckod
                        WHERE LOWER(u.nazev) = LOWER(%s)
                          AND u.obeckod = %s
                        LIMIT 1
                        """,
                        (street_name, municipality_code),
                    )
                elif municipality_name is not None:
                    cur.execute(
                        """
                        SELECT u.kod, o.kod, o.nazev, u.nazev
                        FROM ulice u
                        JOIN obce o ON o.kod = u.obeckod
                        WHERE LOWER(u.nazev) = LOWER(%s)
                          AND LOWER(o.nazev) = LOWER(%s)
                        LIMIT 1
                        """,
                        (street_name, municipality_name),
                    )
                else:
                    # No municipality specified - may return any match
                    cur.execute(
                        """
                        SELECT u.kod, o.kod, o.nazev, u.nazev
                        FROM ulice u
                        LEFT JOIN obce o ON o.kod = u.obeckod
                        WHERE LOWER(u.nazev) = LOWER(%s)
                        LIMIT 1
                        """,
                        (street_name,),
                    )

                row = cur.fetchone()
                if row:
                    return StreetValidationResult(
                        is_valid=True,
                        street_code=row[0],
                        municipality_code=row[1],
                        municipality_name=row[2],
                        street_name=row[3],
                    )
                else:
                    return StreetValidationResult(
                        is_valid=False,
                        error="Street not found in RUIAN",
                    )

        except Exception as e:
            return StreetValidationResult(
                is_valid=False,
                error=f"Database error: {e}",
            )

    def validate_lv(
        self,
        *,
        cadastral_area_code: int | None = None,
        cadastral_area_name: str | None = None,
        lv_number: int,
    ) -> bool:
        """Check if LV (ownership sheet) exists.

        Note:
            LV validation requires external API (ČÚZK),
            as LV data is not part of RUIAN.
            This method is a placeholder for future implementation.

        Args:
            cadastral_area_code: Cadastral area code
            cadastral_area_name: Cadastral area name
            lv_number: Ownership sheet number

        Returns:
            Always False - not implemented yet.
        """
        # LV data is not in RUIAN - would require ČÚZK API
        # Placeholder for future implementation
        _ = cadastral_area_code, cadastral_area_name, lv_number
        return False

    def find_cadastral_area(
        self,
        *,
        name: str | None = None,
        code: int | None = None,
    ) -> tuple[int | None, str | None]:
        """Find cadastral area by name or code.

        Utility method to lookup cadastral area information.

        Args:
            name: Cadastral area name (case-insensitive)
            code: Cadastral area code

        Returns:
            Tuple of (code, name) or (None, None) if not found.
        """
        if name is None and code is None:
            return None, None

        try:
            with self.db.cursor() as cur:
                if code is not None:
                    cur.execute(
                        "SELECT kod, nazev FROM katastralniuzemi WHERE kod = %s",
                        (code,),
                    )
                else:
                    cur.execute(
                        "SELECT kod, nazev FROM katastralniuzemi WHERE LOWER(nazev) = LOWER(%s)",
                        (name,),
                    )

                row = cur.fetchone()
                if row:
                    return row[0], row[1]
                return None, None

        except Exception:
            return None, None

    def find_municipality(
        self,
        *,
        name: str | None = None,
        code: int | None = None,
    ) -> tuple[int | None, str | None]:
        """Find municipality by name or code.

        Utility method to lookup municipality information.

        Args:
            name: Municipality name (case-insensitive)
            code: Municipality code

        Returns:
            Tuple of (code, name) or (None, None) if not found.
        """
        if name is None and code is None:
            return None, None

        try:
            with self.db.cursor() as cur:
                if code is not None:
                    cur.execute(
                        "SELECT kod, nazev FROM obce WHERE kod = %s",
                        (code,),
                    )
                else:
                    cur.execute(
                        "SELECT kod, nazev FROM obce WHERE LOWER(nazev) = LOWER(%s)",
                        (name,),
                    )

                row = cur.fetchone()
                if row:
                    return row[0], row[1]
                return None, None

        except Exception:
            return None, None
