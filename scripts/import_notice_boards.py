#!/usr/bin/env python3
"""Import notice boards from JSON file to PostgreSQL database.

This script reads notice board data from a JSON file (produced by fetch_notice_boards.py)
and imports it into the notice_boards table using upsert (ON CONFLICT) logic.

Usage:
    # Import from JSON
    uv run python scripts/import_notice_boards.py data/notice_boards.json

    # Show statistics
    uv run python scripts/import_notice_boards.py --stats
"""

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import psycopg2
from psycopg2.extras import execute_values

if TYPE_CHECKING:
    import psycopg2.extensions

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from notice_boards.config import get_db_connection
from notice_boards.models import NoticeBoard

logger = logging.getLogger(__name__)


def json_to_notice_board(data: dict[str, Any]) -> NoticeBoard:
    """Convert JSON dict to NoticeBoard dataclass."""
    address = data.get("address", {}) or {}
    coordinates = data.get("coordinates")

    return NoticeBoard(
        municipality_code=int(data["municipality_code"]) if data.get("municipality_code") else None,
        name=data.get("name", ""),
        abbreviation=data.get("abbreviation"),
        ico=data.get("ico"),
        source_url=data.get("url"),
        edesky_url=data.get("edesky_url"),
        ofn_json_url=data.get("ofn_json_url"),
        latitude=coordinates[0] if coordinates else None,
        longitude=coordinates[1] if coordinates else None,
        address_street=address.get("street_name"),
        address_city=address.get("city"),
        address_district=address.get("district"),
        address_postal_code=address.get("postal_code"),
        address_region=address.get("region"),
        address_point_id=int(address["address_point_id"])
        if address.get("address_point_id")
        else None,
        data_box_id=data.get("data_box_id"),
        emails=data.get("email") or [],
        legal_form_code=data.get("legal_form_code"),
        legal_form_label=data.get("legal_form_label"),
        board_type=data.get("type_"),
        nutslau=data.get("nutslau"),
        coat_of_arms_url=data.get("coat_of_arms_url"),
    )


def upsert_notice_boards(conn: "psycopg2.extensions.connection", boards: list[NoticeBoard]) -> int:
    """Upsert notice boards to database.

    Uses municipality_code OR ico as unique key for conflict resolution.

    Returns number of rows affected.
    """
    if not boards:
        return 0

    # Prepare data for bulk insert
    rows = []
    for board in boards:
        rows.append(
            (
                board.municipality_code,
                board.name,
                board.abbreviation,
                board.ico,
                board.source_url,
                board.edesky_url,
                board.ofn_json_url,
                board.latitude,
                board.longitude,
                board.address_street,
                board.address_city,
                board.address_district,
                board.address_postal_code,
                board.address_region,
                board.address_point_id,
                board.data_box_id,
                board.emails,
                board.legal_form_code,
                board.legal_form_label,
                board.board_type,
                board.nutslau,
                board.coat_of_arms_url,
            )
        )

    # Use ON CONFLICT to upsert
    # First, try to match by municipality_code if available, otherwise by ico
    with conn.cursor() as cur:
        # Insert with ON CONFLICT DO UPDATE
        insert_sql = """
            INSERT INTO notice_boards (
                municipality_code, name, abbreviation, ico,
                source_url, edesky_url, ofn_json_url,
                latitude, longitude,
                address_street, address_city, address_district,
                address_postal_code, address_region, address_point_id,
                data_box_id, emails,
                legal_form_code, legal_form_label, board_type,
                nutslau, coat_of_arms_url,
                updated_at
            ) VALUES %s
            ON CONFLICT (ico) WHERE ico IS NOT NULL
            DO UPDATE SET
                municipality_code = EXCLUDED.municipality_code,
                name = EXCLUDED.name,
                abbreviation = EXCLUDED.abbreviation,
                source_url = EXCLUDED.source_url,
                edesky_url = EXCLUDED.edesky_url,
                ofn_json_url = EXCLUDED.ofn_json_url,
                latitude = EXCLUDED.latitude,
                longitude = EXCLUDED.longitude,
                address_street = EXCLUDED.address_street,
                address_city = EXCLUDED.address_city,
                address_district = EXCLUDED.address_district,
                address_postal_code = EXCLUDED.address_postal_code,
                address_region = EXCLUDED.address_region,
                address_point_id = EXCLUDED.address_point_id,
                data_box_id = EXCLUDED.data_box_id,
                emails = EXCLUDED.emails,
                legal_form_code = EXCLUDED.legal_form_code,
                legal_form_label = EXCLUDED.legal_form_label,
                board_type = EXCLUDED.board_type,
                nutslau = EXCLUDED.nutslau,
                coat_of_arms_url = EXCLUDED.coat_of_arms_url,
                updated_at = NOW()
        """

        template = """(
            %s, %s, %s, %s,
            %s, %s, %s,
            %s, %s,
            %s, %s, %s,
            %s, %s, %s,
            %s, %s,
            %s, %s, %s,
            %s, %s,
            NOW()
        )"""

        execute_values(cur, insert_sql, rows, template=template)
        affected: int = cur.rowcount

    conn.commit()
    return affected


