"""Tests for eDesky sync functionality."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Add scripts to path for testing
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from notice_boards.models import NoticeBoard
from notice_boards.scrapers.edesky import EdeskyDashboard


class TestExtractEdeskyIdFromUrl:
    """Tests for extract_edesky_id_from_url function."""

    def test_extract_valid_url(self) -> None:
        """Test extracting ID from valid eDesky URL."""
        from sync_edesky_boards import extract_edesky_id_from_url

        assert extract_edesky_id_from_url("https://edesky.cz/desky/123") == 123
        assert extract_edesky_id_from_url("https://edesky.cz/desky/1") == 1
        assert extract_edesky_id_from_url("http://edesky.cz/desky/99999") == 99999

    def test_extract_invalid_url(self) -> None:
        """Test extracting ID from invalid URL returns None."""
        from sync_edesky_boards import extract_edesky_id_from_url

        assert extract_edesky_id_from_url("https://edesky.cz/dokument/123") is None
        assert extract_edesky_id_from_url("invalid-url") is None
        assert extract_edesky_id_from_url("") is None


class TestSyncStats:
    """Tests for SyncStats dataclass."""

    def test_total_matched(self) -> None:
        """Test total_matched calculation."""
        from sync_edesky_boards import SyncStats

        stats = SyncStats(
            matched_by_edesky_id=10,
            matched_by_edesky_url=5,
            matched_by_ico=3,
            matched_by_name=2,
        )
        assert stats.total_matched == 20

    def test_total_processed(self) -> None:
        """Test total_processed calculation."""
        from sync_edesky_boards import SyncStats

        stats = SyncStats(
            matched_by_edesky_id=10,
            matched_by_edesky_url=5,
            matched_by_ico=3,
            matched_by_name=2,
            created_new=50,
            skipped_ambiguous=2,
            errors=1,
        )
        assert stats.total_processed == 73  # 20 matched + 50 new + 2 skipped + 1 error


class TestMatchAndUpdateBoard:
    """Tests for match_and_update_board function."""

    @pytest.fixture
    def mock_repo(self) -> MagicMock:
        """Create mock repository."""
        return MagicMock()

    @pytest.fixture
    def sample_dashboard(self) -> EdeskyDashboard:
        """Create sample dashboard for testing."""
        return EdeskyDashboard(
            edesky_id=123,
            name="Test Municipality",
            category="obec",
            ico="12345678",
            nuts3_id=1,
            nuts3_name="Region",
            nuts4_id=10,
            nuts4_name="District",
            latitude=50.0,
            longitude=14.0,
        )

    def test_match_by_edesky_id(
        self, mock_repo: MagicMock, sample_dashboard: EdeskyDashboard
    ) -> None:
        """Test matching by existing edesky_id."""
        from sync_edesky_boards import SyncStats, match_and_update_board

        mock_repo.get_notice_board_by_edesky_id.return_value = NoticeBoard(
            id=1, edesky_id=123, name="Test"
        )

        stats = SyncStats()
        result = match_and_update_board(mock_repo, sample_dashboard, stats)

        assert result is True
        assert stats.matched_by_edesky_id == 1
        mock_repo.get_notice_board_by_edesky_id.assert_called_once_with(123)

    def test_match_by_ico_single_match(
        self, mock_repo: MagicMock, sample_dashboard: EdeskyDashboard
    ) -> None:
        """Test matching by ICO with single unmatched board."""
        from sync_edesky_boards import SyncStats, match_and_update_board

        mock_repo.get_notice_board_by_edesky_id.return_value = None
        mock_repo.get_notice_boards_by_ico.return_value = [
            NoticeBoard(id=1, ico="12345678", name="Test", edesky_id=None)
        ]

        stats = SyncStats()
        result = match_and_update_board(mock_repo, sample_dashboard, stats)

        assert result is True
        assert stats.matched_by_ico == 1
        mock_repo.update_notice_board_edesky_fields.assert_called_once()

    def test_match_by_ico_multiple_matches_disambiguate_by_name(
        self, mock_repo: MagicMock, sample_dashboard: EdeskyDashboard
    ) -> None:
        """Test matching by ICO with multiple boards, disambiguated by name."""
        from sync_edesky_boards import SyncStats, match_and_update_board

        mock_repo.get_notice_board_by_edesky_id.return_value = None
        mock_repo.get_notice_boards_by_ico.return_value = [
            NoticeBoard(id=1, ico="12345678", name="Other Name", edesky_id=None),
            NoticeBoard(id=2, ico="12345678", name="Test Municipality", edesky_id=None),
        ]

        stats = SyncStats()
        result = match_and_update_board(mock_repo, sample_dashboard, stats)

        assert result is True
        assert stats.matched_by_ico == 1
        # Should have been called with board_id=2 (matching name)
        call_args = mock_repo.update_notice_board_edesky_fields.call_args
        assert call_args.kwargs["board_id"] == 2

    def test_match_by_name_and_district(
        self, mock_repo: MagicMock, sample_dashboard: EdeskyDashboard
    ) -> None:
        """Test matching by name and district."""
        from sync_edesky_boards import SyncStats, match_and_update_board

        mock_repo.get_notice_board_by_edesky_id.return_value = None
        mock_repo.get_notice_boards_by_ico.return_value = []
        mock_repo.get_notice_boards_by_name_and_district.return_value = [
            NoticeBoard(id=1, name="Test Municipality", nuts4_name="District", edesky_id=None)
        ]

        stats = SyncStats()
        result = match_and_update_board(mock_repo, sample_dashboard, stats)

        assert result is True
        assert stats.matched_by_name == 1

    def test_no_match_creates_new(
        self, mock_repo: MagicMock, sample_dashboard: EdeskyDashboard
    ) -> None:
        """Test that no match returns False (new record should be created)."""
        from sync_edesky_boards import SyncStats, match_and_update_board

        mock_repo.get_notice_board_by_edesky_id.return_value = None
        mock_repo.get_notice_boards_by_ico.return_value = []
        mock_repo.get_notice_boards_by_name_and_district.return_value = []

        stats = SyncStats()
        result = match_and_update_board(mock_repo, sample_dashboard, stats)

        assert result is False

    def test_ambiguous_match_skipped(
        self, mock_repo: MagicMock, sample_dashboard: EdeskyDashboard
    ) -> None:
        """Test that ambiguous matches are skipped."""
        from sync_edesky_boards import SyncStats, match_and_update_board

        mock_repo.get_notice_board_by_edesky_id.return_value = None
        mock_repo.get_notice_boards_by_ico.return_value = []
        mock_repo.get_notice_boards_by_name_and_district.return_value = [
            NoticeBoard(id=1, name="Test Municipality", edesky_id=None),
            NoticeBoard(id=2, name="Test Municipality", edesky_id=None),
        ]

        stats = SyncStats()
        result = match_and_update_board(mock_repo, sample_dashboard, stats)

        assert result is False
        assert stats.skipped_ambiguous == 1
        assert len(stats.ambiguous_boards) == 1

    def test_dry_run_no_update(
        self, mock_repo: MagicMock, sample_dashboard: EdeskyDashboard
    ) -> None:
        """Test dry run doesn't call update."""
        from sync_edesky_boards import SyncStats, match_and_update_board

        mock_repo.get_notice_board_by_edesky_id.return_value = None
        mock_repo.get_notice_boards_by_ico.return_value = [
            NoticeBoard(id=1, ico="12345678", name="Test", edesky_id=None)
        ]

        stats = SyncStats()
        result = match_and_update_board(mock_repo, sample_dashboard, stats, dry_run=True)

        assert result is True
        assert stats.matched_by_ico == 1
        mock_repo.update_notice_board_edesky_fields.assert_not_called()


