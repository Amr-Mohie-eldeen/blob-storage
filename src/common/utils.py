# src/common/utils.py
import hashlib
import os
from typing import BinaryIO


def calculate_checksum(file: BinaryIO) -> str:
    """Calculate SHA-256 checksum of a file"""
    sha256_hash = hashlib.sha256()
    for byte_block in iter(lambda: file.read(4096), b""):
        sha256_hash.update(byte_block)
    file.seek(0)
    return sha256_hash.hexdigest()


def get_available_space(path: str) -> int:
    """Get available space in bytes"""
    stats = os.statvfs(path)
    return stats.f_bavail * stats.f_frsize
