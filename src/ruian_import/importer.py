"""Import RUIAN VFR files to PostGIS."""

import logging
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import psycopg2

from .config import DatabaseConfig, get_data_dir

logger = logging.getLogger(__name__)


# Expected tables after import from ST_UKSH (state structure) file
EXPECTED_TABLES_ST = [
    "staty",
    "regionysoudrznosti",
    "vusc",
    "okresy",
    "orp",
    "pou",
]

# Expected tables from OB (municipality) files
EXPECTED_TABLES_OB = [
    "obce",
    "spravniobvody",
    "mop",
    "momc",
    "castiobci",
    "katastralniuzemi",
    "zsj",
    "ulice",
    "parcely",
    "stavebniobjekty",
    "adresnimista",
]

# All possible tables (from both ST and OB files)
EXPECTED_TABLES = EXPECTED_TABLES_ST + EXPECTED_TABLES_OB


class _ProgressCounter:
    """Thread-safe progress counter."""

    def __init__(self, total: int):
        self.total = total
        self.completed = 0
        self.success = 0
        self.failed = 0
        self._lock = threading.Lock()

    def increment(self, success: bool) -> tuple[int, int, int]:
        """Increment counter and return (completed, success, failed)."""
        with self._lock:
            self.completed += 1
            if success:
                self.success += 1
            else:
                self.failed += 1
            return self.completed, self.success, self.failed


