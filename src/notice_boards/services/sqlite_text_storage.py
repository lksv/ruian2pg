"""Compressed text storage using SQLite + zstd dictionary compression.

Stores extracted text from document attachments in SQLite files organized
by NUTS3 region and year, using zstd compression with trained dictionaries
for high compression ratios on similar Czech legal/admin texts.

Directory structure: base_path/{nuts3_id}/{year}.sqlite
Boards without NUTS3 go to base_path/_unknown/{year}.sqlite

Usage:
    from notice_boards.services.sqlite_text_storage import SqliteTextStorage
    from notice_boards.services.text_extractor import PendingExtraction

    storage = SqliteTextStorage(Path("data/texts"))

    # Save text (compresses automatically)
    compressed_size = storage.save(pending, "Extracted text...")

    # Load text (decompresses automatically)
    text = storage.load(pending)

    # Get stats across all files
    stats = storage.get_stats()
"""

import logging
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING, Any

import zstandard as zstd

if TYPE_CHECKING:
    from notice_boards.services.text_extractor import PendingExtraction

logger = logging.getLogger(__name__)

# Number of texts needed before training a per-file compression dictionary
DICT_TRAINING_THRESHOLD = 50

# Number of texts (across all files) needed before training a global dictionary
GLOBAL_DICT_TRAINING_THRESHOLD = 200

# Maximum number of samples used for dictionary training
DICT_TRAINING_MAX_SAMPLES = 500

# Target dictionary size in bytes
DICT_SIZE = 112 * 1024  # 112 KB

# dict_id value for texts compressed without a dictionary
NO_DICT_ID = 0

# Special dict_id for texts compressed with the global dictionary
GLOBAL_DICT_ID = -1

# Filename for the global dictionary database
GLOBAL_DICT_DB = "_global_dict.sqlite"


