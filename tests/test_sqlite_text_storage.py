"""Tests for SqliteTextStorage."""

from datetime import date
from pathlib import Path

from notice_boards.services.sqlite_text_storage import (
    DICT_TRAINING_THRESHOLD,
    GLOBAL_DICT_ID,
    GLOBAL_DICT_TRAINING_THRESHOLD,
    NO_DICT_ID,
    SqliteTextStorage,
)
from notice_boards.services.text_extractor import PendingExtraction

_SENTINEL = object()


def make_pending(
    attachment_id: int = 1,
    nuts3_id: int | None = 116,
    published_at: date | None | object = _SENTINEL,
    **kwargs: object,
) -> PendingExtraction:
    """Create a PendingExtraction for testing."""
    if published_at is _SENTINEL:
        published_at = date(2024, 6, 15)
    return PendingExtraction(
        id=attachment_id,
        document_id=int(kwargs.get("document_id", 10)),  # type: ignore[arg-type]
        notice_board_id=int(kwargs.get("notice_board_id", 100)),  # type: ignore[arg-type]
        filename=str(kwargs.get("filename", "test.pdf")),
        mime_type=str(kwargs.get("mime_type", "application/pdf")),
        file_size_bytes=int(kwargs.get("file_size_bytes", 1024)),  # type: ignore[arg-type]
        storage_path=kwargs.get("storage_path"),  # type: ignore[arg-type]
        orig_url=kwargs.get("orig_url"),  # type: ignore[arg-type]
        download_status=str(kwargs.get("download_status", "downloaded")),
        board_name=str(kwargs.get("board_name", "Test Board")),
        nuts3_id=nuts3_id,
        published_at=published_at,
    )


class TestSaveAndLoad:
    """Tests for basic save/load round-trip."""

    def test_save_and_load(self, tmp_path: Path) -> None:
        """Test text round-trips through compression."""
        storage = SqliteTextStorage(tmp_path)
        pending = make_pending()
        text = "This is a test document about Czech municipalities."

        compressed_size = storage.save(pending, text)
        assert compressed_size > 0

        loaded = storage.load(pending)
        assert loaded == text
        storage.close()

    def test_save_empty_text(self, tmp_path: Path) -> None:
        """Test saving empty text."""
        storage = SqliteTextStorage(tmp_path)
        pending = make_pending()

        compressed_size = storage.save(pending, "")
        assert compressed_size > 0

        loaded = storage.load(pending)
        assert loaded == ""
        storage.close()

    def test_save_unicode_text(self, tmp_path: Path) -> None:
        """Test saving Czech text with diacritics."""
        storage = SqliteTextStorage(tmp_path)
        pending = make_pending()
        text = "Rozhodnutí o povolení stavby na pozemku č. 592/2 v k.ú. Veveří"

        storage.save(pending, text)
        loaded = storage.load(pending)
        assert loaded == text
        storage.close()

    def test_save_overwrites_existing(self, tmp_path: Path) -> None:
        """Test that save replaces existing text for same attachment."""
        storage = SqliteTextStorage(tmp_path)
        pending = make_pending()

        storage.save(pending, "first version")
        storage.save(pending, "second version")

        loaded = storage.load(pending)
        assert loaded == "second version"
        storage.close()

    def test_load_nonexistent_returns_none(self, tmp_path: Path) -> None:
        """Test loading from non-existent file returns None."""
        storage = SqliteTextStorage(tmp_path)
        pending = make_pending(attachment_id=999)

        loaded = storage.load(pending)
        assert loaded is None
        storage.close()

    def test_load_nonexistent_db_returns_none(self, tmp_path: Path) -> None:
        """Test loading when SQLite file doesn't exist returns None."""
        storage = SqliteTextStorage(tmp_path)
        pending = make_pending(nuts3_id=999, attachment_id=1)

        loaded = storage.load(pending)
        assert loaded is None
        storage.close()


class TestLoadById:
    """Tests for load_by_id convenience method."""

    def test_load_by_id(self, tmp_path: Path) -> None:
        """Test loading text by ID and partition info."""
        storage = SqliteTextStorage(tmp_path)
        pending = make_pending(attachment_id=42, nuts3_id=116, published_at=date(2024, 1, 1))
        text = "Test text for load_by_id"

        storage.save(pending, text)
        loaded = storage.load_by_id(42, nuts3_id=116, year=2024)
        assert loaded == text
        storage.close()

    def test_load_by_id_not_found(self, tmp_path: Path) -> None:
        """Test load_by_id returns None when not found."""
        storage = SqliteTextStorage(tmp_path)
        loaded = storage.load_by_id(999, nuts3_id=116, year=2024)
        assert loaded is None
        storage.close()


