#!/usr/bin/env python3
"""Generate test data for notice board map rendering validation.

This script creates fake notice board data with real RUIAN references
for testing map tile rendering.

Usage:
    # Generate test data for a cadastral area by code
    uv run python scripts/generate_test_references.py --cadastral-code 610186

    # Generate test data for a cadastral area by name
    uv run python scripts/generate_test_references.py --cadastral-name "Veveří"

    # Generate with custom count
    uv run python scripts/generate_test_references.py --cadastral-code 610186 \
        --parcels 20 --addresses 15 --streets 5

    # Cleanup generated test data
    uv run python scripts/generate_test_references.py --cleanup
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import date, datetime

# Add src to path for imports
from pathlib import Path
from typing import TYPE_CHECKING, Any

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from notice_boards.config import get_db_connection

if TYPE_CHECKING:
    from psycopg2.extensions import connection as Connection


@dataclass
class CadastralAreaInfo:
    """Information about a cadastral area."""

    code: int
    name: str
    municipality_code: int
    municipality_name: str


@dataclass
class ParcelInfo:
    """Information about a parcel."""

    parcel_id: int
    cadastral_area_code: int
    parcel_number: int
    parcel_sub_number: int | None


@dataclass
class AddressInfo:
    """Information about an address point."""

    address_point_code: int
    municipality_name: str
    street_name: str | None
    house_number: int | None
    orientation_number: int | None


@dataclass
class StreetInfo:
    """Information about a street."""

    street_code: int
    municipality_name: str
    street_name: str


def find_cadastral_area(
    conn: Connection,
    code: int | None = None,
    name: str | None = None,
) -> CadastralAreaInfo | None:
    """Find cadastral area by code or name, including municipality info."""
    if code is None and name is None:
        return None

    with conn.cursor() as cur:
        if code is not None:
            cur.execute(
                """
                SELECT ku.kod, ku.nazev, o.kod as obec_kod, o.nazev as obec_nazev
                FROM katastralniuzemi ku
                JOIN obce o ON ku.obeckod = o.kod
                WHERE ku.kod = %s
                LIMIT 1
                """,
                (code,),
            )
        else:
            cur.execute(
                """
                SELECT ku.kod, ku.nazev, o.kod as obec_kod, o.nazev as obec_nazev
                FROM katastralniuzemi ku
                JOIN obce o ON ku.obeckod = o.kod
                WHERE LOWER(ku.nazev) = LOWER(%s)
                LIMIT 1
                """,
                (name,),
            )

        row = cur.fetchone()
        if row:
            return CadastralAreaInfo(
                code=row[0],
                name=row[1],
                municipality_code=row[2],
                municipality_name=row[3],
            )
        return None


def get_random_parcels(
    conn: Connection,
    cadastral_code: int,
    limit: int = 10,
) -> list[ParcelInfo]:
    """Get random parcels from cadastral area."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, katastralniuzemikod, kmenovecislo, pododdelenicisla
            FROM parcely
            WHERE katastralniuzemikod = %s
            ORDER BY RANDOM()
            LIMIT %s
            """,
            (cadastral_code, limit),
        )

        return [
            ParcelInfo(
                parcel_id=row[0],
                cadastral_area_code=row[1],
                parcel_number=row[2],
                parcel_sub_number=row[3],
            )
            for row in cur.fetchall()
        ]


def get_random_addresses(
    conn: Connection,
    municipality_code: int,
    limit: int = 10,
) -> list[AddressInfo]:
    """Get random addresses from municipality.

    Note: adresnimista doesn't have obeckod directly, so we filter
    through ulice (streets) which belong to municipalities.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT am.kod, o.nazev as obec, u.nazev as ulice,
                   am.cislodomovni, am.cisloorientacni
            FROM adresnimista am
            JOIN ulice u ON u.kod = am.ulicekod
            JOIN obce o ON o.kod = u.obeckod
            WHERE u.obeckod = %s
            ORDER BY RANDOM()
            LIMIT %s
            """,
            (municipality_code, limit),
        )

        return [
            AddressInfo(
                address_point_code=row[0],
                municipality_name=row[1],
                street_name=row[2],
                house_number=row[3],
                orientation_number=row[4],
            )
            for row in cur.fetchall()
        ]


def get_random_streets(
    conn: Connection,
    municipality_code: int,
    limit: int = 5,
) -> list[StreetInfo]:
    """Get random streets from municipality."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT u.kod, o.nazev as obec, u.nazev
            FROM ulice u
            JOIN obce o ON o.kod = u.obeckod
            WHERE u.obeckod = %s
            ORDER BY RANDOM()
            LIMIT %s
            """,
            (municipality_code, limit),
        )

        return [
            StreetInfo(
                street_code=row[0],
                municipality_name=row[1],
                street_name=row[2],
            )
            for row in cur.fetchall()
        ]


def create_notice_board(
    conn: Connection,
    cadastral_area: CadastralAreaInfo,
) -> int:
    """Create test notice board, return id."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO notice_boards (
                name, municipality_code, board_type, source_url, is_active
            ) VALUES (
                %s, %s, 'test', 'http://test.example.com', TRUE
            )
            RETURNING id
            """,
            (
                f"Test Notice Board - {cadastral_area.name}",
                cadastral_area.municipality_code,
            ),
        )
        result = cur.fetchone()
        assert result is not None
        board_id: int = result[0]
        return board_id


def create_document(
    conn: Connection,
    board_id: int,
    cadastral_area: CadastralAreaInfo,
) -> int:
    """Create test document, return id."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO documents (
                notice_board_id, title, published_at,
                parse_status, source_document_type
            ) VALUES (
                %s, %s, %s, 'completed', 'test_faker'
            )
            RETURNING id
            """,
            (
                board_id,
                f"Test Document - References in {cadastral_area.name}",
                date.today(),
            ),
        )
        result = cur.fetchone()
        assert result is not None
        doc_id: int = result[0]
        return doc_id


def create_attachment(
    conn: Connection,
    doc_id: int,
    cadastral_code: int,
    json_content: dict[str, Any],
) -> int:
    """Create test attachment with JSON content, return id."""
    today = date.today().isoformat()
    filename = f"test_references_{cadastral_code}.json"
    storage_path = f"test/{today}/{filename}"

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO attachments (
                document_id, filename, mime_type, storage_path,
                parse_status, extracted_text
            ) VALUES (
                %s, %s, 'application/json', %s, 'completed', %s
            )
            RETURNING id
            """,
            (
                doc_id,
                filename,
                storage_path,
                json.dumps(json_content, ensure_ascii=False, indent=2),
            ),
        )
        result = cur.fetchone()
        assert result is not None
        attachment_id: int = result[0]
        return attachment_id