class RuianImporter:
    """Importer for RUIAN VFR files to PostGIS."""

    def __init__(self, db_config: DatabaseConfig | None = None):
        self.db_config = db_config or DatabaseConfig()
        self.data_dir = get_data_dir()

    def check_database_connection(self) -> bool:
        """
        Check if database is accessible.

        Returns:
            True if connection successful, False otherwise.
        """
        try:
            with (
                psycopg2.connect(self.db_config.connection_string) as conn,
                conn.cursor() as cur,
            ):
                cur.execute("SELECT PostGIS_Version();")
                row = cur.fetchone()
                version = row[0] if row else "unknown"
                logger.info("Connected to PostGIS version: %s", version)
                return True
        except psycopg2.Error as e:
            logger.error("Database connection failed: %s", e)
            return False

    def ensure_extensions(self) -> None:
        """Ensure required PostGIS extensions are installed."""
        with (
            psycopg2.connect(self.db_config.connection_string) as conn,
            conn.cursor() as cur,
        ):
            cur.execute("CREATE EXTENSION IF NOT EXISTS postgis;")
            cur.execute("CREATE EXTENSION IF NOT EXISTS postgis_topology;")
            conn.commit()
        logger.info("PostGIS extensions ensured")

    def import_file(
        self,
        vfr_file: Path,
        overwrite: bool = True,
        layer: str | None = None,
    ) -> bool:
        """
        Import a single VFR file using ogr2ogr.

        Args:
            vfr_file: Path to the VFR file (xml.zip).
            overwrite: If True, overwrite existing data. If False, append.
            layer: Optional specific layer to import (e.g., 'Obce').

        Returns:
            True if import successful, False otherwise.
        """
        if not vfr_file.exists():
            logger.error("File not found: %s", vfr_file)
            return False

        logger.info("Importing %s...", vfr_file.name)

        # Use /vsizip/ to access XML inside ZIP archive
        # VFR files are XML inside ZIP, e.g., 20251231_ST_UKSH.xml.zip contains 20251231_ST_UKSH.xml
        xml_name = vfr_file.name.replace(".zip", "")
        vsizip_path = f"/vsizip/{vfr_file.absolute()}/{xml_name}"

        cmd = [
            "ogr2ogr",
            "-f",
            "PostgreSQL",
            self.db_config.ogr_connection_string,
            vsizip_path,
            "-progress",
            "-lco",
            "GEOMETRY_NAME=geom",
            "-lco",
            "FID=ogc_fid",
            "-lco",
            "PRECISION=NO",
            "-t_srs",
            "EPSG:5514",  # S-JTSK / Krovak East North
        ]

        if overwrite:
            cmd.append("-overwrite")
        else:
            cmd.append("-append")

        if layer:
            cmd.extend(["-sql", f"SELECT * FROM {layer}"])

        try:
            result = subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                text=True,
            )
            if result.stdout:
                logger.debug("ogr2ogr output: %s", result.stdout)
            logger.info("Successfully imported %s", vfr_file.name)
            return True
        except subprocess.CalledProcessError as e:
            logger.error("Failed to import %s: %s", vfr_file.name, e.stderr)
            return False
        except FileNotFoundError:
            logger.error(
                "ogr2ogr not found. Please install GDAL with VFR support. "
                "On macOS: brew install gdal"
            )
            return False

    def import_all(self, overwrite: bool = True) -> tuple[int, int]:
        """
        Import all VFR files from the data directory.

        Args:
            overwrite: If True, overwrite existing data for each file.

        Returns:
            Tuple of (successful imports, failed imports).
        """
        files = sorted(self.data_dir.glob("*_ST_UKSH.xml.zip"))

        if not files:
            logger.warning("No VFR files found in %s", self.data_dir)
            return 0, 0

        logger.info("Found %d VFR files to import", len(files))

        success = 0
        failed = 0

        for vfr_file in files:
            if self.import_file(vfr_file, overwrite=overwrite):
                success += 1
            else:
                failed += 1

        logger.info("Import complete: %d success, %d failed", success, failed)
        return success, failed

    def import_latest(self, overwrite: bool = True) -> bool:
        """
        Import the latest (most recent) VFR file.

        Args:
            overwrite: If True, overwrite existing data.

        Returns:
            True if import successful, False otherwise.
        """
        files = sorted(self.data_dir.glob("*_ST_UKSH.xml.zip"))

        if not files:
            logger.warning("No VFR files found in %s", self.data_dir)
            return False

        latest_file = files[-1]
        return self.import_file(latest_file, overwrite=overwrite)

    def get_table_stats(self) -> dict[str, int]:
        """
        Get row counts for all imported tables.

        Returns:
            Dictionary of table names to row counts.
        """
        stats = {}

        with (
            psycopg2.connect(self.db_config.connection_string) as conn,
            conn.cursor() as cur,
        ):
            # Get list of tables
            cur.execute("""
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                AND table_type = 'BASE TABLE'
                ORDER BY table_name;
            """)
            tables = [row[0] for row in cur.fetchall()]

            for table in tables:
                try:
                    cur.execute(f'SELECT COUNT(*) FROM "{table}";')
                    row = cur.fetchone()
                    count = row[0] if row else 0
                    stats[table] = count
                except psycopg2.Error as e:
                    logger.warning("Could not count rows in %s: %s", table, e)
                    conn.rollback()

        return stats

    def verify_import(self) -> bool:
        """
        Verify that expected tables exist and have data.

        Returns:
            True if verification passed, False otherwise.
        """
        stats = self.get_table_stats()

        if not stats:
            logger.error("No tables found in database")
            return False

        logger.info("Table statistics:")
        all_ok = True

        for table in EXPECTED_TABLES:
            if table in stats:
                count = stats[table]
                logger.info("  %s: %d rows", table, count)
                if count == 0:
                    logger.warning("  WARNING: Table %s is empty", table)
            else:
                logger.warning("  %s: NOT FOUND", table)
                all_ok = False

        return all_ok

    def list_local_ob_files(self) -> list[Path]:
        """
        List all OB (municipality) VFR files in the local data directory.

        Returns:
            List of paths to local OB VFR files, sorted by name.
        """
        return sorted(self.data_dir.glob("*_OB_*_UKSH.xml.zip"))

    def get_imported_ob_files(self) -> set[str]:
        """
        Get set of OB filenames that have already been imported.

        Uses a tracking table to remember which files have been imported.

        Returns:
            Set of imported OB filenames (without path).
        """
        imported: set[str] = set()
        try:
            with (
                psycopg2.connect(self.db_config.connection_string) as conn,
                conn.cursor() as cur,
            ):
                # Check if tracking table exists
                cur.execute("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables
                        WHERE table_schema = 'public'
                        AND table_name = 'ruian_import_log'
                    );
                """)
                row = cur.fetchone()
                if not row or not row[0]:
                    return imported

                cur.execute("SELECT filename FROM ruian_import_log WHERE status = 'success';")
                for row in cur.fetchall():
                    imported.add(row[0])
        except psycopg2.Error as e:
            logger.warning("Could not read import log: %s", e)

        return imported

    def _ensure_import_log_table(self) -> None:
        """Create import log table if it doesn't exist."""
        with (
            psycopg2.connect(self.db_config.connection_string) as conn,
            conn.cursor() as cur,
        ):
            cur.execute("""
                CREATE TABLE IF NOT EXISTS ruian_import_log (
                    id SERIAL PRIMARY KEY,
                    filename VARCHAR(255) NOT NULL UNIQUE,
                    status VARCHAR(50) NOT NULL,
                    imported_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    error_message TEXT
                );
            """)
            conn.commit()

    def _log_import(self, filename: str, status: str, error_message: str | None = None) -> None:
        """Log import status for a file."""
        with (
            psycopg2.connect(self.db_config.connection_string) as conn,
            conn.cursor() as cur,
        ):
            cur.execute(
                """
                INSERT INTO ruian_import_log (filename, status, error_message)
                VALUES (%s, %s, %s)
                ON CONFLICT (filename) DO UPDATE
                SET status = EXCLUDED.status,
                    imported_at = CURRENT_TIMESTAMP,
                    error_message = EXCLUDED.error_message;
                """,
                (filename, status, error_message),
            )
            conn.commit()

    def import_all_municipalities(
        self,
        resume: bool = False,
        workers: int = 1,
    ) -> tuple[int, int, int]:
        """
        Import all municipality (OB) VFR files from the data directory.

        OB files are always imported in append mode to add data from each
        municipality to the existing tables.

        Args:
            resume: If True, skip files that have already been imported.
            workers: Number of parallel import workers (default: 1 for sequential).

        Returns:
            Tuple of (successful imports, skipped, failed imports).
        """
        files = self.list_local_ob_files()

        if not files:
            logger.warning("No OB files found in %s", self.data_dir)
            return 0, 0, 0

        # Ensure tracking table exists
        self._ensure_import_log_table()

        # Get already imported files if resuming
        imported_files = self.get_imported_ob_files() if resume else set()

        # Filter out already imported files
        if resume and imported_files:
            original_count = len(files)
            files = [f for f in files if f.name not in imported_files]
            skipped_initial = original_count - len(files)
            if skipped_initial > 0:
                logger.info("Resuming: skipping %d already imported files", skipped_initial)
        else:
            skipped_initial = 0

        total = len(files)
        if total == 0:
            logger.info("All OB files have already been imported")
            return 0, skipped_initial, 0

        logger.info("Importing %d OB files (append mode, %d workers)...", total, workers)

        if workers > 1:
            # Parallel import
            success, failed = self._import_municipalities_parallel(files, workers)
        else:
            # Sequential import (original behavior)
            success, failed = self._import_municipalities_sequential(files)

        logger.info(
            "Import complete: %d success, %d skipped, %d failed",
            success,
            skipped_initial,
            failed,
        )
        return success, skipped_initial, failed

    def _import_municipalities_sequential(
        self,
        files: list[Path],
    ) -> tuple[int, int]:
        """
        Import municipality files sequentially.

        Args:
            files: List of VFR files to import.

        Returns:
            Tuple of (success, failed) counts.
        """
        total = len(files)
        success = 0
        failed = 0

        for i, vfr_file in enumerate(files, 1):
            print(
                f"\rImporting {i}/{total}: {vfr_file.name}... ",
                end="",
                flush=True,
            )

            try:
                # Always use append mode for OB files
                if self.import_file(vfr_file, overwrite=False):
                    success += 1
                    self._log_import(vfr_file.name, "success")
                    print("OK")
                else:
                    failed += 1
                    self._log_import(vfr_file.name, "failed", "import_file returned False")
                    print("FAILED")
            except Exception as e:
                failed += 1
                error_msg = str(e)
                self._log_import(vfr_file.name, "failed", error_msg)
                logger.error("Failed to import %s: %s", vfr_file.name, error_msg)
                print("FAILED")

            # Progress update every 100 files
            if i % 100 == 0:
                logger.info(
                    "Progress: %d/%d (%d%%) - %d success, %d failed",
                    i,
                    total,
                    i * 100 // total,
                    success,
                    failed,
                )

        return success, failed

    def _import_municipalities_parallel(
        self,
        files: list[Path],
        workers: int,
    ) -> tuple[int, int]:
        """
        Import municipality files in parallel using ThreadPoolExecutor.

        Args:
            files: List of VFR files to import.
            workers: Number of parallel workers.

        Returns:
            Tuple of (success, failed) counts.
        """
        total = len(files)
        progress = _ProgressCounter(total)

        def import_task(vfr_file: Path) -> tuple[Path, bool, str | None]:
            """Import single file, return (path, success, error)."""
            try:
                result = self.import_file(vfr_file, overwrite=False)
                return vfr_file, result, None
            except Exception as e:
                return vfr_file, False, str(e)

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(import_task, f): f for f in files}

            for future in as_completed(futures):
                vfr_file, ok, error = future.result()
                completed, succ, fail = progress.increment(ok)

                if ok:
                    self._log_import(vfr_file.name, "success")
                else:
                    error_msg = error or "import_file returned False"
                    self._log_import(vfr_file.name, "failed", error_msg)
                    if error:
                        logger.error("Failed to import %s: %s", vfr_file.name, error)

                # Progress update every 100 files
                if completed % 100 == 0:
                    logger.info(
                        "Progress: %d/%d (%d%%) - %d ok, %d failed",
                        completed,
                        total,
                        completed * 100 // total,
                        succ,
                        fail,
                    )

        return progress.success, progress.failed

    def import_latest_municipalities(self) -> tuple[int, int]:
        """
        Import OB files from the latest (most recent) date.

        Returns:
            Tuple of (successful imports, failed imports).
        """
        files = self.list_local_ob_files()

        if not files:
            logger.warning("No OB files found in %s", self.data_dir)
            return 0, 0

        # Get the latest date from filenames
        dates = set()
        for f in files:
            # Extract date (first 8 chars of filename)
            dates.add(f.name[:8])

        if not dates:
            logger.warning("Could not parse dates from OB filenames")
            return 0, 0

        latest_date = sorted(dates)[-1]
        latest_files = [f for f in files if f.name.startswith(latest_date)]

        logger.info("Found %d OB files for latest date %s", len(latest_files), latest_date)

        # Ensure tracking table exists
        self._ensure_import_log_table()

        success = 0
        failed = 0
        total = len(latest_files)

        for i, vfr_file in enumerate(latest_files, 1):
            print(
                f"\rImporting {i}/{total}: {vfr_file.name}... ",
                end="",
                flush=True,
            )

            if self.import_file(vfr_file, overwrite=False):
                success += 1
                self._log_import(vfr_file.name, "success")
                print("OK")
            else:
                failed += 1
                self._log_import(vfr_file.name, "failed", "import_file returned False")
                print("FAILED")

        logger.info("Import complete: %d success, %d failed", success, failed)
        return success, failed

    def sample_query(self, table: str = "obec", limit: int = 5) -> list[dict[str, Any]]:
        """
        Run a sample query to verify data.

        Args:
            table: Table to query.
            limit: Maximum rows to return.

        Returns:
            List of dictionaries with results.
        """
        results = []

        with (
            psycopg2.connect(self.db_config.connection_string) as conn,
            conn.cursor() as cur,
        ):
            try:
                cur.execute(
                    f"""
                    SELECT nazev, kod, ST_AsText(ST_Centroid(geom)) as centroid
                    FROM "{table}"
                    LIMIT %s;
                """,
                    (limit,),
                )

                description = cur.description
                if description:
                    columns = [desc[0] for desc in description]
                    for row in cur.fetchall():
                        results.append(dict(zip(columns, row, strict=True)))
            except psycopg2.Error as e:
                logger.error("Sample query failed: %s", e)

        return results