class TestUnknownNuts3:
    """Tests for unknown NUTS3 partitioning."""

    def test_save_unknown_nuts3(self, tmp_path: Path) -> None:
        """Test that None nuts3_id uses _unknown directory."""
        storage = SqliteTextStorage(tmp_path)
        pending = make_pending(nuts3_id=None)
        text = "Text from unknown region"

        storage.save(pending, text)
        loaded = storage.load(pending)
        assert loaded == text

        # Verify file is in _unknown directory
        db_path = tmp_path / "_unknown" / "2024.sqlite"
        assert db_path.exists()
        storage.close()

    def test_save_no_date(self, tmp_path: Path) -> None:
        """Test that None published_at uses _nodate."""
        storage = SqliteTextStorage(tmp_path)
        pending = make_pending(published_at=None)
        text = "Text with no date"

        storage.save(pending, text)
        loaded = storage.load(pending)
        assert loaded == text

        # Verify file path
        db_path = tmp_path / "116" / "_nodate.sqlite"
        assert db_path.exists()
        storage.close()


class TestDirectoryStructure:
    """Tests for correct file path generation."""

    def test_correct_file_path(self, tmp_path: Path) -> None:
        """Test SQLite files are created in the correct directory."""
        storage = SqliteTextStorage(tmp_path)

        pending1 = make_pending(attachment_id=1, nuts3_id=116, published_at=date(2024, 3, 1))
        pending2 = make_pending(attachment_id=2, nuts3_id=120, published_at=date(2023, 7, 15))

        storage.save(pending1, "text 1")
        storage.save(pending2, "text 2")

        assert (tmp_path / "116" / "2024.sqlite").exists()
        assert (tmp_path / "120" / "2023.sqlite").exists()
        storage.close()

    def test_multiple_years_same_region(self, tmp_path: Path) -> None:
        """Test multiple year files in same region directory."""
        storage = SqliteTextStorage(tmp_path)

        p2023 = make_pending(attachment_id=1, nuts3_id=116, published_at=date(2023, 1, 1))
        p2024 = make_pending(attachment_id=2, nuts3_id=116, published_at=date(2024, 1, 1))

        storage.save(p2023, "2023 text")
        storage.save(p2024, "2024 text")

        assert (tmp_path / "116" / "2023.sqlite").exists()
        assert (tmp_path / "116" / "2024.sqlite").exists()
        assert storage.load(p2023) == "2023 text"
        assert storage.load(p2024) == "2024 text"
        storage.close()


class TestDelete:
    """Tests for text deletion."""

    def test_delete_existing(self, tmp_path: Path) -> None:
        """Test deleting an existing text."""
        storage = SqliteTextStorage(tmp_path)
        pending = make_pending()
        storage.save(pending, "text to delete")

        result = storage.delete(pending)
        assert result is True
        assert storage.load(pending) is None
        storage.close()

    def test_delete_nonexistent(self, tmp_path: Path) -> None:
        """Test deleting a non-existent text returns False."""
        storage = SqliteTextStorage(tmp_path)
        pending = make_pending(attachment_id=999)

        result = storage.delete(pending)
        assert result is False
        storage.close()

    def test_delete_nonexistent_db(self, tmp_path: Path) -> None:
        """Test deleting when SQLite file doesn't exist returns False."""
        storage = SqliteTextStorage(tmp_path)
        pending = make_pending(nuts3_id=999)

        result = storage.delete(pending)
        assert result is False
        storage.close()


class TestExists:
    """Tests for existence checks."""

    def test_exists_true(self, tmp_path: Path) -> None:
        """Test exists returns True for stored text."""
        storage = SqliteTextStorage(tmp_path)
        pending = make_pending()
        storage.save(pending, "some text")

        assert storage.exists(pending) is True
        storage.close()

    def test_exists_false(self, tmp_path: Path) -> None:
        """Test exists returns False for missing text."""
        storage = SqliteTextStorage(tmp_path)
        pending = make_pending(attachment_id=999)

        assert storage.exists(pending) is False
        storage.close()

    def test_exists_false_no_db(self, tmp_path: Path) -> None:
        """Test exists returns False when db file doesn't exist."""
        storage = SqliteTextStorage(tmp_path)
        pending = make_pending(nuts3_id=999)

        assert storage.exists(pending) is False
        storage.close()


