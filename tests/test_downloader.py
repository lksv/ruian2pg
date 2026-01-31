"""Tests for downloader module."""

from pathlib import Path
from unittest import mock

from ruian_import.config import DownloadConfig
from ruian_import.downloader import RuianDownloader


class TestRuianDownloaderPatterns:
    """Tests for file pattern matching."""

    def test_st_file_pattern(self) -> None:
        """Test ST file pattern matches correctly."""
        pattern = RuianDownloader.FILE_PATTERN
        assert pattern.search("20251231_ST_UKSH.xml.zip")
        assert pattern.search("/path/to/20251231_ST_UKSH.xml.zip")
        assert not pattern.search("20251231_OB_500011_UKSH.xml.zip")
        assert not pattern.search("random_file.zip")

    def test_ob_file_pattern(self) -> None:
        """Test OB file pattern matches correctly."""
        pattern = RuianDownloader.OB_FILE_PATTERN
        assert pattern.search("20251231_OB_500011_UKSH.xml.zip")
        assert pattern.search("/path/to/20251231_OB_123456_UKSH.xml.zip")
        assert not pattern.search("20251231_ST_UKSH.xml.zip")
        assert not pattern.search("random_file.zip")

    def test_ob_pattern_extracts_filename(self) -> None:
        """Test OB pattern extracts complete filename."""
        pattern = RuianDownloader.OB_FILE_PATTERN
        match = pattern.search("https://example.com/20251231_OB_500011_UKSH.xml.zip")
        assert match is not None
        assert match.group(1) == "20251231_OB_500011_UKSH.xml.zip"


class TestRuianDownloaderInit:
    """Tests for RuianDownloader initialization."""

    def test_default_config(self) -> None:
        """Test downloader with default config."""
        downloader = RuianDownloader()
        assert downloader.config is not None
        assert downloader.data_dir.is_dir()

    def test_custom_config(self) -> None:
        """Test downloader with custom config."""
        config = DownloadConfig(timeout=600)
        downloader = RuianDownloader(config)
        assert downloader.config.timeout == 600


class TestFetchFileList:
    """Tests for fetch_file_list method."""

    def test_fetch_file_list_parses_response(self) -> None:
        """Test parsing of file list response."""
        mock_response = """
        /path/20251231_ST_UKSH.xml.zip
        /path/20251230_ST_UKSH.xml.zip
        """
        with mock.patch("httpx.Client") as mock_client:
            mock_instance = mock_client.return_value.__enter__.return_value
            mock_instance.get.return_value.text = mock_response
            mock_instance.get.return_value.raise_for_status = mock.Mock()

            downloader = RuianDownloader()
            files = downloader.fetch_file_list()

            assert len(files) == 2
            assert all("_ST_UKSH.xml.zip" in f for f in files)

    def test_fetch_file_list_handles_empty_lines(self) -> None:
        """Test handling of empty lines in response."""
        mock_response = """
        /path/20251231_ST_UKSH.xml.zip

        /path/20251230_ST_UKSH.xml.zip

        """
        with mock.patch("httpx.Client") as mock_client:
            mock_instance = mock_client.return_value.__enter__.return_value
            mock_instance.get.return_value.text = mock_response
            mock_instance.get.return_value.raise_for_status = mock.Mock()

            downloader = RuianDownloader()
            files = downloader.fetch_file_list()

            assert len(files) == 2


class TestFetchObFileList:
    """Tests for fetch_ob_file_list method."""

    def test_fetch_ob_file_list_parses_response(self) -> None:
        """Test parsing of OB file list response."""
        mock_response = """
        /path/20251231_OB_500011_UKSH.xml.zip
        /path/20251231_OB_500038_UKSH.xml.zip
        /path/20251231_OB_500054_UKSH.xml.zip
        """
        with mock.patch("httpx.Client") as mock_client:
            mock_instance = mock_client.return_value.__enter__.return_value
            mock_instance.get.return_value.text = mock_response
            mock_instance.get.return_value.raise_for_status = mock.Mock()

            downloader = RuianDownloader()
            files = downloader.fetch_ob_file_list()

            assert len(files) == 3
            assert all("_OB_" in f for f in files)
            assert all("_UKSH.xml.zip" in f for f in files)

    def test_fetch_ob_file_list_uses_correct_url(self) -> None:
        """Test that OB file list uses correct URL."""
        with mock.patch("httpx.Client") as mock_client:
            mock_instance = mock_client.return_value.__enter__.return_value
            mock_instance.get.return_value.text = ""
            mock_instance.get.return_value.raise_for_status = mock.Mock()

            config = DownloadConfig()
            downloader = RuianDownloader(config)
            downloader.fetch_ob_file_list()

            mock_instance.get.assert_called_once_with(config.ob_list_url)