def get_subject_ref_type_id(conn: Connection) -> int:
    """Get the ref_type_id for 'subject' reference type."""
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM ref_types WHERE code = 'subject' LIMIT 1")
        result = cur.fetchone()
        if result:
            ref_type_id: int = result[0]
            return ref_type_id
        # If not found, return 1 (default)
        return 1


def create_parcel_refs(
    conn: Connection,
    attachment_id: int,
    parcels: list[ParcelInfo],
    ref_type_id: int,
    cadastral_area_name: str,
) -> None:
    """Create parcel references."""
    with conn.cursor() as cur:
        for parcel in parcels:
            # Generate raw_text
            if parcel.parcel_sub_number:
                raw_text = (
                    f"parcela č. {parcel.parcel_number}/{parcel.parcel_sub_number} "
                    f"k.ú. {cadastral_area_name}"
                )
            else:
                raw_text = f"parcela č. {parcel.parcel_number} k.ú. {cadastral_area_name}"

            cur.execute(
                """
                INSERT INTO parcel_refs (
                    attachment_id, ref_type_id, parcel_id,
                    cadastral_area_code, parcel_number, parcel_sub_number,
                    raw_text, confidence
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, 1.0)
                ON CONFLICT (attachment_id, parcel_id, ref_type_id) DO NOTHING
                """,
                (
                    attachment_id,
                    ref_type_id,
                    parcel.parcel_id,
                    parcel.cadastral_area_code,
                    parcel.parcel_number,
                    parcel.parcel_sub_number,
                    raw_text,
                ),
            )


def create_address_refs(
    conn: Connection,
    attachment_id: int,
    addresses: list[AddressInfo],
    ref_type_id: int,
) -> None:
    """Create address references."""
    with conn.cursor() as cur:
        for addr in addresses:
            # Generate raw_text
            parts = []
            if addr.street_name:
                parts.append(addr.street_name)
            if addr.house_number:
                parts.append(str(addr.house_number))
            if addr.orientation_number:
                parts.append(f"/{addr.orientation_number}")
            if addr.municipality_name:
                if parts:
                    parts.append(f", {addr.municipality_name}")
                else:
                    parts.append(addr.municipality_name)
            raw_text = "".join(parts) if parts else "address"

            cur.execute(
                """
                INSERT INTO address_refs (
                    attachment_id, ref_type_id, address_point_code,
                    municipality_name, street_name, house_number,
                    orientation_number, raw_text, confidence
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 1.0)
                ON CONFLICT (attachment_id, address_point_code, ref_type_id) DO NOTHING
                """,
                (
                    attachment_id,
                    ref_type_id,
                    addr.address_point_code,
                    addr.municipality_name,
                    addr.street_name,
                    addr.house_number,
                    addr.orientation_number,
                    raw_text,
                ),
            )