class TestDictionaryTraining:
    """Tests for automatic dictionary training."""

    def test_no_dictionary_below_threshold(self, tmp_path: Path) -> None:
        """Test no dictionary is trained below threshold."""
        storage = SqliteTextStorage(tmp_path)

        for i in range(DICT_TRAINING_THRESHOLD - 1):
            p = make_pending(attachment_id=i)
            storage.save(p, f"Sample text number {i} about municipalities")

        # Check no dictionary was created
        ref = storage._compute_ref(make_pending())
        conn = storage._get_connection(ref)
        row = conn.execute("SELECT COUNT(*) FROM dictionaries").fetchone()
        assert row[0] == 0
        storage.close()

    def test_dictionary_trained_at_threshold(self, tmp_path: Path) -> None:
        """Test dictionary is trained when threshold is reached."""
        storage = SqliteTextStorage(tmp_path)

        # Insert enough samples to trigger training
        for i in range(DICT_TRAINING_THRESHOLD):
            p = make_pending(attachment_id=i)
            # Use longer, more realistic text to ensure training succeeds
            storage.save(
                p,
                f"Rozhodnutí č. {i}/2024 o povolení stavby na pozemku "
                f"parc. č. {1000 + i} v katastrálním území Veveří, "
                f"obec Brno, okres Brno-město. Na základě žádosti "
                f"stavebníka ze dne {i}.1.2024 se povoluje stavba "
                f"rodinného domu na pozemku v ulici Kounicova {i}.",
            )

        # Check dictionary was created
        ref = storage._compute_ref(make_pending())
        conn = storage._get_connection(ref)
        row = conn.execute("SELECT COUNT(*) FROM dictionaries").fetchone()
        assert row[0] == 1

        # Verify dictionary has reasonable size
        dict_row = conn.execute(
            "SELECT LENGTH(dict_data), sample_count FROM dictionaries"
        ).fetchone()
        assert dict_row[0] > 0  # has data
        assert dict_row[1] == DICT_TRAINING_THRESHOLD  # sample count matches
        storage.close()


class TestCompressionWithDictionary:
    """Tests for dictionary-compressed text."""

    def test_text_loads_correctly_with_dict(self, tmp_path: Path) -> None:
        """Test that text compressed with dict decompresses correctly."""
        storage = SqliteTextStorage(tmp_path)

        # Fill to trigger dictionary training
        for i in range(DICT_TRAINING_THRESHOLD):
            p = make_pending(attachment_id=i)
            storage.save(
                p,
                f"Rozhodnutí č. {i}/2024 o povolení stavby na pozemku "
                f"parc. č. {1000 + i} v katastrálním území Veveří.",
            )

        # Now save a new text (should use dictionary)
        new_pending = make_pending(attachment_id=DICT_TRAINING_THRESHOLD + 1)
        new_text = "Nové rozhodnutí o povolení stavby na pozemku parc. č. 9999"
        storage.save(new_pending, new_text)

        loaded = storage.load(new_pending)
        assert loaded == new_text

        # Verify it used the dictionary
        ref = storage._compute_ref(new_pending)
        conn = storage._get_connection(ref)
        row = conn.execute(
            "SELECT dict_id FROM texts WHERE attachment_id = ?",
            (new_pending.id,),
        ).fetchone()
        assert row[0] != NO_DICT_ID
        storage.close()


class TestMixedDictAndPlain:
    """Tests for files with both dict-compressed and plain texts."""

    def test_mixed_dict_and_plain_loads(self, tmp_path: Path) -> None:
        """Test that texts with and without dict in same file both load."""
        storage = SqliteTextStorage(tmp_path)

        # Save texts before dictionary (dict_id=0)
        early_texts = {}
        for i in range(DICT_TRAINING_THRESHOLD):
            p = make_pending(attachment_id=i)
            text = (
                f"Stavební úřad vydává rozhodnutí č.j. SÚ/{i}/2024 "
                f"o umístění stavby rodinného domu na pozemku p.č. {1000 + i}."
            )
            early_texts[i] = text
            storage.save(p, text)

        # Save text after dictionary (dict_id > 0)
        late_pending = make_pending(attachment_id=DICT_TRAINING_THRESHOLD + 1)
        late_text = "Pozdní rozhodnutí o povolení stavby č. 999/2024"
        storage.save(late_pending, late_text)

        # All texts should still load correctly
        for i in range(min(5, DICT_TRAINING_THRESHOLD)):
            p = make_pending(attachment_id=i)
            loaded = storage.load(p)
            assert loaded == early_texts[i], f"Failed for attachment {i}"

        loaded_late = storage.load(late_pending)
        assert loaded_late == late_text
        storage.close()