class TestListLocalFiles:
    """Tests for list_local_files method."""

    def test_list_local_files_st_type(self, tmp_path: Path) -> None:
        """Test listing ST files."""
        # Create test files
        (tmp_path / "20251231_ST_UKSH.xml.zip").touch()
        (tmp_path / "20251231_OB_500011_UKSH.xml.zip").touch()
        (tmp_path / "other_file.txt").touch()

        config = DownloadConfig(data_dir=tmp_path)
        downloader = RuianDownloader(config)
        downloader.data_dir = tmp_path

        files = downloader.list_local_files(file_type="ST")
        assert len(files) == 1
        assert files[0].name == "20251231_ST_UKSH.xml.zip"

    def test_list_local_files_ob_type(self, tmp_path: Path) -> None:
        """Test listing OB files."""
        # Create test files
        (tmp_path / "20251231_ST_UKSH.xml.zip").touch()
        (tmp_path / "20251231_OB_500011_UKSH.xml.zip").touch()
        (tmp_path / "20251231_OB_500038_UKSH.xml.zip").touch()

        config = DownloadConfig(data_dir=tmp_path)
        downloader = RuianDownloader(config)
        downloader.data_dir = tmp_path

        files = downloader.list_local_files(file_type="OB")
        assert len(files) == 2
        assert all("_OB_" in f.name for f in files)

    def test_list_local_files_all_type(self, tmp_path: Path) -> None:
        """Test listing all VFR files."""
        # Create test files
        (tmp_path / "20251231_ST_UKSH.xml.zip").touch()
        (tmp_path / "20251231_OB_500011_UKSH.xml.zip").touch()
        (tmp_path / "other_file.txt").touch()

        config = DownloadConfig(data_dir=tmp_path)
        downloader = RuianDownloader(config)
        downloader.data_dir = tmp_path

        files = downloader.list_local_files(file_type="all")
        assert len(files) == 2

    def test_list_local_files_sorted(self, tmp_path: Path) -> None:
        """Test that files are sorted by name."""
        # Create test files out of order
        (tmp_path / "20251231_OB_500038_UKSH.xml.zip").touch()
        (tmp_path / "20251231_OB_500011_UKSH.xml.zip").touch()
        (tmp_path / "20251230_OB_500011_UKSH.xml.zip").touch()

        config = DownloadConfig(data_dir=tmp_path)
        downloader = RuianDownloader(config)
        downloader.data_dir = tmp_path

        files = downloader.list_local_files(file_type="OB")
        names = [f.name for f in files]
        assert names == sorted(names)


class TestDownloadFile:
    """Tests for download_file method."""

    def test_download_file_skips_existing(self, tmp_path: Path) -> None:
        """Test that existing files are skipped."""
        existing_file = tmp_path / "20251231_ST_UKSH.xml.zip"
        existing_file.write_text("existing content")

        config = DownloadConfig(data_dir=tmp_path)
        downloader = RuianDownloader(config)
        downloader.data_dir = tmp_path

        url = "https://example.com/20251231_ST_UKSH.xml.zip"
        result = downloader.download_file(url, force=False)

        assert result is None  # Skipped

    def test_download_file_force_redownload(self, tmp_path: Path) -> None:
        """Test force re-download of existing file."""
        existing_file = tmp_path / "20251231_ST_UKSH.xml.zip"
        existing_file.write_text("existing content")

        config = DownloadConfig(data_dir=tmp_path)
        downloader = RuianDownloader(config)
        downloader.data_dir = tmp_path

        with mock.patch("httpx.Client") as mock_client:
            mock_instance = mock_client.return_value.__enter__.return_value
            mock_stream = mock.MagicMock()
            mock_stream.__enter__.return_value.headers = {"content-length": "100"}
            mock_stream.__enter__.return_value.iter_bytes.return_value = [b"new content"]
            mock_stream.__enter__.return_value.raise_for_status = mock.Mock()
            mock_instance.stream.return_value = mock_stream

            url = "https://example.com/20251231_ST_UKSH.xml.zip"
            result = downloader.download_file(url, force=True)

            assert result is not None
            assert result.exists()


