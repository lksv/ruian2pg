#!/usr/bin/env python3
"""CLI for extracting text from document attachments.

Extracts text from PDF, Office documents, and images using Docling library
with OCR support. Falls back to PyMuPDF/pdfplumber when Docling is unavailable.

Usage:
    # Show statistics
    uv run python scripts/extract_text.py --stats

    # Extract from stored files only
    uv run python scripts/extract_text.py --all --only-downloaded

    # Streaming mode (download and extract without persisting)
    uv run python scripts/extract_text.py --all --stream

    # Stream + persist after extraction
    uv run python scripts/extract_text.py --all --stream --persist

    # Extract for specific board
    uv run python scripts/extract_text.py --board-id 123

    # Single attachment
    uv run python scripts/extract_text.py --attachment-id 456

    # Date filters
    uv run python scripts/extract_text.py --all --published-after 2024-01-01

    # Disable OCR (faster)
    uv run python scripts/extract_text.py --all --no-ocr

    # Force full-page OCR
    uv run python scripts/extract_text.py --all --force-ocr

    # Dry run (list pending without extracting)
    uv run python scripts/extract_text.py --all --dry-run

    # Reset failed to pending
    uv run python scripts/extract_text.py --reset-failed

    # Show stats by MIME type
    uv run python scripts/extract_text.py --stats-by-mime
"""