class TestRecompressWithDictionary:
    """Tests for re-compression with dictionary."""

    def test_recompress(self, tmp_path: Path) -> None:
        """Test re-compressing old texts with new dictionary."""
        storage = SqliteTextStorage(tmp_path)

        # Save texts to trigger dictionary training
        for i in range(DICT_TRAINING_THRESHOLD):
            p = make_pending(attachment_id=i)
            storage.save(
                p,
                f"Rozhodnutí č. {i}/2024 o povolení stavby na pozemku "
                f"parc. č. {1000 + i} v katastrálním území Veveří.",
            )

        ref = storage._compute_ref(make_pending())

        # Re-compress old texts
        recompressed = storage.recompress_with_dictionary(ref)
        assert recompressed == DICT_TRAINING_THRESHOLD

        # Verify texts still load correctly
        for i in range(5):
            p = make_pending(attachment_id=i)
            loaded = storage.load(p)
            assert loaded is not None
            assert f"Rozhodnutí č. {i}/2024" in loaded

        # Verify all texts now use dictionary
        conn = storage._get_connection(ref)
        row = conn.execute("SELECT COUNT(*) FROM texts WHERE dict_id = ?", (NO_DICT_ID,)).fetchone()
        assert row[0] == 0
        storage.close()


class TestStats:
    """Tests for aggregated statistics."""

    def test_stats_empty(self, tmp_path: Path) -> None:
        """Test stats on empty storage."""
        storage = SqliteTextStorage(tmp_path)
        stats = storage.get_stats()

        assert stats["total_texts"] == 0
        assert stats["total_original_bytes"] == 0
        assert stats["total_compressed_bytes"] == 0
        assert stats["compression_ratio"] == 0.0
        assert stats["num_files"] == 0
        assert stats["num_dictionaries"] == 0
        storage.close()

    def test_stats_with_data(self, tmp_path: Path) -> None:
        """Test stats with saved data."""
        storage = SqliteTextStorage(tmp_path)

        for i in range(10):
            p = make_pending(attachment_id=i, nuts3_id=116, published_at=date(2024, 1, 1))
            storage.save(p, f"Sample text number {i} for stats testing")

        stats = storage.get_stats()
        assert stats["total_texts"] == 10
        assert stats["total_original_bytes"] > 0
        assert stats["total_compressed_bytes"] > 0
        assert stats["compression_ratio"] > 0
        assert stats["num_files"] == 1
        assert stats["num_dictionaries"] == 0
        storage.close()

    def test_stats_multiple_files(self, tmp_path: Path) -> None:
        """Test stats across multiple SQLite files."""
        storage = SqliteTextStorage(tmp_path)

        p1 = make_pending(attachment_id=1, nuts3_id=116, published_at=date(2024, 1, 1))
        p2 = make_pending(attachment_id=2, nuts3_id=120, published_at=date(2023, 1, 1))

        storage.save(p1, "text in region 116")
        storage.save(p2, "text in region 120")

        stats = storage.get_stats()
        assert stats["total_texts"] == 2
        assert stats["num_files"] == 2
        storage.close()


class TestContextManager:
    """Tests for context manager support."""

    def test_context_manager(self, tmp_path: Path) -> None:
        """Test using storage as context manager."""
        with SqliteTextStorage(tmp_path) as storage:
            pending = make_pending()
            storage.save(pending, "context manager test")
            loaded = storage.load(pending)
            assert loaded == "context manager test"

        # After exit, connections should be closed
        assert len(storage._connections) == 0

    def test_context_manager_cleanup_on_exception(self, tmp_path: Path) -> None:
        """Test context manager cleans up on exception."""
        storage = SqliteTextStorage(tmp_path)
        try:
            with storage:
                pending = make_pending()
                storage.save(pending, "test")
                raise ValueError("test error")
        except ValueError:
            pass

        assert len(storage._connections) == 0


