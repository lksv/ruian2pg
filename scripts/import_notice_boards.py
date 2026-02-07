#!/usr/bin/env python3
"""Import notice boards from JSON file to PostgreSQL database.

This script reads notice board data from a JSON file (produced by fetch_notice_boards.py)
and imports it into the notice_boards table using upsert (ON CONFLICT) logic.

Usage:
    # Import from JSON (upsert mode)
    uv run python scripts/import_notice_boards.py data/notice_boards.json

    # Enrich existing boards (match by ICO/name, only update NULL fields)
    uv run python scripts/import_notice_boards.py --enrich-only data/notice_boards.json

    # Show statistics
    uv run python scripts/import_notice_boards.py --stats
"""

import argparse
import json
import logging
import sys
from dataclasses import dataclass
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
from notice_boards.repository import DocumentRepository

logger = logging.getLogger(__name__)


@dataclass
class EnrichStats:
    """Statistics for enrich operation."""

    matched_by_ico: int = 0
    matched_by_name: int = 0
    enriched: int = 0
    skipped_no_match: int = 0
    skipped_no_unique_key: int = 0
    errors: int = 0

    @property
    def total_matched(self) -> int:
        """Total boards matched."""
        return self.matched_by_ico + self.matched_by_name

    @property
    def total_processed(self) -> int:
        """Total boards processed."""
        return self.total_matched + self.skipped_no_match + self.skipped_no_unique_key + self.errors


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

    Uses municipality_code as unique key for conflict resolution.

    Returns number of rows affected.
    """
    if not boards:
        return 0

    # Deduplicate by municipality_code — keep last occurrence per code.
    # City districts share municipality_code with parent city; the parent
    # entry typically appears last in the JSON and is the one we want.
    seen: dict[int, int] = {}
    unique_boards: list[NoticeBoard] = []
    for board in boards:
        code = board.municipality_code
        if code is not None and code in seen:
            # Replace earlier entry with this one
            unique_boards[seen[code]] = board
        else:
            if code is not None:
                seen[code] = len(unique_boards)
            unique_boards.append(board)

    if len(unique_boards) < len(boards):
        logger.info(
            f"Deduplicated {len(boards)} boards to {len(unique_boards)} "
            f"by municipality_code ({len(boards) - len(unique_boards)} duplicates removed)"
        )

    # Prepare data for bulk insert
    rows = []
    for board in unique_boards:
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

    # Use ON CONFLICT to upsert by municipality_code (unique per board)
    with conn.cursor() as cur:
        # Ensure partial unique index exists for ON CONFLICT
        cur.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_notice_boards_municipality_code_unique
            ON notice_boards(municipality_code) WHERE municipality_code IS NOT NULL
        """)

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
            ON CONFLICT (municipality_code) WHERE municipality_code IS NOT NULL
            DO UPDATE SET
                name = EXCLUDED.name,
                abbreviation = EXCLUDED.abbreviation,
                ico = EXCLUDED.ico,
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
            # Skip entries without municipality_code (required for upsert)
            if not board.municipality_code:
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