def create_street_refs(
    conn: Connection,
    attachment_id: int,
    streets: list[StreetInfo],
    ref_type_id: int,
) -> None:
    """Create street references."""
    with conn.cursor() as cur:
        for street in streets:
            raw_text = f"ulice {street.street_name}"

            cur.execute(
                """
                INSERT INTO street_refs (
                    attachment_id, ref_type_id, street_code,
                    municipality_name, street_name, raw_text, confidence
                ) VALUES (%s, %s, %s, %s, %s, %s, 1.0)
                ON CONFLICT (attachment_id, street_code, ref_type_id) DO NOTHING
                """,
                (
                    attachment_id,
                    ref_type_id,
                    street.street_code,
                    street.municipality_name,
                    street.street_name,
                    raw_text,
                ),
            )


def cleanup_test_data(conn: Connection) -> int:
    """Remove all test data (board_type='test'). Returns count of deleted boards."""
    with conn.cursor() as cur:
        # Delete references first (cascade should handle this, but be explicit)
        cur.execute(
            """
            DELETE FROM parcel_refs WHERE attachment_id IN (
                SELECT a.id FROM attachments a
                JOIN documents d ON d.id = a.document_id
                JOIN notice_boards nb ON nb.id = d.notice_board_id
                WHERE nb.board_type = 'test'
            )
            """
        )

        cur.execute(
            """
            DELETE FROM address_refs WHERE attachment_id IN (
                SELECT a.id FROM attachments a
                JOIN documents d ON d.id = a.document_id
                JOIN notice_boards nb ON nb.id = d.notice_board_id
                WHERE nb.board_type = 'test'
            )
            """
        )

        cur.execute(
            """
            DELETE FROM street_refs WHERE attachment_id IN (
                SELECT a.id FROM attachments a
                JOIN documents d ON d.id = a.document_id
                JOIN notice_boards nb ON nb.id = d.notice_board_id
                WHERE nb.board_type = 'test'
            )
            """
        )

        cur.execute(
            """
            DELETE FROM lv_refs WHERE attachment_id IN (
                SELECT a.id FROM attachments a
                JOIN documents d ON d.id = a.document_id
                JOIN notice_boards nb ON nb.id = d.notice_board_id
                WHERE nb.board_type = 'test'
            )
            """
        )

        # Delete attachments
        cur.execute(
            """
            DELETE FROM attachments WHERE document_id IN (
                SELECT d.id FROM documents d
                JOIN notice_boards nb ON nb.id = d.notice_board_id
                WHERE nb.board_type = 'test'
            )
            """
        )

        # Delete documents
        cur.execute(
            """
            DELETE FROM documents WHERE notice_board_id IN (
                SELECT id FROM notice_boards WHERE board_type = 'test'
            )
            """
        )

        # Delete notice boards
        cur.execute("DELETE FROM notice_boards WHERE board_type = 'test'")
        deleted_count = cur.rowcount

        conn.commit()
        deleted: int = deleted_count
        return deleted


def build_json_summary(
    cadastral_area: CadastralAreaInfo,
    parcels: list[ParcelInfo],
    addresses: list[AddressInfo],
    streets: list[StreetInfo],
) -> dict[str, Any]:
    """Build JSON summary for extracted_text field."""
    return {
        "generator": "generate_test_references.py",
        "generated_at": datetime.now().isoformat(),
        "cadastral_area": {
            "code": cadastral_area.code,
            "name": cadastral_area.name,
        },
        "municipality": {
            "code": cadastral_area.municipality_code,
            "name": cadastral_area.municipality_name,
        },
        "references": {
            "parcels": [
                {
                    "parcel_id": p.parcel_id,
                    "cadastral_area_code": p.cadastral_area_code,
                    "parcel_number": p.parcel_number,
                    "parcel_sub_number": p.parcel_sub_number,
                    "raw_text": (
                        f"parcela č. {p.parcel_number}"
                        + (f"/{p.parcel_sub_number}" if p.parcel_sub_number else "")
                        + f" k.ú. {cadastral_area.name}"
                    ),
                }
                for p in parcels
            ],
            "addresses": [
                {
                    "address_point_code": a.address_point_code,
                    "municipality_name": a.municipality_name,
                    "street_name": a.street_name,
                    "house_number": a.house_number,
                    "orientation_number": a.orientation_number,
                    "raw_text": (
                        (a.street_name or "")
                        + (" " if a.street_name else "")
                        + (str(a.house_number) if a.house_number else "")
                        + (f"/{a.orientation_number}" if a.orientation_number else "")
                        + (f", {a.municipality_name}" if a.municipality_name else "")
                    ).strip(),
                }
                for a in addresses
            ],
            "streets": [
                {
                    "street_code": s.street_code,
                    "municipality_name": s.municipality_name,
                    "street_name": s.street_name,
                    "raw_text": f"ulice {s.street_name}",
                }
                for s in streets
            ],
        },
    }