class TestDownloadAllMunicipalities:
    """Tests for download_all_municipalities method."""

    def test_download_all_municipalities_empty_list(self) -> None:
        """Test handling of empty file list."""
        with mock.patch("httpx.Client") as mock_client:
            mock_instance = mock_client.return_value.__enter__.return_value
            mock_instance.get.return_value.text = ""
            mock_instance.get.return_value.raise_for_status = mock.Mock()

            downloader = RuianDownloader()
            downloaded, failed = downloader.download_all_municipalities()

            assert downloaded == []
            assert failed == []

    def test_download_all_municipalities_uses_workers(self, tmp_path: Path) -> None:
        """Test that workers parameter is respected."""
        mock_response = """
        /path/20251231_OB_500011_UKSH.xml.zip
        /path/20251231_OB_500038_UKSH.xml.zip
        """

        config = DownloadConfig(data_dir=tmp_path, max_concurrent_downloads=3)
        downloader = RuianDownloader(config)
        downloader.data_dir = tmp_path

        with mock.patch("httpx.Client") as mock_client:
            mock_instance = mock_client.return_value.__enter__.return_value
            mock_instance.get.return_value.text = mock_response
            mock_instance.get.return_value.raise_for_status = mock.Mock()

            # Mock ThreadPoolExecutor and as_completed together
            with (
                mock.patch("ruian_import.downloader.ThreadPoolExecutor") as mock_executor,
                mock.patch("ruian_import.downloader.as_completed") as mock_as_completed,
            ):
                mock_executor_instance = mock.MagicMock()
                mock_executor.return_value.__enter__.return_value = mock_executor_instance

                # Create mock futures that return results
                mock_future1 = mock.MagicMock()
                mock_future1.result.return_value = ("url1", None, None)
                mock_future2 = mock.MagicMock()
                mock_future2.result.return_value = ("url2", None, None)

                mock_executor_instance.submit.side_effect = [mock_future1, mock_future2]
                mock_as_completed.return_value = iter([mock_future1, mock_future2])

                downloader.download_all_municipalities(workers=7)

                mock_executor.assert_called_once_with(max_workers=7)

    def test_download_all_municipalities_progress_callback(self, tmp_path: Path) -> None:
        """Test progress callback is called."""
        mock_response = "/path/20251231_OB_500011_UKSH.xml.zip"

        config = DownloadConfig(data_dir=tmp_path)
        downloader = RuianDownloader(config)
        downloader.data_dir = tmp_path

        progress_calls: list[tuple[int, int, str]] = []

        def progress_callback(downloaded: int, total: int, filename: str) -> None:
            progress_calls.append((downloaded, total, filename))

        with mock.patch("httpx.Client") as mock_client:
            mock_instance = mock_client.return_value.__enter__.return_value
            mock_instance.get.return_value.text = mock_response
            mock_instance.get.return_value.raise_for_status = mock.Mock()

            with (
                mock.patch("ruian_import.downloader.ThreadPoolExecutor") as mock_executor,
                mock.patch("ruian_import.downloader.as_completed") as mock_as_completed,
            ):
                mock_executor_instance = mock.MagicMock()
                mock_executor.return_value.__enter__.return_value = mock_executor_instance

                # Create mock future
                mock_future = mock.MagicMock()
                mock_future.result.return_value = (
                    "https://example.com/20251231_OB_500011_UKSH.xml.zip",
                    tmp_path / "20251231_OB_500011_UKSH.xml.zip",
                    None,
                )

                mock_executor_instance.submit.return_value = mock_future
                mock_as_completed.return_value = iter([mock_future])

                downloader.download_all_municipalities(progress_callback=progress_callback)

                assert len(progress_calls) == 1
                assert progress_calls[0][0] == 1  # completed = 1
                assert progress_calls[0][1] == 1  # total = 1
