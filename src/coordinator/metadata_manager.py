import json
import logging
from typing import Optional

from fastapi import HTTPException
from redis import Redis

logger = logging.getLogger(__name__)


class MetadataManager:
    def __init__(self, redis: Redis):
        self.redis = redis

    def store_metadata(self, blob_id: str, metadata: dict) -> None:
        """Store metadata in Redis"""
        try:
            redis_metadata = {
                key: (
                    json.dumps(value) if isinstance(value, (list, dict)) else str(value)
                )
                for key, value in metadata.items()
            }
            logger.debug(f"Storing metadata for blob {blob_id}: {redis_metadata}")
            self.redis.hset(f"blob:{blob_id}", mapping=redis_metadata)
        except Exception as redis_error:
            logger.error(f"Redis error: {str(redis_error)}")
            raise HTTPException(status_code=500, detail="Failed to store metadata")

    def get_blob_metadata(self, blob_id: str) -> Optional[dict]:
        """Get and parse blob metadata"""
        try:
            metadata = self.redis.hgetall(f"blob:{blob_id}")
            logger.debug(f"Retrieved raw metadata for blob {blob_id}: {metadata}")
            if not metadata:
                return None

            for key in metadata:
                try:
                    if key in ["successful_nodes", "pending_nodes", "failed_nodes"]:
                        metadata[key] = json.loads(metadata[key])
                except json.JSONDecodeError:
                    logger.error(
                        f"Failed to parse JSON for key {key} in blob {blob_id}"
                    )
                    pass

            logger.debug(f"Parsed metadata for blob {blob_id}: {metadata}")
            return metadata
        except Exception as e:
            logger.error(f"Failed to get metadata for blob {blob_id}: {str(e)}")
            return None

    def store_file_name(self, filename: str, blob_id: str) -> None:
        """Maps a filename to a blob ID in Redis."""
        try:
            self.redis.hset("filename_to_blob", filename, blob_id)
        except Exception as e:
            logger.error(f"Failed to store file name: {e}")

    def get_blob_id_by_file_name(self, file_name: str) -> Optional[str]:
        """Retrieves the blob ID associated with a filename."""
        try:
            blob_id = self.redis.hget("filename_to_blob", file_name)
            return blob_id
        except Exception as e:
            logger.error(f"Failed to retrieve blob ID by file name: {e}")
            return None
