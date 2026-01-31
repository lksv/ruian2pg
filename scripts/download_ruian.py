#!/usr/bin/env python3
"""CLI script for downloading RUIAN VFR files."""

import argparse
import logging
import sys
from pathlib import Path

# Add src to path for development
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ruian_import.config import DownloadConfig
from ruian_import.downloader import RuianDownloader


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
        description="Download RUIAN VFR files from CUZK",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --list                    # List available ST (state) files
  %(prog)s --latest                  # Download only the latest ST file
  %(prog)s --all                     # Download all available ST files
  %(prog)s --force --all             # Re-download all ST files
  %(prog)s --municipalities          # Download all municipality (OB) files
  %(prog)s --municipalities -w 10    # Download OB files with 10 parallel workers
  %(prog)s --list-municipalities     # List available OB files
        """,
    )

    parser.add_argument(
        "--list",
        action="store_true",
        help="List available files without downloading",
    )
    parser.add_argument(
        "--latest",
        action="store_true",
        help="Download only the latest file",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Download all available files",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download even if file exists",
    )
    parser.add_argument(
        "--local",
        action="store_true",
        help="List local ST files in data directory",
    )

    # Municipality (OB) options
    parser.add_argument(
        "--municipalities",
        "--obce",
        action="store_true",
        dest="municipalities",
        help="Download all municipality (OB) files",
    )
    parser.add_argument(
        "--list-municipalities",
        "--list-obce",
        action="store_true",
        dest="list_municipalities",
        help="List available municipality (OB) files",
    )
    parser.add_argument(
        "--local-municipalities",
        "--local-obce",
        action="store_true",
        dest="local_municipalities",
        help="List local municipality (OB) files",
    )
    parser.add_argument(
        "-w",
        "--workers",
        type=int,
        default=5,
        help="Number of parallel download workers (default: 5)",
    )

    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Verbose output",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        help="Data directory for downloads",
    )

    args = parser.parse_args()
    setup_logging(args.verbose)

    # Validate arguments
    actions = [
        args.list,
        args.latest,
        args.all,
        args.local,
        args.municipalities,
        args.list_municipalities,
        args.local_municipalities,
    ]
    if not any(actions):
        parser.print_help()
        print(
            "\nError: Please specify an action: --list, --latest, --all, --local, "
            "--municipalities, --list-municipalities, or --local-municipalities"
        )
        return 1

    # Initialize downloader
    config = DownloadConfig()
    if args.data_dir:
        config.data_dir = args.data_dir
    downloader = RuianDownloader(config)

    try:
        if args.local:
            files = downloader.list_local_files()
            if files:
                print(f"Found {len(files)} local VFR files:")
                for f in files:
                    size_mb = f.stat().st_size / (1024 * 1024)
                    print(f"  {f.name} ({size_mb:.1f} MB)")
            else:
                print("No local VFR files found")
            return 0

        if args.list:
            urls = downloader.fetch_file_list()
            print(f"Found {len(urls)} available VFR files:")
            for url in urls:
                print(f"  {url.split('/')[-1]}")
            return 0

        if args.latest:
            path = downloader.download_latest(force=args.force)
            if path:
                print(f"Downloaded: {path}")
            else:
                print("No new files to download (use --force to re-download)")
            return 0

        if args.all:
            downloaded = downloader.download_all(force=args.force)
            print(f"Downloaded {len(downloaded)} files")
            return 0

        # Municipality (OB) operations
        if args.list_municipalities:
            urls = downloader.fetch_ob_file_list()
            print(f"Found {len(urls)} available OB (municipality) files:")
            for url in urls[:10]:  # Show first 10
                print(f"  {url.split('/')[-1]}")
            if len(urls) > 10:
                print(f"  ... and {len(urls) - 10} more")
            return 0

        if args.local_municipalities:
            files = downloader.list_local_files(file_type="OB")
            if files:
                print(f"Found {len(files)} local OB (municipality) files:")
                total_size_mb = 0.0
                for f in files[:10]:  # Show first 10
                    size_mb = f.stat().st_size / (1024 * 1024)
                    total_size_mb += size_mb
                    print(f"  {f.name} ({size_mb:.1f} MB)")
                if len(files) > 10:
                    for f in files[10:]:
                        total_size_mb += f.stat().st_size / (1024 * 1024)
                    print(f"  ... and {len(files) - 10} more")
                print(f"Total size: {total_size_mb / 1024:.1f} GB")
            else:
                print("No local OB files found")
            return 0

        if args.municipalities:
            print(f"Downloading municipality files with {args.workers} workers...")
            downloaded, failed = downloader.download_all_municipalities(
                force=args.force,
                workers=args.workers,
            )
            print(f"Downloaded {len(downloaded)} files, {len(failed)} failed")
            if failed:
                print("Failed URLs:")
                for url in failed[:5]:
                    print(f"  {url}")
                if len(failed) > 5:
                    print(f"  ... and {len(failed) - 5} more")
            return 0 if not failed else 1

    except Exception as e:
        logging.error("Error: %s", e)
        if args.verbose:
            raise
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
