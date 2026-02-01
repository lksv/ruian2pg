#!/usr/bin/env python3
"""Sync notice boards from eDesky.cz API.

Downloads notice board metadata from eDesky API and updates the database
with edesky_id, category, NUTS3/4 info, and parent hierarchy.

Usage:
    # Sync ALL boards from eDesky (creates new records)
    uv run python scripts/sync_edesky_boards.py --all

    # Match and update existing boards with eDesky data
    uv run python scripts/sync_edesky_boards.py --all --match-existing

    # Clean import: INSERT only after TRUNCATE (no matching, no upsert)
    uv run python scripts/sync_edesky_boards.py --all --create-only

    # Preview matches without updating (dry-run)
    uv run python scripts/sync_edesky_boards.py --all --match-existing --dry-run

    # Sync specific region with subordinated boards
    uv run python scripts/sync_edesky_boards.py --edesky-id 62 --include-subordinated

    # Show statistics
    uv run python scripts/sync_edesky_boards.py --stats

    # Verbose output
    uv run python scripts/sync_edesky_boards.py --all --match-existing --verbose

Environment:
    EDESKY_API_KEY - Required API key from eDesky.cz
"""

import argparse
import logging
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from notice_boards.config import get_db_connection
from notice_boards.repository import DocumentRepository
from notice_boards.scraper_config import EdeskyConfig
from notice_boards.scrapers.edesky import EdeskyApiClient, EdeskyDashboard

if TYPE_CHECKING:
    from psycopg2.extensions import connection as Connection

logger = logging.getLogger(__name__)


@dataclass
class SyncStats:
    """Statistics for sync operation."""

    matched_by_edesky_id: int = 0
    matched_by_edesky_url: int = 0
    matched_by_ico: int = 0
    matched_by_name: int = 0
    created_new: int = 0
    skipped_ambiguous: int = 0
    skipped_duplicate: int = 0
    errors: int = 0
    ambiguous_boards: list[str] = field(default_factory=list)

    @property
    def total_matched(self) -> int:
        """Total boards matched to existing records."""
        return (
            self.matched_by_edesky_id
            + self.matched_by_edesky_url
            + self.matched_by_ico
            + self.matched_by_name
        )

    @property
    def total_processed(self) -> int:
        """Total boards processed."""
        return (
            self.total_matched
            + self.created_new
            + self.skipped_ambiguous
            + self.skipped_duplicate
            + self.errors
        )


def extract_edesky_id_from_url(url: str) -> int | None:
    """Extract eDesky ID from URL."""
    match = re.search(r"/desky/(\d+)", url)
    if match:
        return int(match.group(1))
    return None