class TestRepositoryMethods:
    """Tests for repository matching methods."""

    @pytest.fixture
    def mock_conn(self) -> MagicMock:
        """Create mock database connection."""
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        return conn

    def test_get_notice_board_by_edesky_url_valid(self, mock_conn: MagicMock) -> None:
        """Test finding board by eDesky URL - direct match."""
        from notice_boards.repository import DocumentRepository

        cursor_mock = MagicMock()
        # Mock direct URL match returning a row
        cursor_mock.fetchone.return_value = (
            1,
            None,
            "Test",
            "12345678",
            "https://edesky.cz/desky/123",
            123,
            "obec",
            None,
            None,
            None,
            None,
            None,
            None,
            None,
        )
        mock_conn.cursor.return_value.__enter__.return_value = cursor_mock

        repo = DocumentRepository(mock_conn)
        result = repo.get_notice_board_by_edesky_url("https://edesky.cz/desky/123")

        assert result is not None
        assert result.edesky_id == 123

    def test_get_notice_board_by_edesky_url_invalid(self, mock_conn: MagicMock) -> None:
        """Test invalid URL returns None."""
        from notice_boards.repository import DocumentRepository

        cursor_mock = MagicMock()
        # Mock no direct URL match
        cursor_mock.fetchone.return_value = None
        mock_conn.cursor.return_value.__enter__.return_value = cursor_mock

        repo = DocumentRepository(mock_conn)
        # Invalid URL (no /desky/ pattern) should return None
        result = repo.get_notice_board_by_edesky_url("invalid-url")
        assert result is None

    def test_get_notice_board_stats(self, mock_conn: MagicMock) -> None:
        """Test getting notice board stats."""
        from notice_boards.repository import DocumentRepository

        cursor_mock = MagicMock()
        # Order: total, with_edesky_id, with_ico, with_edesky_url, with_nuts3, with_nuts4,
        #        with_municipality_code, with_data_box, with_source_url
        cursor_mock.fetchone.return_value = (100, 80, 90, 85, 70, 60, 55, 50, 45)
        mock_conn.cursor.return_value.__enter__.return_value = cursor_mock

        repo = DocumentRepository(mock_conn)
        stats = repo.get_notice_board_stats()

        assert stats["total"] == 100
        assert stats["with_edesky_id"] == 80
        assert stats["with_ico"] == 90
        assert stats["with_municipality_code"] == 55
        assert stats["with_data_box"] == 50
        assert stats["with_source_url"] == 45

    def test_get_notice_board_stats_empty(self, mock_conn: MagicMock) -> None:
        """Test getting stats when no boards exist."""
        from notice_boards.repository import DocumentRepository

        cursor_mock = MagicMock()
        cursor_mock.fetchone.return_value = None
        mock_conn.cursor.return_value.__enter__.return_value = cursor_mock

        repo = DocumentRepository(mock_conn)
        stats = repo.get_notice_board_stats()

        assert stats["total"] == 0
        assert stats["with_edesky_id"] == 0