def main() -> None:
    """Main function."""
    parser = argparse.ArgumentParser(
        description="Generate test data for notice board map rendering validation."
    )
    parser.add_argument(
        "--cadastral-code",
        type=int,
        help="Cadastral area code (e.g., 610186 for Veveří)",
    )
    parser.add_argument(
        "--cadastral-name",
        type=str,
        help='Cadastral area name (e.g., "Veveří")',
    )
    parser.add_argument(
        "--parcels",
        type=int,
        default=10,
        help="Number of parcel references to create (default: 10)",
    )
    parser.add_argument(
        "--addresses",
        type=int,
        default=10,
        help="Number of address references to create (default: 10)",
    )
    parser.add_argument(
        "--streets",
        type=int,
        default=5,
        help="Number of street references to create (default: 5)",
    )
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="Remove all test data (board_type='test')",
    )

    args = parser.parse_args()

    conn = get_db_connection()

    try:
        if args.cleanup:
            deleted = cleanup_test_data(conn)
            print(f"Cleanup complete. Deleted {deleted} test notice board(s).")
            return

        # Validate arguments
        if args.cadastral_code is None and args.cadastral_name is None:
            print(
                "Error: Either --cadastral-code or --cadastral-name must be provided.",
                file=sys.stderr,
            )
            sys.exit(1)

        # 1. Find cadastral area and municipality
        cadastral_area = find_cadastral_area(
            conn,
            code=args.cadastral_code,
            name=args.cadastral_name,
        )

        if cadastral_area is None:
            print(
                f"Error: Cadastral area not found "
                f"(code={args.cadastral_code}, name={args.cadastral_name})",
                file=sys.stderr,
            )
            sys.exit(1)

        print(f"Found cadastral area: {cadastral_area.name} ({cadastral_area.code})")
        print(
            f"Municipality: {cadastral_area.municipality_name} ({cadastral_area.municipality_code})"
        )

        # 2. Query random RUIAN entities
        parcels = get_random_parcels(conn, cadastral_area.code, args.parcels)
        addresses = get_random_addresses(conn, cadastral_area.municipality_code, args.addresses)
        streets = get_random_streets(conn, cadastral_area.municipality_code, args.streets)

        print(f"\nFound {len(parcels)} parcels, {len(addresses)} addresses, {len(streets)} streets")

        if not parcels and not addresses and not streets:
            print("Error: No RUIAN data found for this area.", file=sys.stderr)
            sys.exit(1)

        # 3. Build JSON summary
        json_content = build_json_summary(cadastral_area, parcels, addresses, streets)

        # 4. Create notice_board, document, attachment
        board_id = create_notice_board(conn, cadastral_area)
        print(f"\nCreated notice board (id={board_id})")

        doc_id = create_document(conn, board_id, cadastral_area)
        print(f"Created document (id={doc_id})")

        attachment_id = create_attachment(conn, doc_id, cadastral_area.code, json_content)
        print(f"Created attachment (id={attachment_id})")

        # 5. Create references
        ref_type_id = get_subject_ref_type_id(conn)

        create_parcel_refs(conn, attachment_id, parcels, ref_type_id, cadastral_area.name)
        print(f"Created {len(parcels)} parcel references")

        create_address_refs(conn, attachment_id, addresses, ref_type_id)
        print(f"Created {len(addresses)} address references")

        create_street_refs(conn, attachment_id, streets, ref_type_id)
        print(f"Created {len(streets)} street references")

        conn.commit()

        # 6. Print summary
        print("\n" + "=" * 60)
        print("Test data generated successfully!")
        print("=" * 60)
        print(f"Cadastral area: {cadastral_area.name} ({cadastral_area.code})")
        print(
            f"Municipality: {cadastral_area.municipality_name} ({cadastral_area.municipality_code})"
        )
        print(f"Notice board ID: {board_id}")
        print(f"Document ID: {doc_id}")
        print(f"Attachment ID: {attachment_id}")
        print(f"Parcel refs: {len(parcels)}")
        print(f"Address refs: {len(addresses)}")
        print(f"Street refs: {len(streets)}")
        print("\nTo cleanup: uv run python scripts/generate_test_references.py --cleanup")

    except Exception as e:
        conn.rollback()
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
