"""Download RUIAN VFR files from CUZK."""

import logging
import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx

from .config import DownloadConfig, get_data_dir

logger = logging.getLogger(__name__)


class RuianDownloader:
    """Downloader for RUIAN VFR files."""

    # Pattern for ST (state) VFR file URLs: YYYYMMDD_ST_UKSH.xml.zip
    FILE_PATTERN = re.compile(r"(\d{8}_ST_UKSH\.xml\.zip)")

    # Pattern for OB (municipality) VFR file URLs: YYYYMMDD_OB_{KOD}_UKSH.xml.zip
    OB_FILE_PATTERN = re.compile(r"(\d{8}_OB_\d+_UKSH\.xml\.zip)")

    def __init__(self, config: DownloadConfig | None = None):
        self.config = config or DownloadConfig()
        self.data_dir = get_data_dir()

    def fetch_file_list(self) -> list[str]:
        """
        Fetch list of available VFR files from CUZK.

        Returns:
            List of file URLs to download.
        """
        logger.info("Fetching file list from %s", self.config.list_url)

        with httpx.Client(timeout=self.config.timeout) as client:
            response = client.get(self.config.list_url)
            response.raise_for_status()

        # Parse the text response - each line contains a file path
        files = []
        for line in response.text.strip().split("\n"):
            line = line.strip()
            if not line:
                continue

            # Extract filename from URL or path
            match = self.FILE_PATTERN.search(line)
            if match:
                filename = match.group(1)
                url = f"{self.config.base_download_url}/{filename}"
                files.append(url)
            elif line.startswith("http"):
                files.append(line)

        logger.info("Found %d VFR files", len(files))
        return files

    def download_file(self, url: str, force: bool = False) -> Path | None:
        """
        Download a single VFR file.

        Args:
            url: URL of the file to download.
            force: If True, re-download even if file exists.

        Returns:
            Path to downloaded file, or None if skipped.
        """
        filename = url.split("/")[-1]
        local_path = self.data_dir / filename

        if local_path.exists() and not force:
            logger.info("Skipping %s (already exists)", filename)
            return None

        logger.info("Downloading %s...", filename)

        with (
            httpx.Client(timeout=self.config.timeout, follow_redirects=True) as client,
            client.stream("GET", url) as response,
        ):
            response.raise_for_status()

            # Download to temporary file first
            temp_path = local_path.with_suffix(".tmp")
            total_size = int(response.headers.get("content-length", 0))
            downloaded = 0

            with open(temp_path, "wb") as f:
                for chunk in response.iter_bytes(chunk_size=self.config.chunk_size):
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_size:
                        progress = (downloaded / total_size) * 100
                        print(f"\r  Progress: {progress:.1f}%", end="", flush=True)

            print()  # New line after progress

            # Move to final location
            temp_path.rename(local_path)

        logger.info("Downloaded %s (%d bytes)", filename, local_path.stat().st_size)
        return local_path

    def download_all(self, force: bool = False) -> list[Path]:
        """
        Download all available VFR files.

        Args:
            force: If True, re-download even if files exist.

        Returns:
            List of paths to downloaded files.
        """
        urls = self.fetch_file_list()
        downloaded = []

        for url in urls:
            try:
                path = self.download_file(url, force=force)
                if path:
                    downloaded.append(path)
            except httpx.HTTPError as e:
                logger.error("Failed to download %s: %s", url, e)

        logger.info("Downloaded %d new files", len(downloaded))
        return downloaded

    def download_latest(self, force: bool = False) -> Path | None:
        """
        Download only the latest (most recent) VFR file.

        Args:
            force: If True, re-download even if file exists.

        Returns:
            Path to downloaded file, or None if skipped/failed.
        """
        urls = self.fetch_file_list()
        if not urls:
            logger.warning("No VFR files found")
            return None

        # Files are named with dates, so sorting gives us chronological order
        latest_url = sorted(urls)[-1]
        return self.download_file(latest_url, force=force)

    def list_local_files(self, file_type: str = "ST") -> list[Path]:
        """
        List all VFR files in the local data directory.

        Args:
            file_type: Type of files to list - "ST" for state, "OB" for municipalities,
                      or "all" for both.

        Returns:
            List of paths to local VFR files, sorted by name.
        """
        if file_type == "ST":
            return sorted(self.data_dir.glob("*_ST_UKSH.xml.zip"))
        elif file_type == "OB":
            return sorted(self.data_dir.glob("*_OB_*_UKSH.xml.zip"))
        else:  # all
            st_files = list(self.data_dir.glob("*_ST_UKSH.xml.zip"))
            ob_files = list(self.data_dir.glob("*_OB_*_UKSH.xml.zip"))
            return sorted(st_files + ob_files)

    def fetch_ob_file_list(self) -> list[str]:
        """
        Fetch list of available municipality (OB) VFR files from CUZK.

        Returns:
            List of file URLs to download.
        """
        logger.info("Fetching OB file list from %s", self.config.ob_list_url)

        with httpx.Client(timeout=self.config.timeout) as client:
            response = client.get(self.config.ob_list_url)
            response.raise_for_status()

        # Parse the text response - each line contains a file path
        files = []
        for line in response.text.strip().split("\n"):
            line = line.strip()
            if not line:
                continue

            # Extract filename from URL or path
            match = self.OB_FILE_PATTERN.search(line)
            if match:
                filename = match.group(1)
                url = f"{self.config.base_download_url}/{filename}"
                files.append(url)
            elif line.startswith("http"):
                files.append(line)

        logger.info("Found %d OB (municipality) files", len(files))
        return files

    def download_all_municipalities(
        self,
        force: bool = False,
        workers: int | None = None,
        progress_callback: Callable[[int, int, str], None] | None = None,
    ) -> tuple[list[Path], list[str]]:
        """
        Download all municipality (OB) VFR files in parallel.

        Args:
            force: If True, re-download even if files exist.
            workers: Number of parallel download workers (default from config).
            progress_callback: Optional callback(downloaded, total, filename) for progress.

        Returns:
            Tuple of (list of successfully downloaded paths, list of failed URLs).
        """
        urls = self.fetch_ob_file_list()
        if not urls:
            logger.warning("No OB files found")
            return [], []

        num_workers = workers or self.config.max_concurrent_downloads
        total = len(urls)
        downloaded: list[Path] = []
        failed: list[str] = []
        completed_count = 0

        logger.info("Downloading %d municipality files with %d workers...", total, num_workers)

        def download_task(url: str) -> tuple[str, Path | None, str | None]:
            """Download a single file, return (url, path, error)."""
            try:
                path = self.download_file(url, force=force)
                return url, path, None
            except httpx.HTTPError as e:
                return url, None, str(e)
            except Exception as e:
                return url, None, str(e)

        with ThreadPoolExecutor(max_workers=num_workers) as executor:
            futures = {executor.submit(download_task, url): url for url in urls}

            for future in as_completed(futures):
                url, path, error = future.result()
                completed_count += 1
                filename = url.split("/")[-1]

                if error:
                    logger.error("Failed to download %s: %s", filename, error)
                    failed.append(url)
                elif path:
                    downloaded.append(path)

                if progress_callback:
                    progress_callback(completed_count, total, filename)
                else:
                    # Default progress output
                    print(
                        f"\rProgress: {completed_count}/{total} "
                        f"({completed_count * 100 // total}%)",
                        end="",
                        flush=True,
                    )

        print()  # New line after progress
        logger.info(
            "Download complete: %d downloaded, %d skipped, %d failed",
            len(downloaded),
            total - len(downloaded) - len(failed),
            len(failed),
        )
        return downloaded, failed

    def download_latest_ob(self, force: bool = False) -> Path | None:
        """
        Download only the latest (most recent) municipality (OB) VFR files.

        This downloads all OB files from the most recent date.

        Args:
            force: If True, re-download even if file exists.

        Returns:
            Path to one of the downloaded files, or None if failed.
        """
        urls = self.fetch_ob_file_list()
        if not urls:
            logger.warning("No OB files found")
            return None

        # Get the latest date from filenames
        dates = set()
        for url in urls:
            match = self.OB_FILE_PATTERN.search(url)
            if match:
                # Extract date (first 8 chars of filename)
                dates.add(match.group(1)[:8])

        if not dates:
            logger.warning("Could not parse dates from OB filenames")
            return None

        latest_date = sorted(dates)[-1]
        latest_urls = [url for url in urls if f"/{latest_date}_OB_" in url]

        logger.info("Found %d OB files for latest date %s", len(latest_urls), latest_date)

        # Download all files for the latest date
        downloaded, _ = self.download_all_municipalities(
            force=force,
            workers=self.config.max_concurrent_downloads,
        )

        return downloaded[0] if downloaded else None