import argparse
import logging
import sys
from datetime import date, datetime
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from notice_boards.config import get_db_connection
from notice_boards.services.attachment_downloader import AttachmentDownloader
from notice_boards.services.sqlite_text_storage import SqliteTextStorage
from notice_boards.services.text_extractor import (
    ExtractionConfig,
    ExtractionResult,
    TextExtractionService,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def parse_date(date_str: str) -> date:
    """Parse date string in YYYY-MM-DD format."""
    return datetime.strptime(date_str, "%Y-%m-%d").date()


def show_stats(service: TextExtractionService) -> None:
    """Display extraction statistics."""
    stats = service.get_stats()
    print("\nText Extraction Statistics:")
    print(f"  Total attachments:   {stats['total']:,}")
    print(f"  Pending:             {stats['pending']:,}")
    print(f"  Parsing:             {stats['parsing']:,}")
    print(f"  Completed:           {stats['completed']:,}")
    print(f"  Failed:              {stats['failed']:,}")
    print(f"  Skipped:             {stats['skipped']:,}")
    print(f"  Total chars:         {int(stats['total_chars']):,}")
    if "compression_ratio" in stats:
        print(f"  Compression ratio:   {stats['compression_ratio']:.1f}x")
        print(f"  Compressed size:     {int(stats['compressed_bytes']):,} bytes")


def show_stats_by_board(service: TextExtractionService, limit: int = 20) -> None:
    """Display statistics by board."""
    stats = service.get_stats_by_board()
    if not stats:
        print("\nNo boards with pending extractions.")
        return

    print(f"\nPending Extractions by Board (top {limit}):")
    print("-" * 80)
    print(f"{'Board ID':<10} {'Pending':<10} {'Completed':<10} {'Failed':<10} {'Name':<40}")
    print("-" * 80)

    for row in stats[:limit]:
        print(
            f"{row['board_id']:<10} {row['pending']:<10} {row['completed']:<10} "
            f"{row['failed']:<10} {str(row['board_name'] or '')[:40]:<40}"
        )

    if len(stats) > limit:
        print(f"... and {len(stats) - limit} more boards")


def show_stats_by_mime(service: TextExtractionService) -> None:
    """Display statistics by MIME type."""
    stats = service.get_stats_by_mime_type()
    if not stats:
        print("\nNo attachments found.")
        return

    print("\nExtraction Statistics by MIME Type:")
    print("-" * 100)
    print(f"{'MIME Type':<50} {'Total':<10} {'Pending':<10} {'Completed':<10} {'Failed':<10}")
    print("-" * 100)

    for row in stats:
        mime = str(row["mime_type"] or "(none)")
        print(
            f"{mime[:50]:<50} {row['total']!s:<10} {row['pending']!s:<10} "
            f"{row['completed']!s:<10} {row['failed']!s:<10}"
        )


def list_pending(
    service: TextExtractionService, limit: int, only_downloaded: bool, verbose: bool
) -> None:
    """List pending attachments without extracting."""
    pending = service.get_pending_extractions(limit=limit, only_downloaded=only_downloaded)

    if not pending:
        print("\nNo pending attachments found.")
        return

    print(f"\nPending Attachments ({len(pending)} shown):")
    print("-" * 100)

    for p in pending:
        print(f"  ID: {p.id}, Doc: {p.document_id}, File: {p.filename}")
        if verbose:
            print(f"      MIME: {p.mime_type}, Size: {p.file_size_bytes}")
            print(f"      Download: {p.download_status}, Storage: {p.storage_path or '(none)'}")
            print(f"      Board: {p.board_name}")
        print()


def run_extraction(
    service: TextExtractionService,
    args: argparse.Namespace,
) -> int:
    """Run extraction and return exit code."""
    processed = 0
    success = 0
    failed = 0
    skipped = 0

    def on_progress(result: ExtractionResult) -> None:
        nonlocal processed, success, failed, skipped
        processed += 1

        if result.success:
            success += 1
            if args.verbose:
                print(f"  [{processed}] OK: {result.attachment_id} ({result.text_length} chars)")
        elif result.error_type == "skipped":
            skipped += 1
            if args.verbose:
                print(f"  [{processed}] SKIP: {result.attachment_id} - {result.error}")
        else:
            failed += 1
            if args.verbose:
                print(f"  [{processed}] FAIL: {result.attachment_id} - {result.error}")

        # Progress indicator every 100 items
        if processed % 100 == 0 and not args.verbose:
            print(f"  Processed {processed}... (success: {success}, failed: {failed})")

    # Single attachment extraction
    if args.attachment_id:
        print(f"\nExtracting text from attachment {args.attachment_id}...")
        result = service.extract_text(
            attachment_id=args.attachment_id,
            persist_attachment=args.persist,
        )
        on_progress(result)
        print(f"\nResult: {'Success' if result.success else 'Failed'}")
        if result.text_length:
            print(f"Text length: {result.text_length} chars")
        if result.error:
            print(f"Error: {result.error}")
        return 0 if result.success else 1

    # Batch extraction
    print("\nStarting text extraction...")
    print(f"  Only downloaded: {args.only_downloaded}")
    print(f"  Include failed: {args.include_failed}")
    print(f"  Persist: {args.persist}")
    if args.limit:
        print(f"  Limit: {args.limit}")
    if args.published_after:
        print(f"  Published after: {args.published_after}")
    if args.published_before:
        print(f"  Published before: {args.published_before}")
    print()

    stats = service.extract_batch(
        board_id=args.board_id,
        persist_attachments=args.persist,
        only_downloaded=args.only_downloaded,
        include_failed=args.include_failed,
        limit=args.limit,
        on_progress=on_progress,
    )

    print("\nExtraction completed:")
    print(f"  Total available: {stats.total}")
    print(f"  Extracted: {success}")
    print(f"  Failed: {failed}")
    print(f"  Skipped: {skipped}")
    print(f"  Total chars: {stats.total_chars:,}")

    return 0 if failed == 0 else 1


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Extract text from document attachments",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Mode selection
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--all", action="store_true", help="Extract from all pending attachments")
    mode.add_argument("--board-id", type=int, help="Extract from specific board ID")
    mode.add_argument("--attachment-id", type=int, help="Extract from single attachment")
    mode.add_argument("--stats", action="store_true", help="Show extraction statistics")
    mode.add_argument(
        "--stats-by-board", action="store_true", help="Show statistics by notice board"
    )
    mode.add_argument("--stats-by-mime", action="store_true", help="Show statistics by MIME type")
    mode.add_argument("--dry-run", action="store_true", help="List pending without extracting")
    mode.add_argument("--reset-failed", action="store_true", help="Reset failed to pending")
    mode.add_argument(
        "--reset-all", action="store_true", help="Reset failed and skipped to pending"
    )

    # Filtering options
    parser.add_argument(
        "--only-downloaded",
        action="store_true",
        help="Only extract from downloaded files (stored mode)",
    )
    parser.add_argument(
        "--include-failed", action="store_true", help="Include previously failed extractions"
    )
    parser.add_argument("--limit", type=int, help="Maximum number of attachments to process")
    parser.add_argument(
        "--published-after",
        type=parse_date,
        help="Filter documents published on or after date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--published-before",
        type=parse_date,
        help="Filter documents published on or before date (YYYY-MM-DD)",
    )

    # Storage options
    parser.add_argument(
        "--persist",
        action="store_true",
        help="Save downloaded files to storage after streaming",
    )
    parser.add_argument(
        "--storage-path",
        type=Path,
        default=Path("data/attachments"),
        help="Path for attachment storage (default: data/attachments)",
    )
    parser.add_argument(
        "--text-storage-path",
        type=Path,
        default=None,
        help="Path for SQLite text storage (e.g., data/texts). "
        "When set, extracted text is compressed and stored in SQLite files "
        "instead of PostgreSQL.",
    )

    # OCR options
    parser.add_argument("--no-ocr", action="store_true", help="Disable OCR (faster)")
    parser.add_argument(
        "--force-ocr", action="store_true", help="Force full-page OCR even for text PDFs"
    )
    parser.add_argument(
        "--ocr-backend",
        choices=["tesserocr", "easyocr", "rapidocr", "ocrmac"],
        default="tesserocr",
        help="OCR backend to use (default: tesserocr)",
    )

    # Output options
    parser.add_argument(
        "--output-format",
        choices=["markdown", "text", "html"],
        default="markdown",
        help="Output format for extracted text (default: markdown)",
    )

    # General options
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")

    args = parser.parse_args()

    # Default to --stats if no action specified
    if not any(
        [
            args.all,
            args.board_id,
            args.attachment_id,
            args.stats,
            args.stats_by_board,
            args.stats_by_mime,
            args.dry_run,
            args.reset_failed,
            args.reset_all,
        ]
    ):
        args.stats = True

    # Set up logging
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Connect to database
    try:
        conn = get_db_connection()
    except Exception as e:
        print(f"Error: Failed to connect to database: {e}", file=sys.stderr)
        return 1

    # Create downloader
    downloader = AttachmentDownloader(conn, args.storage_path)

    # Create extraction config
    config = ExtractionConfig(
        use_ocr=not args.no_ocr,
        ocr_backend=args.ocr_backend,
        force_full_page_ocr=args.force_ocr,
        output_format=args.output_format,
        persist_after_stream=args.persist,
        published_after=args.published_after,
        published_before=args.published_before,
        verbose=args.verbose,
    )

    # Create SQLite text storage if path specified
    sqlite_storage: SqliteTextStorage | None = None
    if args.text_storage_path:
        sqlite_storage = SqliteTextStorage(args.text_storage_path)

    # Create service
    service = TextExtractionService(conn, downloader, config, sqlite_storage=sqlite_storage)

    try:
        # Handle different modes
        if args.stats:
            show_stats(service)
            return 0

        if args.stats_by_board:
            show_stats_by_board(service)
            return 0

        if args.stats_by_mime:
            show_stats_by_mime(service)
            return 0

        if args.dry_run:
            list_pending(service, args.limit or 50, args.only_downloaded, args.verbose)
            return 0

        if args.reset_failed:
            count = service.reset_to_pending(failed_only=True)
            print(f"Reset {count} failed attachments to pending")
            return 0

        if args.reset_all:
            count = service.reset_to_pending(failed_only=False)
            print(f"Reset {count} failed/skipped attachments to pending")
            return 0

        # Run extraction
        if args.all or args.board_id or args.attachment_id:
            return run_extraction(service, args)

        # Should not reach here
        parser.print_help()
        return 1

    finally:
        if sqlite_storage is not None:
            sqlite_storage.close()
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
