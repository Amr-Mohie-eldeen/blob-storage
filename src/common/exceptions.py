# src/common/exceptions.py
class BlobStorageError(Exception):
    """Base exception for blob storage"""

    pass


class NodeNotAvailableError(BlobStorageError):
    """Raised when storage node is not available"""

    pass


class StorageFullError(BlobStorageError):
    """Raised when storage is full"""

    pass


class BlobNotFoundError(BlobStorageError):
    """Raised when blob is not found"""

    pass