class TestConcurrentWrites:
    """Tests for concurrent write safety."""

    def test_sequential_writes_same_file(self, tmp_path: Path) -> None:
        """Test multiple writes to the same SQLite file."""
        storage = SqliteTextStorage(tmp_path)

        for i in range(50):
            p = make_pending(attachment_id=i)
            storage.save(p, f"Text number {i}")

        # Verify all texts are readable
        for i in range(50):
            p = make_pending(attachment_id=i)
            loaded = storage.load(p)
            assert loaded == f"Text number {i}"

        storage.close()

    def test_interleaved_writes_different_files(self, tmp_path: Path) -> None:
        """Test interleaved writes to different SQLite files."""
        storage = SqliteTextStorage(tmp_path)

        for i in range(20):
            # Alternate between two regions
            nuts3 = 116 if i % 2 == 0 else 120
            p = make_pending(attachment_id=i, nuts3_id=nuts3)
            storage.save(p, f"Text {i} in region {nuts3}")

        # Verify all readable
        for i in range(20):
            nuts3 = 116 if i % 2 == 0 else 120
            p = make_pending(attachment_id=i, nuts3_id=nuts3)
            loaded = storage.load(p)
            assert loaded == f"Text {i} in region {nuts3}"

        storage.close()


class TestSQLiteSchema:
    """Tests for SQLite schema correctness."""

    def test_schema_created(self, tmp_path: Path) -> None:
        """Test that tables are created correctly."""
        storage = SqliteTextStorage(tmp_path)
        pending = make_pending()
        storage.save(pending, "test")

        ref = storage._compute_ref(pending)
        conn = storage._get_connection(ref)

        # Check texts table exists and has correct columns
        cursor = conn.execute("PRAGMA table_info(texts)")
        columns = {row[1] for row in cursor.fetchall()}
        assert "attachment_id" in columns
        assert "data" in columns
        assert "dict_id" in columns
        assert "original_size" in columns
        assert "compressed_size" in columns
        assert "created_at" in columns

        # Check dictionaries table exists
        cursor = conn.execute("PRAGMA table_info(dictionaries)")
        columns = {row[1] for row in cursor.fetchall()}
        assert "id" in columns
        assert "dict_data" in columns
        assert "sample_count" in columns
        assert "created_at" in columns

        storage.close()

    def test_wal_mode_enabled(self, tmp_path: Path) -> None:
        """Test that WAL mode is enabled for better concurrency."""
        storage = SqliteTextStorage(tmp_path)
        pending = make_pending()
        storage.save(pending, "test")

        ref = storage._compute_ref(pending)
        conn = storage._get_connection(ref)
        row = conn.execute("PRAGMA journal_mode").fetchone()
        assert row[0] == "wal"
        storage.close()


