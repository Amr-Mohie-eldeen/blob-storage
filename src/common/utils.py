# src/common/utils.py
import hashlib
import os
import aiofiles


async def calculate_checksum(file_path: str) -> str:
    """Calculate SHA-256 checksum of a file asynchronously"""
    sha256_hash = hashlib.sha256()
    async with aiofiles.open(file_path, "rb") as f:
        while chunk := await f.read(8192):
            sha256_hash.update(chunk)
    return sha256_hash.hexdigest()


def get_available_space(path: str) -> int:
    """Get available space in bytes"""
    stats = os.statvfs(path)
    return stats.f_bavail * stats.f_frsize
