"""Tests for importer module."""

from pathlib import Path
from unittest import mock

from ruian_import.config import DatabaseConfig
from ruian_import.importer import (
    EXPECTED_TABLES,
    EXPECTED_TABLES_OB,
    EXPECTED_TABLES_ST,
    RuianImporter,
)


def setup_mock_cursor(mock_connect: mock.MagicMock, mock_cursor: mock.MagicMock) -> None:
    """Helper to set up mock cursor for psycopg2 connection."""
    mock_conn = mock_connect.return_value.__enter__.return_value
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor


class TestExpectedTables:
    """Tests for expected table constants."""

    def test_expected_tables_st(self) -> None:
        """Test ST expected tables."""
        assert "staty" in EXPECTED_TABLES_ST
        assert "vusc" in EXPECTED_TABLES_ST
        assert "okresy" in EXPECTED_TABLES_ST
        assert "orp" in EXPECTED_TABLES_ST
        assert "pou" in EXPECTED_TABLES_ST

    def test_expected_tables_ob(self) -> None:
        """Test OB expected tables."""
        assert "obce" in EXPECTED_TABLES_OB
        assert "katastralniuzemi" in EXPECTED_TABLES_OB
        assert "adresnimista" in EXPECTED_TABLES_OB
        assert "stavebniobjekty" in EXPECTED_TABLES_OB
        assert "parcely" in EXPECTED_TABLES_OB
        assert "ulice" in EXPECTED_TABLES_OB

    def test_expected_tables_combined(self) -> None:
        """Test combined expected tables."""
        for table in EXPECTED_TABLES_ST:
            assert table in EXPECTED_TABLES
        for table in EXPECTED_TABLES_OB:
            assert table in EXPECTED_TABLES


class TestRuianImporterInit:
    """Tests for RuianImporter initialization."""

    def test_default_config(self) -> None:
        """Test importer with default config."""
        importer = RuianImporter()
        assert importer.db_config is not None
        assert importer.db_config.host == "localhost"

    def test_custom_config(self) -> None:
        """Test importer with custom config."""
        config = DatabaseConfig(host="customhost", port=5433)
        importer = RuianImporter(config)
        assert importer.db_config.host == "customhost"
        assert importer.db_config.port == 5433


class TestListLocalObFiles:
    """Tests for list_local_ob_files method."""

    def test_list_local_ob_files(self, tmp_path: Path) -> None:
        """Test listing local OB files."""
        # Create test files
        (tmp_path / "20251231_OB_500011_UKSH.xml.zip").touch()
        (tmp_path / "20251231_OB_500038_UKSH.xml.zip").touch()
        (tmp_path / "20251231_ST_UKSH.xml.zip").touch()

        importer = RuianImporter()
        importer.data_dir = tmp_path

        files = importer.list_local_ob_files()
        assert len(files) == 2
        assert all("_OB_" in f.name for f in files)

    def test_list_local_ob_files_sorted(self, tmp_path: Path) -> None:
        """Test that OB files are sorted."""
        (tmp_path / "20251231_OB_500038_UKSH.xml.zip").touch()
        (tmp_path / "20251231_OB_500011_UKSH.xml.zip").touch()
        (tmp_path / "20251230_OB_500011_UKSH.xml.zip").touch()

        importer = RuianImporter()
        importer.data_dir = tmp_path

        files = importer.list_local_ob_files()
        names = [f.name for f in files]
        assert names == sorted(names)

    def test_list_local_ob_files_empty(self, tmp_path: Path) -> None:
        """Test empty directory."""
        importer = RuianImporter()
        importer.data_dir = tmp_path

        files = importer.list_local_ob_files()
        assert files == []


class TestGetImportedObFiles:
    """Tests for get_imported_ob_files method."""

    def test_get_imported_ob_files_no_table(self) -> None:
        """Test when tracking table doesn't exist."""
        with mock.patch("psycopg2.connect") as mock_connect:
            mock_cursor = mock.MagicMock()
            mock_cursor.fetchone.return_value = (False,)  # Table doesn't exist
            setup_mock_cursor(mock_connect, mock_cursor)

            importer = RuianImporter()
            result = importer.get_imported_ob_files()

            assert result == set()

    def test_get_imported_ob_files_with_data(self) -> None:
        """Test retrieving imported files."""
        with mock.patch("psycopg2.connect") as mock_connect:
            mock_cursor = mock.MagicMock()
            # First call: table exists
            mock_cursor.fetchone.return_value = (True,)
            # Second call: list of imported files
            mock_cursor.fetchall.return_value = [
                ("20251231_OB_500011_UKSH.xml.zip",),
                ("20251231_OB_500038_UKSH.xml.zip",),
            ]
            setup_mock_cursor(mock_connect, mock_cursor)

            importer = RuianImporter()
            result = importer.get_imported_ob_files()

            assert len(result) == 2
            assert "20251231_OB_500011_UKSH.xml.zip" in result
            assert "20251231_OB_500038_UKSH.xml.zip" in result

    def test_get_imported_ob_files_connection_error(self) -> None:
        """Test handling of database connection error."""
        import psycopg2

        with mock.patch("psycopg2.connect") as mock_connect:
            mock_connect.side_effect = psycopg2.Error("Connection failed")

            importer = RuianImporter()
            result = importer.get_imported_ob_files()

            assert result == set()