def match_and_update_board(
    repo: DocumentRepository,
    dashboard: EdeskyDashboard,
    stats: SyncStats,
    dry_run: bool = False,
    verbose: bool = False,
) -> bool:
    """Try to match eDesky dashboard to existing board and update it.

    Uses tiered matching:
    1. edesky_id (already in DB)
    2. edesky_url (extract ID from URL)
    3. ICO (if exactly one match)
    4. Name + district (fallback)

    Args:
        repo: Document repository.
        dashboard: eDesky dashboard data.
        stats: Stats object to update.
        dry_run: If True, don't actually update.
        verbose: Enable verbose output.

    Returns:
        True if matched and updated, False otherwise.
    """
    edesky_url = f"https://edesky.cz/desky/{dashboard.edesky_id}"

    # 1. Check if already exists by edesky_id
    existing = repo.get_notice_board_by_edesky_id(dashboard.edesky_id)
    if existing:
        stats.matched_by_edesky_id += 1
        if verbose:
            logger.info(f"  Already synced: {dashboard.name} (edesky_id={dashboard.edesky_id})")
        return True

    # 2. Try to match by edesky_url directly (doesn't require ICO)
    # This looks for boards where the URL contains the same edesky_id
    board = repo.get_notice_board_by_edesky_url(edesky_url)
    if board and board.edesky_id is None:
        stats.matched_by_edesky_url += 1
        if not dry_run:
            repo.update_notice_board_edesky_fields(
                board_id=board.id,  # type: ignore
                edesky_id=dashboard.edesky_id,
                edesky_url=edesky_url,
                category=dashboard.category,
                ico=dashboard.ico,
                nuts3_id=dashboard.nuts3_id,
                nuts3_name=dashboard.nuts3_name,
                nuts4_id=dashboard.nuts4_id,
                nuts4_name=dashboard.nuts4_name,
                parent_id=dashboard.parent_id,
                parent_name=dashboard.parent_name,
                latitude=dashboard.latitude,
                longitude=dashboard.longitude,
            )
        if verbose:
            action = "Would update" if dry_run else "Updated"
            logger.info(f"  {action} by URL: {dashboard.name} (edesky_id={dashboard.edesky_id})")
        return True

    # 3. Try to match by ICO (if exactly one match without edesky_id)
    if dashboard.ico:
        boards = repo.get_notice_boards_by_ico(dashboard.ico)
        # Filter to boards without edesky_id (not yet matched)
        unmatched = [b for b in boards if b.edesky_id is None]

        if len(unmatched) == 1:
            board = unmatched[0]
            stats.matched_by_ico += 1
            if not dry_run:
                repo.update_notice_board_edesky_fields(
                    board_id=board.id,  # type: ignore
                    edesky_id=dashboard.edesky_id,
                    edesky_url=edesky_url,
                    category=dashboard.category,
                    ico=dashboard.ico,
                    nuts3_id=dashboard.nuts3_id,
                    nuts3_name=dashboard.nuts3_name,
                    nuts4_id=dashboard.nuts4_id,
                    nuts4_name=dashboard.nuts4_name,
                    parent_id=dashboard.parent_id,
                    parent_name=dashboard.parent_name,
                    latitude=dashboard.latitude,
                    longitude=dashboard.longitude,
                )
            if verbose:
                action = "Would update" if dry_run else "Updated"
                logger.info(
                    f"  {action} by ICO: {dashboard.name} "
                    f"(ICO={dashboard.ico}, edesky_id={dashboard.edesky_id})"
                )
            return True
        elif len(unmatched) > 1:
            # Multiple boards with same ICO - try to disambiguate by name
            name_matches = [b for b in unmatched if b.name.lower() == dashboard.name.lower()]
            if len(name_matches) == 1:
                board = name_matches[0]
                stats.matched_by_ico += 1
                if not dry_run:
                    repo.update_notice_board_edesky_fields(
                        board_id=board.id,  # type: ignore
                        edesky_id=dashboard.edesky_id,
                        edesky_url=edesky_url,
                        category=dashboard.category,
                        ico=dashboard.ico,
                        nuts3_id=dashboard.nuts3_id,
                        nuts3_name=dashboard.nuts3_name,
                        nuts4_id=dashboard.nuts4_id,
                        nuts4_name=dashboard.nuts4_name,
                        parent_id=dashboard.parent_id,
                        parent_name=dashboard.parent_name,
                        latitude=dashboard.latitude,
                        longitude=dashboard.longitude,
                    )
                if verbose:
                    action = "Would update" if dry_run else "Updated"
                    logger.info(
                        f"  {action} by ICO+name: {dashboard.name} "
                        f"(ICO={dashboard.ico}, edesky_id={dashboard.edesky_id})"
                    )
                return True

    # 4. Try to match by name + district (fallback)
    boards = repo.get_notice_boards_by_name_and_district(
        name=dashboard.name,
        district=dashboard.nuts4_name,
    )
    # Filter to boards without edesky_id
    unmatched = [b for b in boards if b.edesky_id is None]

    if len(unmatched) == 1:
        board = unmatched[0]
        stats.matched_by_name += 1
        if not dry_run:
            repo.update_notice_board_edesky_fields(
                board_id=board.id,  # type: ignore
                edesky_id=dashboard.edesky_id,
                edesky_url=edesky_url,
                category=dashboard.category,
                ico=dashboard.ico,
                nuts3_id=dashboard.nuts3_id,
                nuts3_name=dashboard.nuts3_name,
                nuts4_id=dashboard.nuts4_id,
                nuts4_name=dashboard.nuts4_name,
                parent_id=dashboard.parent_id,
                parent_name=dashboard.parent_name,
                latitude=dashboard.latitude,
                longitude=dashboard.longitude,
            )
        if verbose:
            action = "Would update" if dry_run else "Updated"
            logger.info(
                f"  {action} by name: {dashboard.name} "
                f"(district={dashboard.nuts4_name}, edesky_id={dashboard.edesky_id})"
            )
        return True
    elif len(unmatched) > 1:
        stats.skipped_ambiguous += 1
        stats.ambiguous_boards.append(
            f"{dashboard.name} (ICO={dashboard.ico}, district={dashboard.nuts4_name})"
        )
        if verbose:
            logger.warning(
                f"  Ambiguous: {dashboard.name} - {len(unmatched)} matches "
                f"(ICO={dashboard.ico}, district={dashboard.nuts4_name})"
            )
        return False

    return False


