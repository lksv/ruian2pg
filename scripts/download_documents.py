#!/usr/bin/env python3
"""Download documents from eDesky.cz notice boards.

Downloads document metadata and optionally text/attachments from eDesky.
Supports incremental updates by tracking already downloaded documents.

Usage:
    # Download metadata only from specific notice board
    uv run python scripts/download_documents.py --edesky-id 62

    # Download from municipality by name
    uv run python scripts/download_documents.py --municipality "Brno"

    # Download with text extraction
    uv run python scripts/download_documents.py --edesky-id 62 --download-text

    # Full download with original files
    uv run python scripts/download_documents.py --edesky-id 62 --download-originals

    # Limit number of documents
    uv run python scripts/download_documents.py --edesky-id 62 --limit 20

    # Show statistics
    uv run python scripts/download_documents.py --stats

    # Verbose output
    uv run python scripts/download_documents.py --edesky-id 62 --verbose

Download modes:
    - Metadata (default): Downloads XML metadata, stores URLs in DB
    - Text (--download-text): Also downloads OCR text from eDesky
    - Full (--download-originals): Downloads original attachments too
"""

import argparse
import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from notice_boards.config import get_db_connection, get_project_root
from notice_boards.repository import DocumentRepository, create_document_repository
from notice_boards.scraper_config import EdeskyConfig
from notice_boards.scrapers.edesky import EdeskyScraper

if TYPE_CHECKING:
    from psycopg2.extensions import connection as Connection

logger = logging.getLogger(__name__)


def download_documents(
    scraper: EdeskyScraper,
    repo: DocumentRepository,
    edesky_id: int,
    limit: int | None = None,
    incremental: bool = True,
    download_text: bool = False,
    verbose: bool = False,
) -> tuple[int, int]:
    """Download documents from a notice board.

    Args:
        scraper: eDesky scraper instance.
        repo: Document repository for storage.
        edesky_id: eDesky notice board ID.
        limit: Maximum documents to download (None for all).
        incremental: Skip already downloaded documents.
        download_text: Save extracted text to storage.
        verbose: Enable verbose output.

    Returns:
        Tuple of (downloaded_count, skipped_count).
    """
    # Get or create notice board record
    board = repo.get_notice_board_by_edesky_id(edesky_id)
    if board is None:
        # Create minimal record for this board
        logger.info(f"Creating notice board record for eDesky ID {edesky_id}")
        board_id = repo.upsert_notice_board_from_edesky(
            edesky_id=edesky_id,
            name=f"eDesky #{edesky_id}",
        )
    else:
        if board.id is None:
            logger.error("Board found but has no ID")
            return 0, 0
        board_id = board.id
        logger.info(f"Using existing board: {board.name} (ID: {board_id})")

    if board_id is None or board_id == 0:
        logger.error("Failed to get/create notice board record")
        return 0, 0

    # Get existing document IDs for incremental mode
    existing_ids: set[str] = set()
    if incremental:
        existing_ids = repo.get_existing_external_ids(board_id)
        if existing_ids:
            logger.info(f"Found {len(existing_ids)} existing documents (incremental mode)")

    # Scrape documents
    logger.info(f"Fetching documents from eDesky board {edesky_id}...")
    documents = scraper.scrape_by_id(edesky_id)

    if not documents:
        logger.warning("No documents found")
        return 0, 0

    logger.info(f"Found {len(documents)} documents")

    # Apply limit
    if limit and len(documents) > limit:
        documents = documents[:limit]
        logger.info(f"Limited to {limit} documents")

    downloaded = 0
    skipped = 0

    for doc in documents:
        # Skip if already exists (incremental mode)
        if incremental and doc.external_id in existing_ids:
            skipped += 1
            if verbose:
                logger.debug(f"  Skipped (exists): {doc.title}")
            continue

        try:
            # Save document
            doc_id = repo.upsert_document(
                notice_board_id=board_id,
                doc_data=doc,
                download_text=download_text,
            )

            # Save attachments
            for position, att in enumerate(doc.attachments):
                repo.upsert_attachment(
                    document_id=doc_id,
                    att_data=att,
                    position=position,
                )

            downloaded += 1

            if verbose:
                logger.info(f"  Downloaded: {doc.title} ({len(doc.attachments)} attachments)")

        except Exception as e:
            logger.error(f"Failed to save document {doc.external_id}: {e}")

    # Update last_scraped_at
    repo.mark_scrape_complete(board_id)

    logger.info(f"Downloaded {downloaded} documents, skipped {skipped}")
    return downloaded, skipped