class TestEnsureImportLogTable:
    """Tests for _ensure_import_log_table method."""

    def test_ensure_import_log_table_creates_table(self) -> None:
        """Test that table creation SQL is executed."""
        with mock.patch("psycopg2.connect") as mock_connect:
            mock_cursor = mock.MagicMock()
            setup_mock_cursor(mock_connect, mock_cursor)
            mock_conn = mock_connect.return_value.__enter__.return_value

            importer = RuianImporter()
            importer._ensure_import_log_table()

            # Check that CREATE TABLE was called
            mock_cursor.execute.assert_called()
            call_args = mock_cursor.execute.call_args[0][0]
            assert "CREATE TABLE IF NOT EXISTS ruian_import_log" in call_args
            mock_conn.commit.assert_called_once()


class TestLogImport:
    """Tests for _log_import method."""

    def test_log_import_success(self) -> None:
        """Test logging successful import."""
        with mock.patch("psycopg2.connect") as mock_connect:
            mock_cursor = mock.MagicMock()
            setup_mock_cursor(mock_connect, mock_cursor)

            importer = RuianImporter()
            importer._log_import("test_file.xml.zip", "success")

            mock_cursor.execute.assert_called()
            call_args = mock_cursor.execute.call_args
            assert "INSERT INTO ruian_import_log" in call_args[0][0]
            assert call_args[0][1] == ("test_file.xml.zip", "success", None)

    def test_log_import_with_error(self) -> None:
        """Test logging failed import with error message."""
        with mock.patch("psycopg2.connect") as mock_connect:
            mock_cursor = mock.MagicMock()
            setup_mock_cursor(mock_connect, mock_cursor)

            importer = RuianImporter()
            importer._log_import("test_file.xml.zip", "failed", "Connection timeout")

            call_args = mock_cursor.execute.call_args
            assert call_args[0][1] == ("test_file.xml.zip", "failed", "Connection timeout")


class TestImportAllMunicipalities:
    """Tests for import_all_municipalities method."""

    def test_import_all_municipalities_no_files(self, tmp_path: Path) -> None:
        """Test with no OB files."""
        importer = RuianImporter()
        importer.data_dir = tmp_path

        success, skipped, failed = importer.import_all_municipalities()

        assert success == 0
        assert skipped == 0
        assert failed == 0

    def test_import_all_municipalities_resume_skips_imported(self, tmp_path: Path) -> None:
        """Test resume mode skips already imported files."""
        # Create test files
        (tmp_path / "20251231_OB_500011_UKSH.xml.zip").touch()
        (tmp_path / "20251231_OB_500038_UKSH.xml.zip").touch()

        with mock.patch("psycopg2.connect") as mock_connect:
            mock_cursor = mock.MagicMock()
            # Table exists
            mock_cursor.fetchone.return_value = (True,)
            # One file already imported
            mock_cursor.fetchall.return_value = [
                ("20251231_OB_500011_UKSH.xml.zip",),
            ]
            setup_mock_cursor(mock_connect, mock_cursor)

            importer = RuianImporter()
            importer.data_dir = tmp_path

            # Mock import_file to succeed
            with mock.patch.object(importer, "import_file", return_value=True):
                success, skipped, failed = importer.import_all_municipalities(resume=True)

            # One file should be skipped, one imported
            assert skipped == 1
            assert success == 1
            assert failed == 0

    def test_import_all_municipalities_handles_failure(self, tmp_path: Path) -> None:
        """Test handling of import failures."""
        (tmp_path / "20251231_OB_500011_UKSH.xml.zip").touch()

        with mock.patch("psycopg2.connect") as mock_connect:
            mock_cursor = mock.MagicMock()
            mock_cursor.fetchone.return_value = (False,)  # No tracking table
            setup_mock_cursor(mock_connect, mock_cursor)

            importer = RuianImporter()
            importer.data_dir = tmp_path

            # Mock import_file to fail
            with mock.patch.object(importer, "import_file", return_value=False):
                success, skipped, failed = importer.import_all_municipalities()

            assert success == 0
            assert skipped == 0
            assert failed == 1


class TestImportFile:
    """Tests for import_file method."""

    def test_import_file_not_found(self, tmp_path: Path) -> None:
        """Test import of non-existent file."""
        importer = RuianImporter()
        result = importer.import_file(tmp_path / "nonexistent.xml.zip")
        assert result is False

    def test_import_file_ogr2ogr_not_found(self, tmp_path: Path) -> None:
        """Test handling of missing ogr2ogr."""
        test_file = tmp_path / "20251231_ST_UKSH.xml.zip"
        test_file.touch()

        with mock.patch("subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError("ogr2ogr not found")

            importer = RuianImporter()
            result = importer.import_file(test_file)

            assert result is False

    def test_import_file_builds_correct_command(self, tmp_path: Path) -> None:
        """Test that ogr2ogr command is built correctly."""
        test_file = tmp_path / "20251231_ST_UKSH.xml.zip"
        test_file.touch()

        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0

            config = DatabaseConfig(host="testhost", database="testdb")
            importer = RuianImporter(config)
            importer.import_file(test_file, overwrite=True)

            call_args = mock_run.call_args
            cmd = call_args[0][0]

            assert cmd[0] == "ogr2ogr"
            assert "-f" in cmd
            assert "PostgreSQL" in cmd
            assert "-overwrite" in cmd
            assert "EPSG:5514" in cmd

    def test_import_file_append_mode(self, tmp_path: Path) -> None:
        """Test append mode flag."""
        test_file = tmp_path / "20251231_ST_UKSH.xml.zip"
        test_file.touch()

        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0

            importer = RuianImporter()
            importer.import_file(test_file, overwrite=False)

            cmd = mock_run.call_args[0][0]
            assert "-append" in cmd
            assert "-overwrite" not in cmd