def sync_all_dashboards(
    client: EdeskyApiClient,
    repo: DocumentRepository,
    match_existing: bool = False,
    create_only: bool = False,
    dry_run: bool = False,
    verbose: bool = False,
) -> SyncStats:
    """Sync all notice boards from eDesky API.

    Args:
        client: eDesky API client.
        repo: Document repository for database operations.
        match_existing: Match and update existing boards.
        create_only: Only create new records, no matching (for clean import).
        dry_run: Preview without making changes.
        verbose: Enable verbose output.

    Returns:
        SyncStats with operation results.
    """
    import psycopg2

    stats = SyncStats()

    logger.info("Fetching all notice boards from eDesky API...")
    dashboards = client.get_all_dashboards()

    if not dashboards:
        logger.warning("No boards returned from API")
        return stats

    logger.info(f"Found {len(dashboards)} notice boards from eDesky")

    for i, dashboard in enumerate(dashboards, 1):
        if verbose and i % 500 == 0:
            logger.info(f"Processing {i}/{len(dashboards)}...")

        try:
            if create_only:
                # INSERT only mode for clean imports (no matching, no upsert)
                if not dry_run:
                    try:
                        repo.create_notice_board_from_edesky(
                            edesky_id=dashboard.edesky_id,
                            name=dashboard.name,
                            category=dashboard.category,
                            ico=dashboard.ico,
                            nuts3_id=dashboard.nuts3_id,
                            nuts3_name=dashboard.nuts3_name,
                            nuts4_id=dashboard.nuts4_id,
                            nuts4_name=dashboard.nuts4_name,
                            parent_id=dashboard.parent_id,
                            parent_name=dashboard.parent_name,
                            url=dashboard.url,
                            latitude=dashboard.latitude,
                            longitude=dashboard.longitude,
                        )
                        stats.created_new += 1
                        if verbose:
                            logger.info(
                                f"  Created: {dashboard.name} (edesky_id={dashboard.edesky_id})"
                            )
                    except psycopg2.IntegrityError:
                        # Duplicate edesky_id - rollback and skip
                        repo.conn.rollback()
                        stats.skipped_duplicate += 1
                        if verbose:
                            logger.debug(
                                f"  Skipped duplicate: {dashboard.name} "
                                f"(edesky_id={dashboard.edesky_id})"
                            )
                else:
                    stats.created_new += 1
                    if verbose:
                        logger.info(
                            f"  Would create: {dashboard.name} (edesky_id={dashboard.edesky_id})"
                        )
            elif match_existing:
                matched = match_and_update_board(
                    repo=repo,
                    dashboard=dashboard,
                    stats=stats,
                    dry_run=dry_run,
                    verbose=verbose,
                )
                if not matched:
                    # Create new record
                    if not dry_run:
                        repo.upsert_notice_board_from_edesky(
                            edesky_id=dashboard.edesky_id,
                            name=dashboard.name,
                            category=dashboard.category,
                            ico=dashboard.ico,
                            nuts3_id=dashboard.nuts3_id,
                            nuts3_name=dashboard.nuts3_name,
                            nuts4_id=dashboard.nuts4_id,
                            nuts4_name=dashboard.nuts4_name,
                            parent_id=dashboard.parent_id,
                            parent_name=dashboard.parent_name,
                            url=dashboard.url,
                            latitude=dashboard.latitude,
                            longitude=dashboard.longitude,
                        )
                    stats.created_new += 1
                    if verbose:
                        action = "Would create" if dry_run else "Created"
                        logger.info(
                            f"  {action}: {dashboard.name} (edesky_id={dashboard.edesky_id})"
                        )
            else:
                # Just upsert without matching (original behavior)
                if not dry_run:
                    repo.upsert_notice_board_from_edesky(
                        edesky_id=dashboard.edesky_id,
                        name=dashboard.name,
                        category=dashboard.category,
                        ico=dashboard.ico,
                        nuts3_id=dashboard.nuts3_id,
                        nuts3_name=dashboard.nuts3_name,
                        nuts4_id=dashboard.nuts4_id,
                        nuts4_name=dashboard.nuts4_name,
                        parent_id=dashboard.parent_id,
                        parent_name=dashboard.parent_name,
                        url=dashboard.url,
                        latitude=dashboard.latitude,
                        longitude=dashboard.longitude,
                    )
                stats.created_new += 1

        except Exception as e:
            stats.errors += 1
            logger.error(f"Failed to process {dashboard.name}: {e}")

    return stats