class TestGlobalDictionary:
    """Tests for global dictionary training and usage."""

    def _generate_text(self, i: int) -> str:
        """Generate realistic Czech legal text for dictionary training."""
        return (
            f"Rozhodnutí č. {i}/2024 o povolení stavby na pozemku "
            f"parc. č. {1000 + i} v katastrálním území Veveří, "
            f"obec Brno, okres Brno-město. Na základě žádosti "
            f"stavebníka ze dne {i % 28 + 1}.{i % 12 + 1}.2024 se povoluje stavba "
            f"rodinného domu na pozemku v ulici Kounicova {i}. "
            f"Městský úřad rozhodl podle §115 stavebního zákona."
        )

    def test_global_dict_trained_across_files(self, tmp_path: Path) -> None:
        """Test global dict trains from samples across multiple files."""
        storage = SqliteTextStorage(tmp_path)

        # Spread texts across multiple regions so no single file hits threshold
        regions = [116, 120, 130, 140]
        text_id = 0
        per_region = GLOBAL_DICT_TRAINING_THRESHOLD // len(regions) + 1

        for region in regions:
            for _ in range(per_region):
                p = make_pending(
                    attachment_id=text_id, nuts3_id=region, published_at=date(2024, 1, 1)
                )
                storage.save(p, self._generate_text(text_id))
                text_id += 1

        # Global dict should exist now
        global_db = tmp_path / "_global_dict.sqlite"
        assert global_db.exists(), "Global dictionary DB should be created"

        # Verify it has a dictionary
        import sqlite3

        gconn = sqlite3.connect(str(global_db))
        row = gconn.execute("SELECT COUNT(*) FROM dictionaries").fetchone()
        gconn.close()
        assert row[0] == 1
        storage.close()

    def test_global_dict_used_for_compression(self, tmp_path: Path) -> None:
        """Test new texts use global dict when no per-file dict exists."""
        storage = SqliteTextStorage(tmp_path)

        # Train global dict
        regions = [116, 120, 130, 140]
        text_id = 0
        per_region = GLOBAL_DICT_TRAINING_THRESHOLD // len(regions) + 1

        for region in regions:
            for _ in range(per_region):
                p = make_pending(
                    attachment_id=text_id, nuts3_id=region, published_at=date(2024, 1, 1)
                )
                storage.save(p, self._generate_text(text_id))
                text_id += 1

        # Save a new text in a new region (no per-file dict)
        new_p = make_pending(attachment_id=9999, nuts3_id=999, published_at=date(2024, 1, 1))
        new_text = "Nové rozhodnutí o povolení stavby na pozemku v k.ú. Veveří"
        storage.save(new_p, new_text)

        # Should use global dict
        ref = storage._compute_ref(new_p)
        conn = storage._get_connection(ref)
        row = conn.execute("SELECT dict_id FROM texts WHERE attachment_id = ?", (9999,)).fetchone()
        assert row[0] == GLOBAL_DICT_ID

        # Text should round-trip correctly
        loaded = storage.load(new_p)
        assert loaded == new_text
        storage.close()

    def test_global_dict_improves_compression(self, tmp_path: Path) -> None:
        """Test that global dict gives better compression than plain zstd."""
        storage = SqliteTextStorage(tmp_path)

        # Save one text without global dict to measure plain compression
        p_plain = make_pending(attachment_id=1, nuts3_id=116, published_at=date(2024, 1, 1))
        plain_text = self._generate_text(1)
        plain_size = storage.save(p_plain, plain_text)

        # Now train global dict using multiple regions
        regions = [120, 130, 140, 150]
        text_id = 100
        per_region = GLOBAL_DICT_TRAINING_THRESHOLD // len(regions) + 1

        for region in regions:
            for _ in range(per_region):
                p = make_pending(
                    attachment_id=text_id, nuts3_id=region, published_at=date(2024, 1, 1)
                )
                storage.save(p, self._generate_text(text_id))
                text_id += 1

        # Save similar text with global dict in new region
        p_dict = make_pending(attachment_id=9999, nuts3_id=999, published_at=date(2024, 1, 1))
        dict_text = self._generate_text(9999)
        dict_size = storage.save(p_dict, dict_text)

        # Dictionary-compressed should be smaller
        assert dict_size < plain_size, (
            f"Dict-compressed ({dict_size}) should be smaller than plain ({plain_size})"
        )
        storage.close()

    def test_recompress_all_with_global_dict(self, tmp_path: Path) -> None:
        """Test recompress_all updates old plain texts with global dict."""
        storage = SqliteTextStorage(tmp_path)

        # Save texts across regions (plain, no dict)
        regions = [116, 120, 130, 140]
        text_id = 0
        per_region = GLOBAL_DICT_TRAINING_THRESHOLD // len(regions) + 1
        # Map (attachment_id, region) -> text for verification
        saved: list[tuple[int, int, str]] = []

        for region in regions:
            for _ in range(per_region):
                p = make_pending(
                    attachment_id=text_id, nuts3_id=region, published_at=date(2024, 1, 1)
                )
                t = self._generate_text(text_id)
                saved.append((text_id, region, t))
                storage.save(p, t)
                text_id += 1

        # Recompress all
        results = storage.recompress_all()
        total_recompressed = sum(results.values())
        assert total_recompressed > 0

        # All texts should still load correctly
        for aid, region, expected_text in saved[:10]:
            p = make_pending(attachment_id=aid, nuts3_id=region, published_at=date(2024, 1, 1))
            loaded = storage.load(p)
            assert loaded == expected_text, f"Text {aid} corrupted after recompress"

        storage.close()

    def test_train_global_dictionary_manual(self, tmp_path: Path) -> None:
        """Test manually calling train_global_dictionary."""
        storage = SqliteTextStorage(tmp_path)

        # Save enough texts
        for i in range(GLOBAL_DICT_TRAINING_THRESHOLD):
            p = make_pending(attachment_id=i, nuts3_id=116, published_at=date(2024, 1, 1))
            storage.save(p, self._generate_text(i))

        # Manually train
        result = storage.train_global_dictionary()
        assert result is True

        global_db = tmp_path / "_global_dict.sqlite"
        assert global_db.exists()
        storage.close()

    def test_no_global_dict_with_few_texts(self, tmp_path: Path) -> None:
        """Test global dict is not trained with too few texts."""
        storage = SqliteTextStorage(tmp_path)

        # Only a few texts across regions
        for i in range(5):
            p = make_pending(attachment_id=i, nuts3_id=116 + i, published_at=date(2024, 1, 1))
            storage.save(p, self._generate_text(i))

        global_db = tmp_path / "_global_dict.sqlite"
        assert not global_db.exists()
        storage.close()
