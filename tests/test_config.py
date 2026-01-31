"""Tests for config module."""

import os
from pathlib import Path
from unittest import mock

from ruian_import.config import (
    DatabaseConfig,
    DownloadConfig,
    get_data_dir,
    get_project_root,
)


class TestDatabaseConfig:
    """Tests for DatabaseConfig dataclass."""

    def test_default_values(self) -> None:
        """Test default configuration values."""
        config = DatabaseConfig()
        assert config.host == "localhost"
        assert config.port == 5432
        assert config.database == "ruian"
        assert config.user == "ruian"
        assert config.password == "ruian"

    def test_connection_string(self) -> None:
        """Test psycopg2 connection string generation."""
        config = DatabaseConfig(
            host="dbhost",
            port=5433,
            database="testdb",
            user="testuser",
            password="testpass",
        )
        expected = "host=dbhost port=5433 dbname=testdb user=testuser password=testpass"
        assert config.connection_string == expected

    def test_ogr_connection_string(self) -> None:
        """Test OGR PostgreSQL connection string generation."""
        config = DatabaseConfig(
            host="dbhost",
            port=5433,
            database="testdb",
            user="testuser",
            password="testpass",
        )
        expected = "PG:host=dbhost port=5433 dbname=testdb user=testuser password=testpass"
        assert config.ogr_connection_string == expected

    def test_environment_variables(self) -> None:
        """Test configuration from environment variables."""
        env_vars = {
            "RUIAN_DB_HOST": "envhost",
            "RUIAN_DB_PORT": "5434",
            "RUIAN_DB_NAME": "envdb",
            "RUIAN_DB_USER": "envuser",
            "RUIAN_DB_PASSWORD": "envpass",
        }
        with mock.patch.dict(os.environ, env_vars, clear=False):
            config = DatabaseConfig()
            assert config.host == "envhost"
            assert config.port == 5434
            assert config.database == "envdb"
            assert config.user == "envuser"
            assert config.password == "envpass"


class TestDownloadConfig:
    """Tests for DownloadConfig dataclass."""

    def test_default_values(self) -> None:
        """Test default configuration values."""
        config = DownloadConfig()
        assert "vdp.cuzk.gov.cz" in config.list_url
        assert "uzemniPrvky=ST" in config.list_url
        assert config.base_download_url == "https://vdp.cuzk.gov.cz/vymenny_format/soucasna"
        assert config.timeout == 300
        assert config.chunk_size == 8192

    def test_ob_list_url(self) -> None:
        """Test OB (municipality) list URL configuration."""
        config = DownloadConfig()
        assert "vdp.cuzk.gov.cz" in config.ob_list_url
        assert "uzemniPrvky=OB" in config.ob_list_url
        assert "upObecAPodrazene=true" in config.ob_list_url

    def test_max_concurrent_downloads(self) -> None:
        """Test max concurrent downloads configuration."""
        config = DownloadConfig()
        assert config.max_concurrent_downloads == 5

        config = DownloadConfig(max_concurrent_downloads=10)
        assert config.max_concurrent_downloads == 10

    def test_data_dir_default(self) -> None:
        """Test default data directory."""
        config = DownloadConfig()
        assert config.data_dir == Path("data")

    def test_custom_data_dir(self) -> None:
        """Test custom data directory."""
        custom_dir = Path("/tmp/custom_data")
        config = DownloadConfig(data_dir=custom_dir)
        assert config.data_dir == custom_dir


class TestHelperFunctions:
    """Tests for helper functions."""

    def test_get_project_root(self) -> None:
        """Test project root detection."""
        root = get_project_root()
        assert root.is_dir()
        assert (root / "src").is_dir()
        assert (root / "pyproject.toml").is_file()

    def test_get_data_dir(self) -> None:
        """Test data directory creation."""
        data_dir = get_data_dir()
        assert data_dir.is_dir()
        assert data_dir.name == "data"