def enrich_from_json(input_path: Path, verbose: bool = False) -> EnrichStats:
    """Enrich existing notice boards from JSON file.

    Matches existing boards (created from eDesky) by ICO or name+district
    and updates only NULL fields with data from Česko.Digital.

    Args:
        input_path: Path to JSON file with Česko.Digital data.
        verbose: Enable verbose output.

    Returns:
        EnrichStats with operation results.
    """
    stats = EnrichStats()

    logger.info(f"Reading notice boards from {input_path}...")

    with open(input_path, encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        raise ValueError(f"Expected JSON array, got {type(data).__name__}")

    logger.info(f"Loaded {len(data)} records from JSON")

    conn = get_db_connection()
    try:
        repo = DocumentRepository(conn)

        for i, entry in enumerate(data, 1):
            if verbose and i % 500 == 0:
                logger.info(f"Processing {i}/{len(data)}...")

            try:
                board = json_to_notice_board(entry)

                # Skip entries without ICO (needed for matching)
                if not board.ico and not board.name:
                    stats.skipped_no_unique_key += 1
                    continue

                # Try to match existing board
                existing = None
                match_type = None

                # 1. Try matching by ICO first (most reliable)
                if board.ico:
                    boards = repo.get_notice_boards_by_ico(board.ico)
                    if len(boards) == 1:
                        existing = boards[0]
                        match_type = "ico"
                    elif len(boards) > 1:
                        # Multiple boards with same ICO - try to disambiguate by name
                        name_matches = [b for b in boards if b.name.lower() == board.name.lower()]
                        if len(name_matches) == 1:
                            existing = name_matches[0]
                            match_type = "ico"

                # 2. Try matching by name + district if no ICO match
                if not existing and board.name:
                    existing = repo.find_notice_board_by_name_district(
                        name=board.name,
                        district=board.address_district,
                    )
                    if existing:
                        match_type = "name"

                # 3. Fallback: try name-only match (no district)
                #    Only if there's exactly one board with that name
                if not existing and board.name:
                    existing = repo.find_notice_board_by_name_district(
                        name=board.name,
                        district=None,
                    )
                    if existing:
                        match_type = "name"

                if not existing:
                    stats.skipped_no_match += 1
                    if verbose:
                        logger.debug(
                            f"No match for: {board.name} (ICO={board.ico}, "
                            f"district={board.address_district})"
                        )
                    continue

                # Update match stats
                if match_type == "ico":
                    stats.matched_by_ico += 1
                else:
                    stats.matched_by_name += 1

                # Enrich the existing board
                repo.enrich_notice_board(
                    board_id=existing.id,  # type: ignore
                    municipality_code=board.municipality_code,
                    source_url=board.source_url,
                    ofn_json_url=board.ofn_json_url,
                    data_box_id=board.data_box_id,
                    address_street=board.address_street,
                    address_city=board.address_city,
                    address_district=board.address_district,
                    address_postal_code=board.address_postal_code,
                    address_region=board.address_region,
                    address_point_id=board.address_point_id,
                    abbreviation=board.abbreviation,
                    emails=board.emails if board.emails else None,
                    legal_form_code=board.legal_form_code,
                    legal_form_label=board.legal_form_label,
                    board_type=board.board_type,
                    nutslau=board.nutslau,
                    coat_of_arms_url=board.coat_of_arms_url,
                )
                stats.enriched += 1

                if verbose:
                    logger.info(
                        f"Enriched: {board.name} (matched by {match_type}, "
                        f"existing_id={existing.id})"
                    )

            except Exception as e:
                stats.errors += 1
                logger.error(f"Failed to process entry: {e}")

    finally:
        conn.close()

    return stats


def print_enrich_summary(stats: EnrichStats) -> None:
    """Print summary of enrich operation."""
    print("\nEnrich Summary:")
    print(f"  Total processed:        {stats.total_processed:,}")
    print(f"  Matched (total):        {stats.total_matched:,}")
    if stats.total_matched > 0:
        print(f"    - by ICO:             {stats.matched_by_ico:,}")
        print(f"    - by name+district:   {stats.matched_by_name:,}")
    print(f"  Enriched:               {stats.enriched:,}")
    if stats.skipped_no_match > 0:
        print(f"  Skipped (no match):     {stats.skipped_no_match:,}")
    if stats.skipped_no_unique_key > 0:
        print(f"  Skipped (no key):       {stats.skipped_no_unique_key:,}")
    if stats.errors > 0:
        print(f"  Errors:                 {stats.errors:,}")


def show_stats() -> None:
    """Show statistics about notice boards in database."""
    conn = get_db_connection()
    try:
        repo = DocumentRepository(conn)
        db_stats = repo.get_notice_board_stats()

        with conn.cursor() as cur:
            # By board type
            cur.execute("""
                SELECT board_type, COUNT(*)
                FROM notice_boards
                GROUP BY board_type
                ORDER BY COUNT(*) DESC
            """)
            by_type = cur.fetchall()

        print("\nNotice Board Statistics:")
        print(f"  Total:              {db_stats['total']:,}")
        print(f"  With eDesky ID:     {db_stats['with_edesky_id']:,}")
        print(f"  With ICO:           {db_stats['with_ico']:,}")
        print(f"  With official URL:  {db_stats['with_source_url']:,}")
        print(f"  With eDesky URL:    {db_stats['with_edesky_url']:,}")
        print(f"  With RUIAN ref:     {db_stats['with_municipality_code']:,}")
        print(f"  With data box:      {db_stats['with_data_box']:,}")
        print(f"  With NUTS3:         {db_stats['with_nuts3']:,}")
        print(f"  With NUTS4:         {db_stats['with_nuts4']:,}")
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
        "--enrich-only",
        action="store_true",
        help="Only enrich existing boards (match by ICO/name), don't create new ones",
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
        if args.enrich_only:
            stats = enrich_from_json(args.input, verbose=args.verbose)
            print_enrich_summary(stats)
        else:
            import_from_json(args.input)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