def show_stats(conn: "Connection") -> None:
    """Show statistics about downloaded documents."""
    with conn.cursor() as cur:
        # Total documents
        cur.execute("SELECT COUNT(*) FROM documents")
        total_docs = cur.fetchone()[0]

        # Total attachments
        cur.execute("SELECT COUNT(*) FROM attachments")
        total_atts = cur.fetchone()[0]

        # Documents with text
        cur.execute("SELECT COUNT(*) FROM documents WHERE extracted_text_path IS NOT NULL")
        with_text = cur.fetchone()[0]

        # Attachments with content
        cur.execute(
            "SELECT COUNT(*) FROM attachments WHERE storage_path != '' AND storage_path IS NOT NULL"
        )
        with_content = cur.fetchone()[0]

        # By notice board (top 10)
        cur.execute("""
            SELECT nb.name, nb.edesky_id, COUNT(d.id) as doc_count
            FROM notice_boards nb
            LEFT JOIN documents d ON d.notice_board_id = nb.id
            WHERE nb.edesky_id IS NOT NULL
            GROUP BY nb.id, nb.name, nb.edesky_id
            HAVING COUNT(d.id) > 0
            ORDER BY doc_count DESC
            LIMIT 10
        """)
        by_board = cur.fetchall()

        # Recent documents
        cur.execute("""
            SELECT d.title, nb.name, d.published_at, d.created_at
            FROM documents d
            JOIN notice_boards nb ON nb.id = d.notice_board_id
            ORDER BY d.created_at DESC
            LIMIT 5
        """)
        recent = cur.fetchall()

        print("\nDocument Download Statistics:")
        print(f"  Total documents:     {total_docs:,}")
        print(f"  Total attachments:   {total_atts:,}")
        print(f"  Documents with text: {with_text:,}")
        print(f"  Attachments stored:  {with_content:,}")

        if by_board:
            print("\nTop 10 boards by document count:")
            for name, edesky_id, count in by_board:
                print(f"  {name[:40]:40} (#{edesky_id}) {count:,} docs")

        if recent:
            print("\nMost recent downloads:")
            for title, board_name, published_at, created_at in recent:
                print(f"  [{published_at}] {title[:50]}")
                print(f"       from {board_name}, imported {created_at}")


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
        description="Download documents from eDesky.cz notice boards",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Download metadata only
  %(prog)s --edesky-id 62

  # Download with text extraction
  %(prog)s --edesky-id 62 --download-text

  # Download from municipality by name
  %(prog)s --municipality "Brno" --download-text

  # Full download (text + attachments)
  %(prog)s --edesky-id 62 --download-originals --limit 10
        """,
    )

    # Source selection
    source_group = parser.add_mutually_exclusive_group()
    source_group.add_argument(
        "--edesky-id",
        type=int,
        help="eDesky notice board ID to download from",
    )
    source_group.add_argument(
        "--municipality",
        type=str,
        help="Municipality name to look up in database",
    )
    source_group.add_argument(
        "--stats",
        action="store_true",
        help="Show statistics instead of downloading",
    )

    # Download options
    parser.add_argument(
        "--download-text",
        action="store_true",
        help="Download extracted text from eDesky",
    )
    parser.add_argument(
        "--download-originals",
        action="store_true",
        help="Download original attachment files (implies --download-text)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Maximum number of documents to download",
    )
    parser.add_argument(
        "--no-incremental",
        action="store_true",
        help="Re-download all documents (ignore existing)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    setup_logging(args.verbose)

    # Connect to database
    conn = get_db_connection()
    try:
        if args.stats:
            show_stats(conn)
            return

        # Determine eDesky ID
        edesky_id = args.edesky_id

        if args.municipality:
            # Look up by name
            repo = DocumentRepository(conn)
            board = repo.get_notice_board_by_name(args.municipality)
            if board is None:
                logger.error(f"Municipality '{args.municipality}' not found in database")
                logger.error("Run sync_edesky_boards.py first to sync notice boards")
                sys.exit(1)

            if board.edesky_id is None:
                logger.error(f"Municipality '{args.municipality}' has no eDesky ID")
                sys.exit(1)

            edesky_id = board.edesky_id
            logger.info(f"Found {board.name} with eDesky ID {edesky_id}")

        if edesky_id is None:
            parser.print_help()
            sys.exit(1)

        # Determine download mode
        download_text = args.download_text or args.download_originals
        download_originals = args.download_originals

        # Set up storage paths
        project_root = get_project_root()
        text_path = project_root / "data" / "documents" if download_text else None
        attachments_path = project_root / "data" / "attachments" if download_originals else None

        # Create repository with storage
        repo = create_document_repository(
            conn=conn,
            attachments_path=attachments_path,
            text_path=text_path,
        )

        # Create scraper
        config = EdeskyConfig()
        with EdeskyScraper(
            config=config,
            download_text=download_text,
            download_originals=download_originals,
        ) as scraper:
            downloaded, skipped = download_documents(
                scraper=scraper,
                repo=repo,
                edesky_id=edesky_id,
                limit=args.limit,
                incremental=not args.no_incremental,
                download_text=download_text,
                verbose=args.verbose,
            )

            if downloaded == 0 and skipped == 0:
                sys.exit(1)

    finally:
        conn.close()


if __name__ == "__main__":
    main()