def import_from_json(input_path: Path) -> None:
    """Import notice boards from JSON file to database."""
    logger.info(f"Reading notice boards from {input_path}...")

    with open(input_path, encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        raise ValueError(f"Expected JSON array, got {type(data).__name__}")

    logger.info(f"Loaded {len(data)} records from JSON")

    # Convert to NoticeBoard objects
    boards = []
    skipped = 0
    for entry in data:
        try:
            board = json_to_notice_board(entry)
            # Skip entries without any unique identifier
            if not board.ico and not board.municipality_code:
                skipped += 1
                continue
            boards.append(board)
        except Exception as e:
            logger.warning(f"Failed to parse entry: {e}")
            skipped += 1

    logger.info(f"Parsed {len(boards)} valid notice boards (skipped {skipped})")

    # Import to database
    conn = get_db_connection()
    try:
        affected = upsert_notice_boards(conn, boards)
        logger.info(f"Imported {affected} notice boards to database")
    finally:
        conn.close()


def show_stats() -> None:
    """Show statistics about notice boards in database."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            # Total count
            cur.execute("SELECT COUNT(*) FROM notice_boards")
            total = cur.fetchone()[0]

            # By board type
            cur.execute("""
                SELECT board_type, COUNT(*)
                FROM notice_boards
                GROUP BY board_type
                ORDER BY COUNT(*) DESC
            """)
            by_type = cur.fetchall()

            # With URLs
            cur.execute("SELECT COUNT(*) FROM notice_boards WHERE source_url IS NOT NULL")
            with_url = cur.fetchone()[0]

            cur.execute("SELECT COUNT(*) FROM notice_boards WHERE ofn_json_url IS NOT NULL")
            with_ofn = cur.fetchone()[0]

            cur.execute("SELECT COUNT(*) FROM notice_boards WHERE edesky_url IS NOT NULL")
            with_edesky = cur.fetchone()[0]

            # With RUIAN reference
            cur.execute("SELECT COUNT(*) FROM notice_boards WHERE municipality_code IS NOT NULL")
            with_ruian = cur.fetchone()[0]

            print("\nNotice Board Statistics:")
            print(f"  Total:              {total:,}")
            print(f"  With official URL:  {with_url:,}")
            print(f"  With OFN JSON URL:  {with_ofn:,}")
            print(f"  With eDesky URL:    {with_edesky:,}")
            print(f"  With RUIAN ref:     {with_ruian:,}")
            print("\nBy type:")
            for board_type, count in by_type:
                print(f"  {board_type or 'NULL':20} {count:,}")
    finally:
        conn.close()


def setup_logging(verbose: bool = False) -> None:
    """Configure logging."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stderr)],
    )


def main() -> None:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Import notice boards from JSON to PostgreSQL database"
    )
    parser.add_argument(
        "input",
        type=Path,
        nargs="?",
        help="Input JSON file path",
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Show database statistics instead of importing",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    setup_logging(args.verbose)

    if args.stats:
        show_stats()
    elif args.input:
        import_from_json(args.input)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
