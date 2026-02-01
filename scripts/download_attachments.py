#!/usr/bin/env python3
"""Download missing attachment content.

Downloads attachment files for records that have metadata (orig_url)
but no content (empty storage_path).

Usage:
    # Show statistics
    uv run python scripts/download_attachments.py --stats

    # Download all pending attachments
    uv run python scripts/download_attachments.py --all

    # Download for specific board
    uv run python scripts/download_attachments.py --board-id 123

    # Download with limit
    uv run python scripts/download_attachments.py --all --limit 100

    # Dry run (show what would be downloaded)
    uv run python scripts/download_attachments.py --all --dry-run

    # Verbose output
    uv run python scripts/download_attachments.py --all --verbose

    # Filter by publication date
    uv run python scripts/download_attachments.py --all --published-after 2024-01-01

    # Mark old attachments as removed
    uv run python scripts/download_attachments.py --mark-removed --published-before 2020-01-01

    # Reset failed attachments to pending
    uv run python scripts/download_attachments.py --reset-failed
"""

import argparse
import logging
import sys
from datetime import date, datetime
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from notice_boards.config import get_db_connection
from notice_boards.services.attachment_downloader import (
    AttachmentDownloader,
    DownloadConfig,
    DownloadResult,
)


def setup_logging(verbose: bool) -> None:
    """Configure logging."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def print_stats(downloader: AttachmentDownloader) -> None:
    """Print attachment statistics."""
    stats = downloader.get_stats()

    print("\nAttachment Statistics:")
    print(f"  Total attachments:    {stats['total']:,}")
    print(f"  Downloaded:           {stats['downloaded']:,}")
    print(f"  Pending:              {stats['pending']:,}")
    print(f"  Failed:               {stats['failed']:,}")
    print(f"  Removed:              {stats['removed']:,}")
    print(f"  Total size:           {stats['total_bytes'] / (1024 * 1024):.1f} MB")

    if stats["pending"] > 0:
        print("\nBoards with pending attachments:")
        board_stats = downloader.get_stats_by_board()
        for bs in board_stats[:20]:  # Show top 20
            name = str(bs["board_name"] or "Unknown")[:40]
            pending = bs["pending"]
            print(f"  {name:<40} - {pending:>5} pending")
        if len(board_stats) > 20:
            print(f"  ... and {len(board_stats) - 20} more boards")


def print_pending(downloader: AttachmentDownloader, limit: int = 20) -> None:
    """Print pending attachments."""
    pending = downloader.get_pending_attachments(limit=limit)
    if not pending:
        print("\nNo pending attachments found.")
        return

    total = downloader.get_pending_count()
    print(f"\nPending attachments ({min(limit, total)} of {total}):")
    for att in pending:
        board = att.board_name[:30] if att.board_name else "Unknown"
        filename = att.filename[:40] if att.filename else "unknown"
        print(f"  [{att.id:>6}] {board:<30} - {filename}")


def progress_callback(result: DownloadResult, verbose: bool) -> None:
    """Print progress for each download."""
    if result.success:
        size_kb = (result.file_size or 0) / 1024
        if verbose:
            print(f"  Downloaded: {result.attachment_id} ({size_kb:.1f} KB)")
        else:
            print(".", end="", flush=True)
    else:
        if verbose:
            print(f"  Failed: {result.attachment_id} - {result.error}")
        else:
            print("x", end="", flush=True)


def parse_date(value: str) -> date:
    """Parse date string in YYYY-MM-DD format."""
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as err:
        raise argparse.ArgumentTypeError(f"Invalid date format: {value}. Use YYYY-MM-DD.") from err


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Download missing attachment content.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --stats                    Show statistics
  %(prog)s --all                      Download all pending
  %(prog)s --board-id 123             Download for specific board
  %(prog)s --all --limit 100          Download first 100 pending
  %(prog)s --all --dry-run            Preview without downloading
  %(prog)s --all --verbose            Show detailed progress
  %(prog)s --all --published-after 2024-01-01   Filter by date
  %(prog)s --mark-removed --published-before 2020-01-01   Mark old as removed
  %(prog)s --reset-failed             Reset failed to pending
        """,
    )

    # Action arguments
    action_group = parser.add_mutually_exclusive_group(required=True)
    action_group.add_argument(
        "--stats",
        action="store_true",
        help="Show attachment statistics",
    )
    action_group.add_argument(
        "--all",
        action="store_true",
        help="Download all pending attachments",
    )
    action_group.add_argument(
        "--board-id",
        type=int,
        metavar="ID",
        help="Download attachments for specific notice board",
    )
    action_group.add_argument(
        "--document-id",
        type=int,
        metavar="ID",
        help="Download attachments for specific document",
    )
    action_group.add_argument(
        "--list-pending",
        action="store_true",
        help="List pending attachments",
    )
    action_group.add_argument(
        "--mark-removed",
        action="store_true",
        help="Mark attachments as removed (use with --published-before)",
    )
    action_group.add_argument(
        "--reset-failed",
        action="store_true",
        help="Reset failed attachments to pending for retry",
    )

    # Date filter options
    parser.add_argument(
        "--published-after",
        type=parse_date,
        metavar="DATE",
        help="Filter by documents published on or after DATE (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--published-before",
        type=parse_date,
        metavar="DATE",
        help="Filter by documents published on or before DATE (YYYY-MM-DD)",
    )

    # Other options
    parser.add_argument(
        "--limit",
        type=int,
        metavar="N",
        help="Maximum number of attachments to process",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview what would be done without actually doing it",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Verbose output",
    )
    parser.add_argument(
        "--storage-path",
        type=Path,
        default=Path("data/attachments"),
        metavar="PATH",
        help="Path for storing attachments (default: data/attachments)",
    )
    parser.add_argument(
        "--max-size",
        type=int,
        default=50,
        metavar="MB",
        help="Maximum file size in MB (default: 50)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=60,
        metavar="SEC",
        help="Request timeout in seconds (default: 60)",
    )
    parser.add_argument(
        "--skip-ssl-verify",
        action="store_true",
        help="Skip SSL certificate verification",
    )

    args = parser.parse_args()
    setup_logging(args.verbose)

    # Validate mark-removed requires date filter
    if args.mark_removed and not args.published_before:
        parser.error("--mark-removed requires --published-before")

    # Create configuration with date filters
    config = DownloadConfig(
        max_size_bytes=args.max_size * 1024 * 1024,
        request_timeout=args.timeout,
        skip_ssl_verify=args.skip_ssl_verify,
        verbose=args.verbose,
        published_after=args.published_after,
        published_before=args.published_before,
    )

    # Connect to database
    try:
        conn = get_db_connection()
    except Exception as e:
        print(f"Error: Failed to connect to database: {e}", file=sys.stderr)
        sys.exit(1)

    # Create downloader
    downloader = AttachmentDownloader(
        conn=conn,
        storage_path=args.storage_path,
        config=config,
    )

    try:
        if args.stats:
            print_stats(downloader)

        elif args.list_pending:
            print_pending(downloader, limit=args.limit or 20)

        elif args.mark_removed:
            # Mark attachments as removed based on date
            if args.dry_run:
                # Count how many would be affected
                pending = downloader.get_pending_attachments(
                    published_before=args.published_before,
                    limit=args.limit,
                )
                print(
                    f"\nDry run: Would mark {len(pending)} attachments as removed "
                    f"(published before {args.published_before})"
                )
                if args.verbose and pending:
                    for att in pending[:20]:
                        print(f"  [{att.id}] {att.filename}")
                    if len(pending) > 20:
                        print(f"  ... and {len(pending) - 20} more")
            else:
                count = downloader.mark_removed_by_date(args.published_before)
                print(f"\nMarked {count} attachments as removed.")

        elif args.reset_failed:
            # Reset failed attachments to pending
            if args.dry_run:
                status_counts = downloader.get_status_counts()
                failed_count = status_counts.get("failed", 0)
                print(f"\nDry run: Would reset {failed_count} failed attachments to pending.")
            else:
                count = downloader.reset_to_pending(failed_only=True)
                print(f"\nReset {count} attachments to pending.")

        elif args.dry_run:
            # Show what would be downloaded
            board_id = args.board_id
            document_id = args.document_id if hasattr(args, "document_id") else None

            pending_count = downloader.get_pending_count(
                board_id=board_id,
                document_id=document_id,
            )
            limit = args.limit or pending_count

            date_filter_msg = ""
            if args.published_after:
                date_filter_msg += f" (after {args.published_after})"
            if args.published_before:
                date_filter_msg += f" (before {args.published_before})"

            print(
                f"\nDry run: Would download {min(limit, pending_count)} "
                f"of {pending_count} attachments{date_filter_msg}"
            )

            if args.verbose:
                pending = downloader.get_pending_attachments(
                    board_id=board_id,
                    document_id=document_id,
                    limit=min(limit, 50),  # Show max 50 in verbose mode
                )
                for att in pending:
                    url_display = att.orig_url[:60] if att.orig_url else "no-url"
                    print(f"  [{att.id}] {att.filename} from {url_display}...")

        else:
            # Download attachments
            board_id = args.board_id
            document_id = getattr(args, "document_id", None)

            pending_count = downloader.get_pending_count(
                board_id=board_id,
                document_id=document_id,
            )

            if pending_count == 0:
                print("\nNo pending attachments to download.")
                return

            limit = args.limit or pending_count

            date_filter_msg = ""
            if args.published_after:
                date_filter_msg += f" (after {args.published_after})"
            if args.published_before:
                date_filter_msg += f" (before {args.published_before})"

            print(
                f"\nDownloading {min(limit, pending_count)} "
                f"of {pending_count} pending attachments{date_filter_msg}..."
            )

            if not args.verbose:
                print("Progress: ", end="", flush=True)

            with downloader:
                stats = downloader.download_all(
                    board_id=board_id,
                    document_id=document_id,
                    limit=limit,
                    on_progress=lambda r: progress_callback(r, args.verbose),
                )

            if not args.verbose:
                print()  # Newline after progress dots

            print(f"\nCompleted: {stats}")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
