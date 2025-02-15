# src/storage_node/node.py
import os
import asyncio
import logging
from datetime import datetime
from fastapi import UploadFile, HTTPException
from redis import Redis
from pathlib import Path
from typing import Dict, Any
from fastapi.responses import FileResponse
from src.common.config import settings
from src.common.utils import calculate_checksum, get_available_space
from src.models.schemas import NodeInfo, BlobMetadata
from src.common.exceptions import BlobNotFoundError
import aiofiles
from src.common.interfaces import IStorageNode
from src.common.redis_metadata_store import RedisMetadataStore

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class StorageNode(IStorageNode):
    def __init__(self, node_id: str):
        self.node_id = node_id
        self.storage_dir = os.path.join(settings.BASE_STORAGE_PATH, f"node_{node_id}")
        logger.info(
            f"Initializing storage node {node_id} with directory: {self.storage_dir}"
        )

        try:
            self.redis = Redis(
                host=settings.REDIS_HOST,
                port=settings.REDIS_PORT,
                decode_responses=True,
            )
            # Test Redis connection
            self.redis.ping()
            logger.info("Successfully connected to Redis")
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {str(e)}")
            raise

        try:
            os.makedirs(self.storage_dir, exist_ok=True)
            logger.info(f"Storage directory created/verified: {self.storage_dir}")
        except Exception as e:
            logger.error(f"Failed to create storage directory: {str(e)}")
            raise

        self.metadata_store = RedisMetadataStore(self.redis)

    async def store_blob(self, blob_id: str, file: UploadFile) -> dict:
        """Store a blob file"""
        logger.info(f"Storing blob {blob_id}, filename: {file.filename}")

        try:
            # Create blob path
            blob_path = Path(self.storage_dir) / blob_id

            # Check available space
            file_size = 0
            checksum = None

            # Create and write directly to the final blob path
            async with aiofiles.open(
                blob_path, "wb"
            ) as f:  # Use aiofiles for async I/O
                while chunk := await file.read(8192):
                    file_size += len(chunk)
                    await f.write(chunk)

            # Calculate checksum
            checksum = await calculate_checksum(str(blob_path))

            logger.info(
                f"Successfully stored blob {blob_id}, size: {file_size}, checksum: {checksum}"
            )

            # Store blob metadata
            metadata = BlobMetadata(
                blob_id=blob_id,
                original_filename=file.filename,
                content_type=file.content_type,
                size=file_size,
                checksum=checksum,
                created_at=datetime.now(),
                nodes=[self.node_id],
            )

            # Convert the metadata to a dict and ensure datetime is converted to string
            metadata_dict = {
                k: str(v) if isinstance(v, (datetime, list)) else v
                for k, v in metadata.dict().items()
            }

            # Store metadata in Redis
            self.redis.hset(f"blob:{blob_id}", mapping=metadata_dict)

            # Update node info with new space usage
            self._update_heartbeat()

            return {
                "blob_id": blob_id,
                "size": file_size,
                "checksum": checksum,
                "node_id": self.node_id,
            }

        except Exception as e:
            logger.error(f"Failed to store blob {blob_id}: {str(e)}", exc_info=True)
            raise HTTPException(
                status_code=500, detail=f"Failed to store blob: {str(e)}"
            )

    async def start(self):
        """Start the storage node"""
        logger.info(f"Starting storage node {self.node_id}")
        try:
            self.register_node()
            asyncio.create_task(self._heartbeat_loop())
            logger.info(f"Storage node {self.node_id} started successfully")
        except Exception as e:
            logger.error(f"Failed to start storage node: {str(e)}", exc_info=True)
            raise

    def register_node(self):
        """Register this node with the coordinator"""
        try:
            # Log Redis connection details
            logger.info(
                f"Attempting to connect to Redis at {self.redis.connection_pool.connection_kwargs}"
            )

            # Test Redis connection
            if not self.redis.ping():
                raise Exception("Could not ping Redis server")

            logger.info("Successfully connected to Redis")

            node_info = NodeInfo(
                node_id=self.node_id,
                storage_dir=self.storage_dir,
                available_space=get_available_space(self.storage_dir),
                status="active",
                last_heartbeat=datetime.now(),
            )

            # Convert to JSON and log
            node_json = node_info.json()
            logger.info(f"Registering node with info: {node_json}")

            # Attempt to set in Redis
            result = self.redis.hset("storage_nodes", self.node_id, node_json)
            logger.info(f"Redis hset result: {result}")

            # Verify registration
            stored_data = self.redis.hget("storage_nodes", self.node_id)
            if stored_data:
                logger.info(f"Successfully verified node registration: {stored_data}")
            else:
                raise Exception(
                    "Node registration verification failed - no data stored"
                )

            logger.info(f"Node {self.node_id} registered successfully")
        except Exception as e:
            logger.error(f"Failed to register node: {str(e)}", exc_info=True)
            raise

    async def _heartbeat_loop(self):
        """Periodic heartbeat update"""
        while True:
            try:
                self._update_heartbeat()
                await asyncio.sleep(settings.NODE_HEARTBEAT_INTERVAL)
            except Exception as e:
                logger.error(f"Heartbeat error: {str(e)}", exc_info=True)

    def _update_heartbeat(self):
        """Update node heartbeat"""
        try:
            node_info = NodeInfo(
                node_id=self.node_id,
                storage_dir=self.storage_dir,
                available_space=get_available_space(self.storage_dir),
                status="active",
                last_heartbeat=datetime.now(),
            )
            self.redis.hset("storage_nodes", self.node_id, node_info.json())
            logger.debug(f"Heartbeat updated for node {self.node_id}")
        except Exception as e:
            logger.error(f"Failed to update heartbeat: {str(e)}", exc_info=True)
            raise

    async def get_blob(self, blob_id: str):
        """Retrieve a blob file"""
        logger.info(f"Retrieving blob {blob_id}")

        try:
            blob_path = Path(self.storage_dir) / blob_id

            if not blob_path.exists():
                logger.error(f"Blob {blob_id} not found at {blob_path}")
                raise BlobNotFoundError(f"Blob {blob_id} not found")

            # Get metadata from Redis
            metadata = self.redis.hgetall(f"blob:{blob_id}")
            if not metadata:
                logger.error(f"Metadata not found for blob {blob_id}")
                raise BlobNotFoundError(f"Metadata not found for blob {blob_id}")

            # Verify file integrity
            current_checksum = await calculate_checksum(str(blob_path))

            if current_checksum != metadata.get("checksum"):
                logger.error(f"Checksum mismatch for blob {blob_id}")
                raise HTTPException(
                    status_code=500, detail="File integrity check failed"
                )

            logger.info(f"Successfully retrieved blob {blob_id}")

            return FileResponse(
                path=str(blob_path),
                filename=metadata.get("original_filename", blob_id),
                media_type=metadata.get("content_type", "application/octet-stream"),
            )

        except BlobNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e))
        except Exception as e:
            logger.error(f"Failed to retrieve blob {blob_id}: {str(e)}", exc_info=True)
            raise HTTPException(
                status_code=500, detail=f"Failed to retrieve blob: {str(e)}"
            )

    async def delete_blob(self, blob_id: str) -> bool:
        try:
            file_path = Path(self.storage_dir) / blob_id
            if file_path.exists():
                file_path.unlink()
                return True
            return False
        except Exception as e:
            logger.error(f"Failed to delete blob {blob_id}: {str(e)}")
            return False

    def get_node_status(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "storage_dir": self.storage_dir,
            "available_space": get_available_space(self.storage_dir),
            "status": "active",
        }
