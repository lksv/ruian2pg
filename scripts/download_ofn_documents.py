#!/usr/bin/env python3
"""Download documents from OFN (Open Formal Norm) notice board feeds.

OFN is the Czech Open Formal Norm for official notice boards.
This script downloads documents from boards that publish data in OFN JSON-LD format.

Usage:
    # Download from a specific OFN feed URL
    uv run python scripts/download_ofn_documents.py --url "https://edeska.brno.cz/eDeska01/opendata"

    # Download from a board by database ID
    uv run python scripts/download_ofn_documents.py --board-id 45073

    # Download from ALL boards with OFN URL
    uv run python scripts/download_ofn_documents.py --all-ofn

    # Include original attachment files
    uv run python scripts/download_ofn_documents.py --url "..." --download-originals

    # Preview without saving (dry-run)
    uv run python scripts/download_ofn_documents.py --url "..." --dry-run

    # Show statistics
    uv run python scripts/download_ofn_documents.py --stats

    # Verbose output
    uv run python scripts/download_ofn_documents.py --url "..." --verbose

OFN Specification: https://ofn.gov.cz/úřední-desky/2021-07-20/
"""

import argparse
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from notice_boards.config import get_db_connection
from notice_boards.repository import DocumentRepository, create_document_repository
from notice_boards.scraper_config import OfnConfig
from notice_boards.scrapers.ofn import OfnScraper

logger = logging.getLogger(__name__)


@dataclass
class DownloadStats:
    """Statistics for download operation."""

    boards_processed: int = 0
    boards_skipped: int = 0
    boards_failed: int = 0
    documents_found: int = 0
    documents_new: int = 0
    documents_updated: int = 0
    attachments_found: int = 0
    attachments_downloaded: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def total_documents(self) -> int:
        """Total documents processed."""
        return self.documents_new + self.documents_updated


def download_from_url(
    scraper: OfnScraper,
    repo: DocumentRepository,
    ofn_url: str,
    notice_board_id: int | None = None,
    dry_run: bool = False,
    verbose: bool = False,
) -> DownloadStats:
    """Download documents from a single OFN feed URL.

    Args:
        scraper: OFN scraper instance.
        repo: Document repository for database operations.
        ofn_url: OFN JSON-LD feed URL.
        notice_board_id: Database ID of the notice board (required for saving).
        dry_run: Preview without saving.
        verbose: Enable verbose output.

    Returns:
        DownloadStats with operation results.
    """
    stats = DownloadStats()

    logger.info(f"Downloading from OFN feed: {ofn_url}")

    try:
        documents = scraper.scrape_by_url(ofn_url)
        stats.documents_found = len(documents)
        stats.boards_processed = 1

        logger.info(f"Found {len(documents)} documents")

        if not notice_board_id:
            logger.warning("No notice_board_id provided - documents will be listed but not saved")
            for doc in documents:
                att_count = len(doc.attachments)
                stats.attachments_found += att_count
                if verbose:
                    logger.info(
                        f"  [{doc.published_at}] {doc.title[:80]} ({att_count} attachments)"
                    )
            return stats

        # Get existing external IDs for incremental updates
        existing_ids = repo.get_existing_external_ids(notice_board_id)
        logger.debug(f"Found {len(existing_ids)} existing documents")

        for doc in documents:
            att_count = len(doc.attachments)
            stats.attachments_found += att_count

            is_new = doc.external_id not in existing_ids

            if verbose:
                status = "NEW" if is_new else "UPD"
                logger.info(
                    f"  [{status}] [{doc.published_at}] {doc.title[:70]} ({att_count} attachments)"
                )

            if dry_run:
                if is_new:
                    stats.documents_new += 1
                else:
                    stats.documents_updated += 1
                continue

            # Upsert document
            doc_id = repo.upsert_document(notice_board_id, doc)

            if is_new:
                stats.documents_new += 1
            else:
                stats.documents_updated += 1

            # Upsert attachments
            for i, att in enumerate(doc.attachments):
                att_id = repo.upsert_attachment(doc_id, att, position=i)
                if att_id and att.content:
                    stats.attachments_downloaded += 1

        # Mark scrape complete
        if not dry_run:
            repo.mark_scrape_complete(notice_board_id)

    except Exception as e:
        stats.boards_failed = 1
        stats.errors.append(f"{ofn_url}: {e}")
        logger.error(f"Failed to download from {ofn_url}: {e}")

    return stats


def download_all_ofn(
    scraper: OfnScraper,
    repo: DocumentRepository,
    dry_run: bool = False,
    verbose: bool = False,
    limit: int | None = None,
) -> DownloadStats:
    """Download documents from all notice boards with OFN URL.

    Args:
        scraper: OFN scraper instance.
        repo: Document repository for database operations.
        dry_run: Preview without saving.
        verbose: Enable verbose output.
        limit: Maximum number of boards to process (for testing).

    Returns:
        DownloadStats with operation results.
    """
    stats = DownloadStats()

    boards = repo.get_notice_boards_with_ofn()
    if limit:
        boards = boards[:limit]

    logger.info(f"Found {len(boards)} notice boards with OFN URL")

    for i, board in enumerate(boards, 1):
        if not board.ofn_json_url:
            stats.boards_skipped += 1
            continue

        logger.info(f"\n[{i}/{len(boards)}] Processing: {board.name}")

        board_stats = download_from_url(
            scraper=scraper,
            repo=repo,
            ofn_url=board.ofn_json_url,
            notice_board_id=board.id,
            dry_run=dry_run,
            verbose=verbose,
        )

        # Aggregate stats
        stats.boards_processed += board_stats.boards_processed
        stats.boards_failed += board_stats.boards_failed
        stats.documents_found += board_stats.documents_found
        stats.documents_new += board_stats.documents_new
        stats.documents_updated += board_stats.documents_updated
        stats.attachments_found += board_stats.attachments_found
        stats.attachments_downloaded += board_stats.attachments_downloaded
        stats.errors.extend(board_stats.errors)

    return stats