def sync_dashboards(
    client: EdeskyApiClient,
    repo: DocumentRepository,
    edesky_id: int | None = None,
    include_subordinated: bool = False,
    verbose: bool = False,
) -> int:
    """Sync notice boards from eDesky API (legacy mode for specific ID).

    Args:
        client: eDesky API client.
        repo: Document repository for database operations.
        edesky_id: Optional specific board ID to sync.
        include_subordinated: Include subordinated boards.
        verbose: Enable verbose output.

    Returns:
        Number of boards synced.
    """
    logger.info("Fetching notice boards from eDesky API...")

    dashboards = client.get_dashboards(
        edesky_id=edesky_id,
        include_subordinated=include_subordinated,
    )

    if not dashboards:
        logger.warning("No boards returned from API")
        return 0

    logger.info(f"Found {len(dashboards)} notice boards")

    synced = 0
    for dashboard in dashboards:
        try:
            repo.upsert_notice_board_from_edesky(
                edesky_id=dashboard.edesky_id,
                name=dashboard.name,
                category=dashboard.category,
                ico=dashboard.ico,
                nuts3_id=dashboard.nuts3_id,
                nuts3_name=dashboard.nuts3_name,
                nuts4_id=dashboard.nuts4_id,
                nuts4_name=dashboard.nuts4_name,
                parent_id=dashboard.parent_id,
                parent_name=dashboard.parent_name,
                url=dashboard.url,
                latitude=dashboard.latitude,
                longitude=dashboard.longitude,
            )

            if verbose:
                logger.info(
                    f"  Synced: {dashboard.name} "
                    f"(edesky_id={dashboard.edesky_id}, "
                    f"nuts4={dashboard.nuts4_name or 'N/A'})"
                )

            synced += 1

        except Exception as e:
            logger.error(f"Failed to sync {dashboard.name}: {e}")

    logger.info(f"Synced {synced} notice boards")
    return synced


def show_stats(conn: "Connection") -> None:
    """Show statistics about synced notice boards."""
    repo = DocumentRepository(conn)
    stats = repo.get_notice_board_stats()

    with conn.cursor() as cur:
        # By category
        cur.execute("""
            SELECT edesky_category, COUNT(*)
            FROM notice_boards
            WHERE edesky_id IS NOT NULL
            GROUP BY edesky_category
            ORDER BY COUNT(*) DESC
        """)
        by_category = cur.fetchall()

        # By region (NUTS3)
        cur.execute("""
            SELECT nuts3_name, COUNT(*)
            FROM notice_boards
            WHERE edesky_id IS NOT NULL AND nuts3_name IS NOT NULL
            GROUP BY nuts3_name
            ORDER BY COUNT(*) DESC
            LIMIT 10
        """)
        by_region = cur.fetchall()

    print("\nNotice Board Statistics:")
    print(f"  Total boards:           {stats['total']:,}")
    print(f"  With eDesky ID:         {stats['with_edesky_id']:,}")
    print(f"  With ICO:               {stats['with_ico']:,}")
    print(f"  With eDesky URL:        {stats['with_edesky_url']:,}")
    print(f"  With NUTS3:             {stats['with_nuts3']:,}")
    print(f"  With NUTS4:             {stats['with_nuts4']:,}")

    missing = stats["total"] - stats["with_edesky_id"]
    if missing > 0:
        print(f"\n  Missing eDesky ID:      {missing:,}")

    if by_category:
        print("\nBy category:")
        for category, count in by_category:
            print(f"  {category or 'NULL':20} {count:,}")

    if by_region:
        print("\nTop 10 regions (NUTS3):")
        for region, count in by_region:
            print(f"  {region or 'NULL':30} {count:,}")