class SqliteTextStorage:
    """Compressed text storage using SQLite files with zstd compression.

    Each SQLite file contains a 'texts' table for compressed text blobs
    and a 'dictionaries' table for trained zstd dictionaries.

    Files are organized by NUTS3 region and year, derived from
    PendingExtraction attributes via _compute_ref().
    """

    def __init__(self, base_path: Path) -> None:
        """Initialize storage.

        Args:
            base_path: Root directory for SQLite files (e.g., data/texts).
        """
        self.base_path = base_path
        self._connections: dict[str, sqlite3.Connection] = {}
        self._dicts: dict[str, zstd.ZstdCompressionDict | None] = {}
        self._global_dict: zstd.ZstdCompressionDict | None = None
        self._global_dict_loaded = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def save(self, pending: "PendingExtraction", text: str) -> int:
        """Compress and save text for an attachment.

        Args:
            pending: PendingExtraction with context for partitioning.
            text: Extracted text to store.

        Returns:
            Compressed size in bytes.
        """
        ref = self._compute_ref(pending)
        conn = self._get_connection(ref)
        data = self._compress(ref, conn, text)
        dict_id = self._current_dict_id(ref, conn)

        conn.execute(
            """
            INSERT OR REPLACE INTO texts
                (attachment_id, data, dict_id, original_size, compressed_size)
            VALUES (?, ?, ?, ?, ?)
            """,
            (pending.id, data, dict_id, len(text.encode("utf-8")), len(data)),
        )
        conn.commit()

        # Check if we should train a dictionary
        self._maybe_train_dictionary(ref, conn)

        return len(data)

    def load(self, pending: "PendingExtraction") -> str | None:
        """Load and decompress text for an attachment.

        Args:
            pending: PendingExtraction with context for partitioning.

        Returns:
            Decompressed text, or None if not found.
        """
        ref = self._compute_ref(pending)
        db_path = self.base_path / ref
        if not db_path.exists():
            return None

        conn = self._get_connection(ref)
        row = conn.execute(
            "SELECT data, dict_id FROM texts WHERE attachment_id = ?",
            (pending.id,),
        ).fetchone()
        if row is None:
            return None

        data: bytes = row[0]
        dict_id: int = row[1]
        return self._decompress(ref, conn, data, dict_id)

    def load_by_id(self, attachment_id: int, nuts3_id: int | None, year: int | None) -> str | None:
        """Load text by attachment ID and partition info.

        Convenience method when PendingExtraction is not available.

        Args:
            attachment_id: Database ID of the attachment.
            nuts3_id: NUTS3 region ID (None for unknown).
            year: Publication year (None for no-date).

        Returns:
            Decompressed text, or None if not found.
        """
        ref = self._compute_ref_from_parts(nuts3_id, year)
        db_path = self.base_path / ref
        if not db_path.exists():
            return None

        conn = self._get_connection(ref)
        row = conn.execute(
            "SELECT data, dict_id FROM texts WHERE attachment_id = ?",
            (attachment_id,),
        ).fetchone()
        if row is None:
            return None

        data: bytes = row[0]
        dict_id: int = row[1]
        return self._decompress(ref, conn, data, dict_id)

    def delete(self, pending: "PendingExtraction") -> bool:
        """Delete text entry for an attachment.

        Args:
            pending: PendingExtraction with context for partitioning.

        Returns:
            True if found and deleted, False otherwise.
        """
        ref = self._compute_ref(pending)
        db_path = self.base_path / ref
        if not db_path.exists():
            return False

        conn = self._get_connection(ref)
        cursor = conn.execute(
            "DELETE FROM texts WHERE attachment_id = ?",
            (pending.id,),
        )
        conn.commit()
        return cursor.rowcount > 0

    def exists(self, pending: "PendingExtraction") -> bool:
        """Check if text exists for an attachment.

        Args:
            pending: PendingExtraction with context for partitioning.

        Returns:
            True if text exists.
        """
        ref = self._compute_ref(pending)
        db_path = self.base_path / ref
        if not db_path.exists():
            return False

        conn = self._get_connection(ref)
        row = conn.execute(
            "SELECT 1 FROM texts WHERE attachment_id = ?",
            (pending.id,),
        ).fetchone()
        return row is not None

    def get_stats(self) -> dict[str, Any]:
        """Get aggregated statistics across all SQLite files.

        Returns:
            Dict with total_texts, total_original_bytes, total_compressed_bytes,
            compression_ratio, num_files, num_dictionaries.
        """
        total_texts = 0
        total_original = 0
        total_compressed = 0
        num_files = 0
        num_dicts = 0

        for db_path in self.base_path.rglob("*.sqlite"):
            if db_path.name == GLOBAL_DICT_DB:
                continue
            ref = str(db_path.relative_to(self.base_path))
            conn = self._get_connection(ref)
            num_files += 1

            row = conn.execute(
                """
                SELECT COUNT(*), COALESCE(SUM(original_size), 0),
                       COALESCE(SUM(compressed_size), 0)
                FROM texts
                """
            ).fetchone()
            if row:
                total_texts += row[0]
                total_original += row[1]
                total_compressed += row[2]

            dict_row = conn.execute("SELECT COUNT(*) FROM dictionaries").fetchone()
            if dict_row:
                num_dicts += dict_row[0]

        ratio = total_original / total_compressed if total_compressed > 0 else 0.0

        return {
            "total_texts": total_texts,
            "total_original_bytes": total_original,
            "total_compressed_bytes": total_compressed,
            "compression_ratio": round(ratio, 2),
            "num_files": num_files,
            "num_dictionaries": num_dicts,
        }

    def close(self) -> None:
        """Close all open SQLite connections."""
        for conn in self._connections.values():
            conn.close()
        self._connections.clear()
        self._dicts.clear()
        self._global_dict = None
        self._global_dict_loaded = False

    def __enter__(self) -> "SqliteTextStorage":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Internal: partitioning
    # ------------------------------------------------------------------

    def _compute_ref(self, pending: "PendingExtraction") -> str:
        """Compute relative SQLite file path from pending extraction context.

        Default scheme: '{nuts3_id}/{year}.sqlite' or '_unknown/{year}.sqlite'.

        This is the ONLY method to change when the partition scheme changes.
        """
        nuts3_id = getattr(pending, "nuts3_id", None)
        published_at = getattr(pending, "published_at", None)
        year = published_at.year if published_at else None
        return self._compute_ref_from_parts(nuts3_id, year)

    def _compute_ref_from_parts(self, nuts3_id: int | None, year: int | None) -> str:
        """Compute ref from raw partition values."""
        nuts3 = str(nuts3_id) if nuts3_id else "_unknown"
        year_str = str(year) if year else "_nodate"
        return f"{nuts3}/{year_str}.sqlite"

    # ------------------------------------------------------------------
    # Internal: connection management
    # ------------------------------------------------------------------

    def _get_connection(self, ref: str) -> sqlite3.Connection:
        """Get or create a pooled SQLite connection for the given ref."""
        if ref in self._connections:
            return self._connections[ref]

        db_path = self.base_path / ref
        db_path.parent.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        self._ensure_schema(conn)

        self._connections[ref] = conn
        return conn

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        """Create tables if they don't exist."""
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS texts (
                attachment_id INTEGER PRIMARY KEY,
                data BLOB NOT NULL,
                dict_id INTEGER DEFAULT 0,
                original_size INTEGER NOT NULL,
                compressed_size INTEGER NOT NULL,
                created_at TEXT DEFAULT (datetime('now'))
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS dictionaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                dict_data BLOB NOT NULL,
                sample_count INTEGER NOT NULL,
                created_at TEXT DEFAULT (datetime('now'))
            )
            """
        )
        conn.commit()

    # ------------------------------------------------------------------
    # Internal: compression
    # ------------------------------------------------------------------

    def _load_global_dict(self) -> zstd.ZstdCompressionDict | None:
        """Load the global dictionary from _global_dict.sqlite, cached."""
        if self._global_dict_loaded:
            return self._global_dict

        self._global_dict_loaded = True
        db_path = self.base_path / GLOBAL_DICT_DB
        if not db_path.exists():
            return None

        try:
            gconn = sqlite3.connect(str(db_path))
            row = gconn.execute(
                "SELECT dict_data FROM dictionaries ORDER BY id DESC LIMIT 1"
            ).fetchone()
            gconn.close()
        except sqlite3.Error:
            return None

        if row is None:
            return None

        self._global_dict = zstd.ZstdCompressionDict(row[0])
        logger.info("Loaded global zstd dictionary (%d bytes)", len(row[0]))
        return self._global_dict

    def _get_dict(self, ref: str, conn: sqlite3.Connection) -> zstd.ZstdCompressionDict | None:
        """Get the best compression dictionary for a ref.

        Priority: per-file dictionary > global dictionary > None.
        """
        if ref in self._dicts:
            return self._dicts[ref]

        row = conn.execute(
            "SELECT id, dict_data FROM dictionaries ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row is not None:
            dict_data: bytes = row[1]
            d = zstd.ZstdCompressionDict(dict_data)
            self._dicts[ref] = d
            return d

        # Fall back to global dictionary
        gd = self._load_global_dict()
        if gd is not None:
            self._dicts[ref] = gd
            return gd

        self._dicts[ref] = None
        return None

    def _is_global_dict(self, ref: str, conn: sqlite3.Connection) -> bool:
        """Check if the current dict for this ref is the global one (no per-file dict)."""
        row = conn.execute("SELECT COUNT(*) FROM dictionaries").fetchone()
        return (row is None or row[0] == 0) and self._load_global_dict() is not None

    def _current_dict_id(self, ref: str, conn: sqlite3.Connection) -> int:
        """Get the dict_id for new texts: per-file ID, GLOBAL_DICT_ID, or NO_DICT_ID."""
        d = self._get_dict(ref, conn)
        if d is None:
            return NO_DICT_ID

        if self._is_global_dict(ref, conn):
            return GLOBAL_DICT_ID

        row = conn.execute("SELECT id FROM dictionaries ORDER BY id DESC LIMIT 1").fetchone()
        return row[0] if row else NO_DICT_ID

    def _compress(self, ref: str, conn: sqlite3.Connection, text: str) -> bytes:
        """Compress text using dictionary if available, else plain zstd."""
        text_bytes = text.encode("utf-8")
        d = self._get_dict(ref, conn)
        cctx = zstd.ZstdCompressor(dict_data=d) if d is not None else zstd.ZstdCompressor()
        return cctx.compress(text_bytes)

    def _decompress(self, ref: str, conn: sqlite3.Connection, data: bytes, dict_id: int) -> str:
        """Decompress data with the correct dictionary."""
        if dict_id == NO_DICT_ID:
            dctx = zstd.ZstdDecompressor()
        elif dict_id == GLOBAL_DICT_ID:
            gd = self._load_global_dict()
            if gd is None:
                logger.warning(
                    "Global dictionary not found for %s, decompressing without dict", ref
                )
                dctx = zstd.ZstdDecompressor()
            else:
                dctx = zstd.ZstdDecompressor(dict_data=gd)
        else:
            # Load the specific per-file dictionary
            row = conn.execute(
                "SELECT dict_data FROM dictionaries WHERE id = ?", (dict_id,)
            ).fetchone()
            if row is None:
                # Dictionary missing — try without it (best effort)
                logger.warning(
                    "Dictionary %d not found in %s, decompressing without dict",
                    dict_id,
                    ref,
                )
                dctx = zstd.ZstdDecompressor()
            else:
                d = zstd.ZstdCompressionDict(row[0])
                dctx = zstd.ZstdDecompressor(dict_data=d)

        return dctx.decompress(data).decode("utf-8")

    def _maybe_train_dictionary(self, ref: str, conn: sqlite3.Connection) -> None:
        """Train a per-file dictionary if enough samples exist and no dictionary yet.

        Also triggers global dictionary training if enough total texts exist.
        """
        # Check if per-file dictionary already exists
        existing = conn.execute("SELECT COUNT(*) FROM dictionaries").fetchone()
        if existing and existing[0] > 0:
            return

        # Check if we have enough samples for per-file dictionary
        count_row = conn.execute("SELECT COUNT(*) FROM texts").fetchone()
        if count_row and count_row[0] >= DICT_TRAINING_THRESHOLD:
            self._train_per_file_dictionary(ref, conn)
        elif self._load_global_dict() is None:
            # No global dict yet — check if we have enough total texts
            self._maybe_train_global_dictionary()

    def _train_per_file_dictionary(self, ref: str, conn: sqlite3.Connection) -> None:
        """Train a per-file dictionary from texts in this SQLite file."""
        count_row = conn.execute("SELECT COUNT(*) FROM texts").fetchone()
        sample_count = count_row[0] if count_row else 0
        logger.info("Training zstd dictionary for %s (%d samples)...", ref, sample_count)

        samples = self._collect_samples(conn)
        if len(samples) < DICT_TRAINING_THRESHOLD:
            return

        try:
            dict_data = zstd.train_dictionary(DICT_SIZE, samples)  # type: ignore[arg-type]
        except zstd.ZstdError as e:
            logger.warning("Failed to train dictionary for %s: %s", ref, e)
            return

        conn.execute(
            "INSERT INTO dictionaries (dict_data, sample_count) VALUES (?, ?)",
            (dict_data.as_bytes(), len(samples)),
        )
        conn.commit()

        # Clear cached dict so next access picks up the new one
        self._dicts.pop(ref, None)

        logger.info(
            "Trained per-file dictionary for %s: %d bytes from %d samples",
            ref,
            len(dict_data.as_bytes()),
            len(samples),
        )

    def _maybe_train_global_dictionary(self) -> None:
        """Train a global dictionary from samples across all SQLite files.

        Triggered automatically when enough total texts exist but no global
        dictionary has been trained yet.
        """
        # Count total texts across all files
        total = 0
        for db_path in self.base_path.rglob("*.sqlite"):
            if db_path.name == GLOBAL_DICT_DB:
                continue
            try:
                ref = str(db_path.relative_to(self.base_path))
                c = self._get_connection(ref)
                row = c.execute("SELECT COUNT(*) FROM texts").fetchone()
                if row:
                    total += row[0]
            except sqlite3.Error:
                continue

        if total < GLOBAL_DICT_TRAINING_THRESHOLD:
            return

        self.train_global_dictionary()

    def train_global_dictionary(self) -> bool:
        """Train a global dictionary from samples across all SQLite files.

        Collects samples from every partition file and trains a single
        dictionary stored in _global_dict.sqlite. This dictionary is used
        as fallback for files that don't have their own per-file dictionary.

        Returns:
            True if dictionary was trained successfully.
        """
        logger.info("Training global zstd dictionary...")

        # Collect samples across all files (round-robin to get diversity)
        all_samples: list[bytes] = []
        file_refs: list[str] = []

        for db_path in sorted(self.base_path.rglob("*.sqlite")):
            if db_path.name == GLOBAL_DICT_DB:
                continue
            file_refs.append(str(db_path.relative_to(self.base_path)))

        if not file_refs:
            logger.warning("No SQLite files found for global dictionary training")
            return False

        # Take samples from each file proportionally
        per_file = max(5, DICT_TRAINING_MAX_SAMPLES // len(file_refs))

        for ref in file_refs:
            conn = self._get_connection(ref)
            samples = self._collect_samples(conn, limit=per_file)
            all_samples.extend(samples)

        if len(all_samples) < GLOBAL_DICT_TRAINING_THRESHOLD:
            logger.warning(
                "Not enough samples for global dictionary: %d (need %d)",
                len(all_samples),
                GLOBAL_DICT_TRAINING_THRESHOLD,
            )
            return False

        # Cap at max samples
        if len(all_samples) > DICT_TRAINING_MAX_SAMPLES:
            all_samples = all_samples[:DICT_TRAINING_MAX_SAMPLES]

        try:
            dict_data = zstd.train_dictionary(DICT_SIZE, all_samples)  # type: ignore[arg-type]
        except zstd.ZstdError as e:
            logger.warning("Failed to train global dictionary: %s", e)
            return False

        # Store in global dict database
        db_path = self.base_path / GLOBAL_DICT_DB
        gconn = sqlite3.connect(str(db_path))
        gconn.execute(
            """
            CREATE TABLE IF NOT EXISTS dictionaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                dict_data BLOB NOT NULL,
                sample_count INTEGER NOT NULL,
                created_at TEXT DEFAULT (datetime('now'))
            )
            """
        )
        gconn.execute(
            "INSERT INTO dictionaries (dict_data, sample_count) VALUES (?, ?)",
            (dict_data.as_bytes(), len(all_samples)),
        )
        gconn.commit()
        gconn.close()

        # Reset cached state so all refs pick up the new global dict
        self._global_dict = None
        self._global_dict_loaded = False
        self._dicts.clear()

        logger.info(
            "Trained global dictionary: %d bytes from %d samples across %d files",
            len(dict_data.as_bytes()),
            len(all_samples),
            len(file_refs),
        )
        return True

    def _collect_samples(
        self, conn: sqlite3.Connection, limit: int = DICT_TRAINING_MAX_SAMPLES
    ) -> list[bytes]:
        """Collect decompressed text samples from a SQLite connection."""
        rows = conn.execute(
            "SELECT data, dict_id FROM texts ORDER BY attachment_id LIMIT ?",
            (limit,),
        ).fetchall()

        dctx_plain = zstd.ZstdDecompressor()
        gd = self._load_global_dict()
        dctx_global = zstd.ZstdDecompressor(dict_data=gd) if gd else None

        samples: list[bytes] = []
        for data, dict_id in rows:
            try:
                if dict_id == NO_DICT_ID:
                    samples.append(bytes(dctx_plain.decompress(data)))
                elif dict_id == GLOBAL_DICT_ID and dctx_global:
                    samples.append(bytes(dctx_global.decompress(data)))
                else:
                    # Per-file dict — decompress with it
                    row = conn.execute(
                        "SELECT dict_data FROM dictionaries WHERE id = ?", (dict_id,)
                    ).fetchone()
                    if row:
                        d = zstd.ZstdCompressionDict(row[0])
                        dctx = zstd.ZstdDecompressor(dict_data=d)
                        samples.append(bytes(dctx.decompress(data)))
            except zstd.ZstdError:
                continue
        return samples

    def recompress_with_dictionary(self, ref: str) -> int:
        """Re-compress texts that were stored without a dictionary.

        Call after a dictionary has been trained to improve compression
        for older texts. Handles both plain (dict_id=0) and global-dict
        (dict_id=-1) texts when a per-file dictionary becomes available.

        Args:
            ref: Relative path to the SQLite file (e.g., '116/2024.sqlite').

        Returns:
            Number of texts re-compressed.
        """
        conn = self._get_connection(ref)
        d = self._get_dict(ref, conn)
        if d is None:
            return 0

        dict_id = self._current_dict_id(ref, conn)
        if dict_id == NO_DICT_ID:
            return 0

        # Find texts without dictionary or with global dict only
        rows = conn.execute(
            "SELECT attachment_id, data, dict_id FROM texts WHERE dict_id IN (?, ?)",
            (NO_DICT_ID, GLOBAL_DICT_ID),
        ).fetchall()

        if not rows:
            return 0

        dctx_plain = zstd.ZstdDecompressor()
        gd = self._load_global_dict()
        dctx_global = zstd.ZstdDecompressor(dict_data=gd) if gd else None
        cctx = zstd.ZstdCompressor(dict_data=d)
        count = 0

        for attachment_id, data, old_dict_id in rows:
            try:
                if old_dict_id == GLOBAL_DICT_ID and dctx_global:
                    text_bytes = dctx_global.decompress(data)
                else:
                    text_bytes = dctx_plain.decompress(data)
                new_data = cctx.compress(text_bytes)
                conn.execute(
                    """
                    UPDATE texts
                    SET data = ?, dict_id = ?, compressed_size = ?
                    WHERE attachment_id = ?
                    """,
                    (new_data, dict_id, len(new_data), attachment_id),
                )
                count += 1
            except zstd.ZstdError:
                continue

        conn.commit()
        return count

    def recompress_all(self) -> dict[str, int]:
        """Re-compress all texts across all files using the best available dictionary.

        Returns:
            Dict mapping ref to number of texts re-compressed.
        """
        results: dict[str, int] = {}
        for db_path in sorted(self.base_path.rglob("*.sqlite")):
            if db_path.name == GLOBAL_DICT_DB:
                continue
            ref = str(db_path.relative_to(self.base_path))
            count = self.recompress_with_dictionary(ref)
            if count > 0:
                results[ref] = count
                logger.info("Re-compressed %d texts in %s", count, ref)
        return results