def show_stats(repo: DocumentRepository) -> None:
    """Show statistics about OFN notice boards and documents."""
    boards = repo.get_notice_boards_with_ofn()
    board_stats = repo.get_notice_board_stats()

    total_docs = repo.get_document_count()
    total_attachments = repo.get_attachment_count()

    print("\nOFN Notice Board Statistics:")
    print(f"  Total notice boards:      {board_stats['total']:,}")
    print(f"  Boards with OFN URL:      {len(boards):,}")
    print(f"  Total documents:          {total_docs:,}")
    print(f"  Total attachments:        {total_attachments:,}")

    if boards:
        print("\nSample OFN boards:")
        for board in boards[:10]:
            print(f"  - {board.name}")
            print(f"    URL: {board.ofn_json_url}")


def print_summary(stats: DownloadStats, dry_run: bool = False) -> None:
    """Print summary of download operation."""
    prefix = "[DRY RUN] " if dry_run else ""

    print(f"\n{prefix}Download Summary:")
    print(f"  Boards processed:         {stats.boards_processed:,}")
    if stats.boards_skipped > 0:
        print(f"  Boards skipped:           {stats.boards_skipped:,}")
    if stats.boards_failed > 0:
        print(f"  Boards failed:            {stats.boards_failed:,}")
    print(f"  Documents found:          {stats.documents_found:,}")
    print(f"  Documents new:            {stats.documents_new:,}")
    print(f"  Documents updated:        {stats.documents_updated:,}")
    print(f"  Attachments found:        {stats.attachments_found:,}")
    if stats.attachments_downloaded > 0:
        print(f"  Attachments downloaded:   {stats.attachments_downloaded:,}")

    if stats.errors:
        print(f"\nErrors ({len(stats.errors)}):")
        for error in stats.errors[:10]:
            print(f"  - {error}")
        if len(stats.errors) > 10:
            print(f"  ... and {len(stats.errors) - 10} more")


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
    parser = argparse.ArgumentParser(description="Download documents from OFN notice board feeds")
    parser.add_argument(
        "--url",
        help="OFN JSON-LD feed URL to download from",
    )
    parser.add_argument(
        "--board-id",
        type=int,
        help="Download from notice board by database ID",
    )
    parser.add_argument(
        "--all-ofn",
        action="store_true",
        help="Download from ALL boards with OFN URL",
    )
    parser.add_argument(
        "--download-originals",
        action="store_true",
        help="Download original attachment files (not just metadata)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview without saving to database",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Limit number of boards to process (for testing)",
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Show statistics instead of downloading",
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
    action_count = sum([bool(args.url), bool(args.board_id), args.all_ofn, args.stats])
    if action_count == 0:
        parser.error("One of --url, --board-id, --all-ofn, or --stats is required")
    if action_count > 1 and not (args.stats and action_count == 1):
        parser.error("Only one of --url, --board-id, --all-ofn, or --stats can be specified")

    # Setup
    config = OfnConfig()
    conn = get_db_connection()

    # Setup storage paths
    attachments_path = Path("data/attachments")
    text_path = Path("data/documents")

    try:
        if args.stats:
            repo = DocumentRepository(conn)
            show_stats(repo)
            return

        # Create repository with storage
        repo = create_document_repository(
            conn=conn,
            attachments_path=attachments_path if args.download_originals else None,
            text_path=text_path,
        )

        scraper = OfnScraper(
            config=config,
            download_originals=args.download_originals,
        )

        with scraper:
            if args.url:
                # Direct URL download
                notice_board_id = None
                if args.board_id:
                    notice_board_id = args.board_id
                else:
                    # Try to find board by URL in database
                    boards = repo.get_notice_boards_with_ofn()
                    for board in boards:
                        if board.ofn_json_url == args.url:
                            notice_board_id = board.id
                            logger.info(f"Matched URL to board: {board.name} (id={board.id})")
                            break

                stats = download_from_url(
                    scraper=scraper,
                    repo=repo,
                    ofn_url=args.url,
                    notice_board_id=notice_board_id,
                    dry_run=args.dry_run,
                    verbose=args.verbose,
                )
                print_summary(stats, dry_run=args.dry_run)

            elif args.board_id:
                # Download by board ID
                board_or_none = repo.get_notice_board_by_id(args.board_id)
                if not board_or_none:
                    logger.error(f"Notice board with ID {args.board_id} not found")
                    sys.exit(1)

                board = board_or_none  # Now mypy knows board is not None
                if not board.ofn_json_url:
                    logger.error(f"Notice board {board.name} has no OFN URL")
                    sys.exit(1)

                stats = download_from_url(
                    scraper=scraper,
                    repo=repo,
                    ofn_url=board.ofn_json_url,
                    notice_board_id=board.id,
                    dry_run=args.dry_run,
                    verbose=args.verbose,
                )
                print_summary(stats, dry_run=args.dry_run)

            elif args.all_ofn:
                # Download from all boards with OFN URL
                stats = download_all_ofn(
                    scraper=scraper,
                    repo=repo,
                    dry_run=args.dry_run,
                    verbose=args.verbose,
                    limit=args.limit,
                )
                print_summary(stats, dry_run=args.dry_run)

                if stats.boards_failed > 0 and stats.boards_processed == 0:
                    sys.exit(1)

    finally:
        conn.close()


if __name__ == "__main__":
    main()