def print_sync_summary(stats: SyncStats, dry_run: bool = False) -> None:
    """Print summary of sync operation."""
    prefix = "[DRY RUN] " if dry_run else ""

    print(f"\n{prefix}Sync Summary:")
    print(f"  Total processed:        {stats.total_processed:,}")
    print(f"  Matched (total):        {stats.total_matched:,}")
    if stats.total_matched > 0:
        print(f"    - by eDesky ID:       {stats.matched_by_edesky_id:,}")
        print(f"    - by eDesky URL:      {stats.matched_by_edesky_url:,}")
        print(f"    - by ICO:             {stats.matched_by_ico:,}")
        print(f"    - by name:            {stats.matched_by_name:,}")
    print(f"  Created new:            {stats.created_new:,}")
    if stats.skipped_ambiguous > 0:
        print(f"  Skipped (ambiguous):    {stats.skipped_ambiguous:,}")
    if stats.skipped_duplicate > 0:
        print(f"  Skipped (duplicate):    {stats.skipped_duplicate:,}")
    if stats.errors > 0:
        print(f"  Errors:                 {stats.errors:,}")

    if stats.ambiguous_boards and len(stats.ambiguous_boards) <= 20:
        print("\nAmbiguous boards (multiple matches):")
        for board in stats.ambiguous_boards[:20]:
            print(f"  - {board}")


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
    parser = argparse.ArgumentParser(description="Sync notice boards from eDesky.cz API")
    parser.add_argument(
        "--all",
        action="store_true",
        help="Sync ALL boards from eDesky API",
    )
    parser.add_argument(
        "--match-existing",
        action="store_true",
        help="Match eDesky boards to existing records by ICO/name before creating new ones",
    )
    parser.add_argument(
        "--create-only",
        action="store_true",
        help="Only create new records without matching (for clean import after TRUNCATE)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview matches without making changes to database",
    )
    parser.add_argument(
        "--edesky-id",
        type=int,
        help="Specific eDesky board ID to sync",
    )
    parser.add_argument(
        "--include-subordinated",
        action="store_true",
        help="Include subordinated (child) boards",
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Show statistics instead of syncing",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    setup_logging(args.verbose)

    # Validate arguments
    if args.match_existing and not args.all:
        logger.error("--match-existing requires --all flag")
        sys.exit(1)

    if args.create_only and not args.all:
        logger.error("--create-only requires --all flag")
        sys.exit(1)

    if args.match_existing and args.create_only:
        logger.error("--match-existing and --create-only are mutually exclusive")
        sys.exit(1)

    if args.dry_run and not args.all:
        logger.error("--dry-run requires --all flag")
        sys.exit(1)

    # Check for API key
    config = EdeskyConfig()
    if not args.stats and not config.api_key:
        logger.error("EDESKY_API_KEY environment variable not set")
        logger.error("Get an API key from https://edesky.cz and set it:")
        logger.error("  export EDESKY_API_KEY=your_api_key")
        sys.exit(1)

    # Connect to database
    conn = get_db_connection()
    try:
        if args.stats:
            show_stats(conn)
        elif args.all:
            repo = DocumentRepository(conn)
            with EdeskyApiClient(config) as client:
                stats = sync_all_dashboards(
                    client=client,
                    repo=repo,
                    match_existing=args.match_existing,
                    create_only=args.create_only,
                    dry_run=args.dry_run,
                    verbose=args.verbose,
                )
                print_sync_summary(stats, dry_run=args.dry_run)

                if stats.errors > 0 and stats.total_processed == stats.errors:
                    sys.exit(1)
        else:
            repo = DocumentRepository(conn)
            with EdeskyApiClient(config) as client:
                synced = sync_dashboards(
                    client=client,
                    repo=repo,
                    edesky_id=args.edesky_id,
                    include_subordinated=args.include_subordinated,
                    verbose=args.verbose,
                )

                if synced == 0:
                    sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
