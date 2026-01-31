"""Storage backends for document attachments.

Provides an abstract interface for storing attachment files,
with a filesystem implementation. S3 can be added later.
"""

import hashlib
from abc import ABC, abstractmethod
from pathlib import Path


class StorageBackend(ABC):
    """Abstract storage backend for document attachments.

    All paths are relative to the storage root and use forward slashes
    regardless of the operating system.
    """

    @abstractmethod
    def save(self, path: str, content: bytes) -> str:
        """Save file content to storage.

        Args:
            path: Relative path where to store the file (e.g., "2024/01/doc123/file.pdf")
            content: File content as bytes

        Returns:
            The storage path (same as input path for most backends)

        Raises:
            StorageError: If saving fails
        """
        pass

    @abstractmethod
    def load(self, path: str) -> bytes:
        """Load file content from storage.

        Args:
            path: Relative path to the file

        Returns:
            File content as bytes

        Raises:
            StorageError: If file doesn't exist or loading fails
        """
        pass

    @abstractmethod
    def exists(self, path: str) -> bool:
        """Check if file exists in storage.

        Args:
            path: Relative path to the file

        Returns:
            True if file exists, False otherwise
        """
        pass

    @abstractmethod
    def delete(self, path: str) -> None:
        """Delete file from storage.

        Args:
            path: Relative path to the file

        Raises:
            StorageError: If deletion fails (file not existing is not an error)
        """
        pass

    @abstractmethod
    def get_url(self, path: str) -> str | None:
        """Get public URL for the file if available.

        Args:
            path: Relative path to the file

        Returns:
            Public URL or None if not available
        """
        pass

    def compute_hash(self, content: bytes) -> str:
        """Compute SHA-256 hash of content.

        Args:
            content: File content as bytes

        Returns:
            Hex-encoded SHA-256 hash
        """
        return hashlib.sha256(content).hexdigest()


class StorageError(Exception):
    """Exception raised for storage operations failures."""

    pass


class FilesystemStorage(StorageBackend):
    """Local filesystem storage backend.

    Stores files in a directory structure on the local filesystem.

    Example:
        storage = FilesystemStorage(Path("/data/attachments"))
        storage.save("2024/01/doc123/file.pdf", content)
        content = storage.load("2024/01/doc123/file.pdf")
    """

    def __init__(self, base_path: Path) -> None:
        """Initialize filesystem storage.

        Args:
            base_path: Base directory for storing files
        """
        self.base_path = base_path

    def _resolve_path(self, path: str) -> Path:
        """Resolve relative path to absolute filesystem path.

        Args:
            path: Relative path

        Returns:
            Absolute Path object

        Raises:
            StorageError: If path tries to escape base directory
        """
        # Normalize path separators
        normalized = path.replace("\\", "/")
        full_path = (self.base_path / normalized).resolve()

        # Security check: ensure path doesn't escape base directory
        try:
            full_path.relative_to(self.base_path.resolve())
        except ValueError as err:
            raise StorageError(f"Invalid path: {path} (path traversal attempt)") from err

        return full_path

    def save(self, path: str, content: bytes) -> str:
        """Save file content to filesystem.

        Creates parent directories if they don't exist.

        Args:
            path: Relative path where to store the file
            content: File content as bytes

        Returns:
            The storage path (same as input)

        Raises:
            StorageError: If saving fails
        """
        try:
            full_path = self._resolve_path(path)
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_bytes(content)
            return path
        except OSError as e:
            raise StorageError(f"Failed to save file {path}: {e}") from e

    def load(self, path: str) -> bytes:
        """Load file content from filesystem.

        Args:
            path: Relative path to the file

        Returns:
            File content as bytes

        Raises:
            StorageError: If file doesn't exist or loading fails
        """
        try:
            full_path = self._resolve_path(path)
            if not full_path.is_file():
                raise StorageError(f"File not found: {path}")
            return full_path.read_bytes()
        except OSError as e:
            raise StorageError(f"Failed to load file {path}: {e}") from e

    def exists(self, path: str) -> bool:
        """Check if file exists on filesystem.

        Args:
            path: Relative path to the file

        Returns:
            True if file exists, False otherwise
        """
        try:
            full_path = self._resolve_path(path)
            return full_path.is_file()
        except StorageError:
            return False

    def delete(self, path: str) -> None:
        """Delete file from filesystem.

        Args:
            path: Relative path to the file

        Raises:
            StorageError: If deletion fails (file not existing is not an error)
        """
        try:
            full_path = self._resolve_path(path)
            if full_path.is_file():
                full_path.unlink()
        except OSError as e:
            raise StorageError(f"Failed to delete file {path}: {e}") from e

    def get_url(self, path: str) -> str | None:  # noqa: ARG002
        """Get URL for the file.

        Filesystem storage doesn't support public URLs.

        Args:
            path: Relative path to the file

        Returns:
            None (filesystem storage doesn't have public URLs)
        """
        # Filesystem storage doesn't provide public URLs
        # Path parameter is required by the interface but not used here
        return None
