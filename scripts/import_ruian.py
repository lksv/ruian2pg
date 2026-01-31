#!/usr/bin/env python3
"""CLI script for importing RUIAN VFR files to PostGIS."""

import argparse
import logging
import sys
from pathlib import Path

# Add src to path for development
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ruian_import.config import DatabaseConfig
from ruian_import.importer import RuianImporter


def setup_logging(verbose: bool = False) -> None:
    """Configure logging."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Import RUIAN VFR files to PostGIS",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --check                   # Check database connection
  %(prog)s --stats                   # Show table statistics
  %(prog)s --latest                  # Import only the latest ST file
  %(prog)s --all                     # Import all ST files
  %(prog)s --file data/20251231_ST_UKSH.xml.zip  # Import specific file
  %(prog)s --verify                  # Verify import was successful
  %(prog)s --municipalities          # Import all municipality (OB) files
  %(prog)s --municipalities --continue  # Resume interrupted OB import
  %(prog)s --municipalities -w 8     # Parallel import with 8 workers

Environment variables:
  RUIAN_DB_HOST      Database host (default: localhost)
  RUIAN_DB_PORT      Database port (default: 5432)
  RUIAN_DB_NAME      Database name (default: ruian)
  RUIAN_DB_USER      Database user (default: ruian)
  RUIAN_DB_PASSWORD  Database password (default: ruian)
        """,
    )

    parser.add_argument(
        "--check",
        action="store_true",
        help="Check database connection",
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Show table statistics",
    )
    parser.add_argument(
        "--latest",
        action="store_true",
        help="Import only the latest file",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Import all VFR files",
    )
    parser.add_argument(
        "--file",
        type=Path,
        help="Import a specific VFR file",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Verify import was successful",
    )
    parser.add_argument(
        "--sample",
        type=str,
        metavar="TABLE",
        help="Run sample query on specified table",
    )
    parser.add_argument(
        "--append",
        action="store_true",
        help="Append data instead of overwriting",
    )

    # Municipality (OB) options
    parser.add_argument(
        "--municipalities",
        "--obce",
        action="store_true",
        dest="municipalities",
        help="Import all municipality (OB) files",
    )
    parser.add_argument(
        "--continue",
        action="store_true",
        dest="resume",
        help="Resume interrupted import (skip already imported files)",
    )
    parser.add_argument(
        "--workers",
        "-w",
        type=int,
        default=1,
        help="Number of parallel import workers (default: 1)",
    )

    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Verbose output",
    )

    # Database connection options
    parser.add_argument("--host", help="Database host")
    parser.add_argument("--port", type=int, help="Database port")
    parser.add_argument("--dbname", help="Database name")
    parser.add_argument("--user", help="Database user")
    parser.add_argument("--password", help="Database password")

    args = parser.parse_args()
    setup_logging(args.verbose)

    # Build database config
    db_config = DatabaseConfig()
    if args.host:
        db_config.host = args.host
    if args.port:
        db_config.port = args.port
    if args.dbname:
        db_config.database = args.dbname
    if args.user:
        db_config.user = args.user
    if args.password:
        db_config.password = args.password

    # Validate arguments
    actions = [
        args.check,
        args.stats,
        args.latest,
        args.all,
        args.file,
        args.verify,
        args.sample,
        args.municipalities,
    ]
    if not any(actions):
        parser.print_help()
        print("\nError: Please specify an action")
        return 1

    # Initialize importer
    importer = RuianImporter(db_config)
    overwrite = not args.append

    try:
        if args.check:
            if importer.check_database_connection():
                print("Database connection OK")
                importer.ensure_extensions()
                print("PostGIS extensions OK")
                return 0
            else:
                print("Database connection FAILED")
                return 1

        if args.stats:
            stats = importer.get_table_stats()
            if stats:
                print("Table statistics:")
                for table, count in sorted(stats.items()):
                    print(f"  {table}: {count:,} rows")
            else:
                print("No tables found")
            return 0

        if args.verify:
            if importer.verify_import():
                print("Verification PASSED")
                return 0
            else:
                print("Verification FAILED")
                return 1

        if args.sample:
            results = importer.sample_query(args.sample)
            if results:
                print(f"Sample from {args.sample}:")
                for row in results:
                    print(f"  {row}")
            else:
                print(f"No results from {args.sample}")
            return 0

        if args.file:
            if importer.import_file(args.file, overwrite=overwrite):
                print(f"Successfully imported {args.file}")
                return 0
            else:
                print(f"Failed to import {args.file}")
                return 1

        if args.latest:
            if importer.import_latest(overwrite=overwrite):
                print("Successfully imported latest file")
                return 0
            else:
                print("Failed to import latest file")
                return 1

        if args.all:
            success, failed = importer.import_all(overwrite=overwrite)
            print(f"Import complete: {success} success, {failed} failed")
            return 0 if failed == 0 else 1

        if args.municipalities:
            if args.resume:
                print("Resuming municipality import (skipping already imported files)...")
            else:
                print("Importing all municipality (OB) files...")
            if args.workers > 1:
                print(f"Using {args.workers} parallel workers")
            success, skipped, failed = importer.import_all_municipalities(
                resume=args.resume,
                workers=args.workers,
            )
            print(f"Import complete: {success} success, {skipped} skipped, {failed} failed")
            return 0 if failed == 0 else 1

    except Exception as e:
        logging.error("Error: %s", e)
        if args.verbose:
            raise
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
