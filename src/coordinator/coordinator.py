# src/coordinator/coordinator.py
import logging
from time import gmtime
from typing import List

from fastapi import HTTPException, UploadFile
from redis import Redis

from src.common.config import settings
from src.common.interfaces import ICoordinator

from .blob_storage import BlobStorage
from .metadata_manager import MetadataManager
from .node_manager import NodeManager
from .repair_manager import RepairManager
from .upload_manager import UploadManager

# https://stackoverflow.com/a/7517430/49489
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s.%(msecs)03dZ [%(name)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logging.Formatter.converter = gmtime
logger = logging.getLogger(__name__)


class Coordinator(ICoordinator):
    def __init__(self):
        try:
            self.redis = Redis(
                host=settings.REDIS_HOST,
                port=settings.REDIS_PORT,
                decode_responses=True,
            )
            self.metadata_manager = MetadataManager(self.redis)
            self.node_manager = NodeManager(self.redis)
            self.blob_storage = BlobStorage(self.metadata_manager, self.node_manager)
            self.repair_manager = RepairManager(
                self.metadata_manager, self.node_manager, self.blob_storage
            )
            self.upload_manager = UploadManager(
                self.metadata_manager,
                self.node_manager,
                self.blob_storage,
                self.repair_manager,
            )
            # Test Redis connection
            self.redis.ping()
            logger.info("Redis connection established")
        except Exception as e:
            logger.error(f"Redis connection failed: {str(e)}")
            raise Exception(f"Failed to initialize Redis: {str(e)}")

    async def store_blob(self, file: UploadFile) -> dict:
        """Store a blob across all available storage nodes concurrently"""
        return await self.upload_manager.handle_upload(file)

    async def get_blob(self, file_name: str):
        """Retrieve a blob by its file name"""
        try:
            blob_id = self.metadata_manager.get_blob_id_by_file_name(file_name)
            if not blob_id:
                logger.error(f"File not found: {file_name}")
                raise HTTPException(status_code=404, detail="File not found")

            metadata = self.metadata_manager.get_blob_metadata(blob_id)
            if not metadata:
                logger.error(f"Metadata not found for blob: {blob_id}")
                raise HTTPException(status_code=404, detail="Blob metadata not found")

            status = metadata.get("upload_status", "unknown")
            logger.info(
                f"Retrieved metadata for {file_name} (blob: {blob_id}): "
                f"size={metadata.get('size')}B, status={status}, "
                f"nodes={metadata.get('successful_nodes', [])}"
            )

            if status == "in_progress":
                logger.warning(
                    f"Attempting to retrieve blob {blob_id} while upload is still in progress"
                )
            elif status == "degraded":
                logger.warning(f"Retrieving blob {blob_id} in degraded state")

            node_id = self.node_manager.get_available_node_for_blob(metadata)
            return await self.blob_storage.get_blob_from_node(node_id, blob_id)

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error retrieving blob: {str(e)}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))

    def get_active_nodes(self) -> List[str]:
        """Get list of active storage nodes"""
        return self.node_manager.get_active_nodes()

    def _store_file_name(self, filename: str, blob_id: str):
        """Store the file name associated with a blob ID"""
        self.metadata_manager.store_file_name(filename, blob_id)
