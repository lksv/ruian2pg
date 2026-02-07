#!/usr/bin/env python3
"""Migrate existing extracted texts from PostgreSQL to compressed SQLite storage.

Reads all attachments with extracted_text IS NOT NULL, compresses and saves
each text to SQLite files organized by NUTS3 region and year, then clears
the extracted_text column in PG (keeping text_length for stats).

Usage:
    # Preview without changes (dry-run)
    uv run python scripts/migrate_texts_to_sqlite.py --dry-run

    # Migrate all texts
    uv run python scripts/migrate_texts_to_sqlite.py

    # Migrate with limit
    uv run python scripts/migrate_texts_to_sqlite.py --limit 1000

    # Migrate specific board
    uv run python scripts/migrate_texts_to_sqlite.py --board-id 123

    # Custom storage path
    uv run python scripts/migrate_texts_to_sqlite.py --text-storage-path data/texts

    # Verbose output
    uv run python scripts/migrate_texts_to_sqlite.py -v
"""

import argparse
import logging
import sys
from pathlib import Path
from typing import Any

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from notice_boards.config import get_db_connection
from notice_boards.services.sqlite_text_storage import SqliteTextStorage
from notice_boards.services.text_extractor import PendingExtraction

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

BATCH_SIZE = 1000


def migrate_texts(
    storage: SqliteTextStorage,
    conn: Any,
    board_id: int | None = None,
    limit: int | None = None,
    dry_run: bool = False,
    verbose: bool = False,
) -> dict[str, int]:
    """Migrate extracted texts from PostgreSQL to SQLite storage.

    Args:
        storage: SqliteTextStorage instance.
        conn: Database connection.
        board_id: Optional board ID filter.
        limit: Maximum number of texts to migrate.
        dry_run: If True, don't modify anything.
        verbose: If True, print each migration.

    Returns:
        Dict with migrated, failed, total_chars, total_compressed counts.
    """
    stats = {
        "migrated": 0,
        "failed": 0,
        "total_chars": 0,
        "total_compressed": 0,
        "skipped": 0,
    }

    cur = conn.cursor()
    # Build query
    query = """
        SELECT a.id, a.document_id, d.notice_board_id,
               a.filename, a.mime_type, a.file_size_bytes,
               a.storage_path, a.orig_url, a.download_status, nb.name,
               nb.nuts3_id, d.published_at,
               a.extracted_text
        FROM attachments a
        JOIN documents d ON d.id = a.document_id
        LEFT JOIN notice_boards nb ON nb.id = d.notice_board_id
        WHERE a.extracted_text IS NOT NULL
    """
    params: list[int] = []

    if board_id is not None:
        query += " AND d.notice_board_id = %s"
        params.append(board_id)

    query += " ORDER BY a.id"

    if limit is not None:
        query += " LIMIT %s"
        params.append(limit)

    cur.execute(query, params)

    batch_count = 0
    for row in cur:
        pending = PendingExtraction(
            id=row[0],
            document_id=row[1],
            notice_board_id=row[2],
            filename=row[3] or "unknown",
            mime_type=row[4],
            file_size_bytes=row[5],
            storage_path=row[6],
            orig_url=row[7],
            download_status=row[8] or "pending",
            board_name=row[9],
            nuts3_id=row[10],
            published_at=row[11],
        )
        text = row[12]
        text_length = len(text)

        if dry_run:
            stats["migrated"] += 1
            stats["total_chars"] += text_length
            if verbose:
                print(f"  [DRY-RUN] Would migrate attachment {pending.id}: {text_length} chars")
            continue

        try:
            compressed_size = storage.save(pending, text)
            stats["total_chars"] += text_length
            stats["total_compressed"] += compressed_size

            # Clear extracted_text in PG, keep text_length
            update_cur = conn.cursor()
            update_cur.execute(
                """
                UPDATE attachments
                SET extracted_text = NULL, text_length = %s
                WHERE id = %s
                """,
                (text_length, pending.id),
            )
            update_cur.close()

            stats["migrated"] += 1
            batch_count += 1

            if verbose:
                ratio = text_length / compressed_size if compressed_size > 0 else 0
                print(
                    f"  [{stats['migrated']}] Migrated attachment {pending.id}: "
                    f"{text_length} chars -> {compressed_size} bytes ({ratio:.1f}x)"
                )

            # Commit in batches
            if batch_count >= BATCH_SIZE:
                conn.commit()
                batch_count = 0
                if not verbose:
                    print(f"  Migrated {stats['migrated']}...")

        except Exception as e:
            stats["failed"] += 1
            logger.warning("Failed to migrate attachment %d: %s", pending.id, e)

    # Final commit
    if not dry_run and batch_count > 0:
        conn.commit()
    cur.close()
    return stats


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Migrate extracted texts from PostgreSQL to SQLite storage",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument(
        "--text-storage-path",
        type=Path,
        default=Path("data/texts"),
        help="Path for SQLite text storage (default: data/texts)",
    )
    parser.add_argument("--board-id", type=int, help="Migrate only specific board")
    parser.add_argument("--limit", type=int, help="Maximum number of texts to migrate")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview without making changes",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Connect to database
    try:
        conn = get_db_connection()
    except Exception as e:
        print(f"Error: Failed to connect to database: {e}", file=sys.stderr)
        return 1

    # Count texts to migrate
    cur = conn.cursor()
    count_query = """
        SELECT COUNT(*) FROM attachments
        WHERE extracted_text IS NOT NULL
    """
    count_params: list[int] = []
    if args.board_id:
        count_query = """
            SELECT COUNT(*) FROM attachments a
            JOIN documents d ON d.id = a.document_id
            WHERE a.extracted_text IS NOT NULL AND d.notice_board_id = %s
        """
        count_params = [args.board_id]
    cur.execute(count_query, count_params)
    total = cur.fetchone()[0]
    cur.close()

    print(f"\nTexts to migrate: {total:,}")
    if args.limit:
        print(f"Limit: {args.limit}")
    if args.dry_run:
        print("Mode: DRY-RUN (no changes will be made)")
    print(f"Storage path: {args.text_storage_path}")
    print()

    if total == 0:
        print("Nothing to migrate.")
        return 0

    # Create storage and migrate
    with SqliteTextStorage(args.text_storage_path) as storage:
        stats = migrate_texts(
            storage=storage,
            conn=conn,
            board_id=args.board_id,
            limit=args.limit,
            dry_run=args.dry_run,
            verbose=args.verbose,
        )

    # Print results
    print("\nMigration completed:")
    print(f"  Migrated:       {stats['migrated']:,}")
    print(f"  Failed:         {stats['failed']:,}")
    print(f"  Total chars:    {stats['total_chars']:,}")
    if not args.dry_run and stats["total_compressed"] > 0:
        ratio = stats["total_chars"] / stats["total_compressed"]
        print(f"  Compressed:     {stats['total_compressed']:,} bytes ({ratio:.1f}x ratio)")

    conn.close()
    return 0 if stats["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
