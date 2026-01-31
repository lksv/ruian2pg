"""Tests for storage backends."""

import tempfile
from pathlib import Path

import pytest

from notice_boards.storage import FilesystemStorage, StorageError


class TestFilesystemStorage:
    """Tests for FilesystemStorage backend."""

    @pytest.fixture
    def temp_storage(self) -> FilesystemStorage:
        """Create a storage backend with a temporary directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield FilesystemStorage(Path(tmpdir))

    def test_save_and_load(self, temp_storage: FilesystemStorage) -> None:
        """Test basic save and load operations."""
        content = b"Hello, World!"
        path = "test/file.txt"

        saved_path = temp_storage.save(path, content)
        assert saved_path == path

        loaded = temp_storage.load(path)
        assert loaded == content

    def test_save_creates_directories(self, temp_storage: FilesystemStorage) -> None:
        """Test that save creates parent directories."""
        content = b"Nested content"
        path = "deep/nested/path/file.txt"

        temp_storage.save(path, content)

        assert temp_storage.exists(path)
        loaded = temp_storage.load(path)
        assert loaded == content

    def test_exists_returns_false_for_missing(self, temp_storage: FilesystemStorage) -> None:
        """Test exists returns False for non-existent files."""
        assert not temp_storage.exists("nonexistent.txt")

    def test_exists_returns_true_for_existing(self, temp_storage: FilesystemStorage) -> None:
        """Test exists returns True for existing files."""
        path = "existing.txt"
        temp_storage.save(path, b"content")

        assert temp_storage.exists(path)

    def test_delete_removes_file(self, temp_storage: FilesystemStorage) -> None:
        """Test delete removes the file."""
        path = "to_delete.txt"
        temp_storage.save(path, b"content")
        assert temp_storage.exists(path)

        temp_storage.delete(path)
        assert not temp_storage.exists(path)

    def test_delete_nonexistent_does_not_raise(self, temp_storage: FilesystemStorage) -> None:
        """Test delete doesn't raise for non-existent files."""
        # Should not raise
        temp_storage.delete("nonexistent.txt")

    def test_load_nonexistent_raises(self, temp_storage: FilesystemStorage) -> None:
        """Test load raises StorageError for non-existent files."""
        with pytest.raises(StorageError, match="File not found"):
            temp_storage.load("nonexistent.txt")

    def test_path_traversal_prevention(self, temp_storage: FilesystemStorage) -> None:
        """Test that path traversal attempts are blocked."""
        with pytest.raises(StorageError, match="path traversal"):
            temp_storage.save("../escape.txt", b"malicious")

        with pytest.raises(StorageError, match="path traversal"):
            temp_storage.save("foo/../../escape.txt", b"malicious")

    def test_get_url_returns_none(self, temp_storage: FilesystemStorage) -> None:
        """Test get_url returns None for filesystem storage."""
        path = "file.txt"
        temp_storage.save(path, b"content")

        assert temp_storage.get_url(path) is None

    def test_compute_hash(self, temp_storage: FilesystemStorage) -> None:
        """Test SHA-256 hash computation."""
        content = b"Hello, World!"
        expected_hash = "dffd6021bb2bd5b0af676290809ec3a53191dd81c7f70a4b28688a362182986f"

        assert temp_storage.compute_hash(content) == expected_hash

    def test_save_empty_file(self, temp_storage: FilesystemStorage) -> None:
        """Test saving an empty file."""
        path = "empty.txt"
        temp_storage.save(path, b"")

        assert temp_storage.exists(path)
        assert temp_storage.load(path) == b""

    def test_save_binary_content(self, temp_storage: FilesystemStorage) -> None:
        """Test saving binary content."""
        # Some binary data with null bytes
        content = bytes(range(256))
        path = "binary.bin"

        temp_storage.save(path, content)
        loaded = temp_storage.load(path)

        assert loaded == content

    def test_overwrite_existing(self, temp_storage: FilesystemStorage) -> None:
        """Test overwriting an existing file."""
        path = "overwrite.txt"
        temp_storage.save(path, b"original")
        temp_storage.save(path, b"updated")

        assert temp_storage.load(path) == b"updated"

    def test_path_with_backslashes(self, temp_storage: FilesystemStorage) -> None:
        """Test that backslashes are normalized to forward slashes."""
        content = b"Windows path"
        path = "folder\\subfolder\\file.txt"

        temp_storage.save(path, content)

        # Should be accessible with forward slashes
        assert temp_storage.exists("folder/subfolder/file.txt")
        assert temp_storage.load("folder/subfolder/file.txt") == content
