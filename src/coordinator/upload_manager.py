import asyncio
import logging
import uuid
from datetime import datetime
from typing import Dict, List

from fastapi import HTTPException, UploadFile

from .blob_storage import BlobStorage
from .metadata_manager import MetadataManager
from .node_manager import NodeManager
from .repair_manager import RepairManager

logger = logging.getLogger(__name__)


class UploadManager:
    def __init__(
        self,
        metadata_manager: MetadataManager,
        node_manager: NodeManager,
        blob_storage: BlobStorage,
        repair_manager: RepairManager,
    ):
        self.metadata_manager = metadata_manager
        self.node_manager = node_manager
        self.blob_storage = blob_storage
        self.repair_manager = repair_manager

    async def handle_upload(self, file: UploadFile) -> Dict:
        """Handle the complete upload process for a file"""
        try:
            blob_id = str(uuid.uuid4())
            logger.info(f"Starting upload for {file.filename} (blob: {blob_id})")

            # Store filename mapping
            self.metadata_manager.store_file_name(file.filename, blob_id)

            # Get active nodes
            active_nodes = self.node_manager.get_active_nodes()
            if not active_nodes:
                raise HTTPException(
                    status_code=503, detail="No storage nodes available"
                )

            # Read file content
            content = await file.read()
            content_size = len(content)
            logger.info(f"Read {content_size} bytes from {file.filename}")

            # Initialize metadata
            initial_metadata = self._create_initial_metadata(
                blob_id, file, content_size, active_nodes
            )
            self.metadata_manager.store_metadata(blob_id, initial_metadata)
            logger.info(f"Initialized metadata for blob {blob_id}: {initial_metadata}")

            # Create and execute upload tasks
            tasks = self._create_upload_tasks(blob_id, active_nodes, content, file)
            logger.info(f"Created upload tasks for nodes: {active_nodes}")

            return await self._handle_upload_tasks(blob_id, tasks, active_nodes)

        except Exception as e:
            logger.error(f"Upload failed: {str(e)}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))

    def _create_initial_metadata(
        self, blob_id: str, file: UploadFile, content_size: int, active_nodes: List[str]
    ) -> Dict:
        """Create initial metadata for a new blob"""
        return {
            "blob_id": blob_id,
            "original_filename": file.filename,
            "content_type": file.content_type,
            "upload_status": "in_progress",
            "successful_nodes": [],
            "pending_nodes": active_nodes,
            "failed_nodes": [],
            "created_at": datetime.now().isoformat(),
            "size": content_size,
            "checksum": None,
        }

    def _create_upload_tasks(
        self, blob_id: str, active_nodes: List[str], content: bytes, file: UploadFile
    ) -> List[asyncio.Task]:
        """Create upload tasks for all active nodes"""
        return [
            asyncio.create_task(
                self.blob_storage.store_blob_on_node(
                    node_id, blob_id, content, file.filename, file.content_type
                )
            )
            for node_id in active_nodes
        ]

    async def _handle_upload_tasks(
        self, blob_id: str, tasks: List[asyncio.Task], active_nodes: List[str]
    ) -> Dict:
        """Handle the upload tasks and return the result of the first successful upload"""
        try:
            first_success = await self._wait_for_first_success(
                blob_id, tasks, active_nodes
            )
            if first_success:
                return first_success

            raise HTTPException(status_code=500, detail="Failed to upload to any nodes")
        except Exception as e:
            logger.error(f"Error handling upload tasks: {str(e)}")
            raise

    async def _wait_for_first_success(
        self, blob_id: str, tasks: List[asyncio.Task], active_nodes: List[str]
    ) -> Dict:
        """Wait for the first successful upload and handle remaining uploads in background"""
        for completed_task in asyncio.as_completed(tasks):
            try:
                result = await completed_task
                # Update metadata with first success
                metadata = self.metadata_manager.get_blob_metadata(blob_id)
                if metadata:
                    metadata["successful_nodes"] = [result["node_id"]]
                    metadata["size"] = result["size"]
                    metadata["checksum"] = result["checksum"]
                    metadata["pending_nodes"] = [
                        n for n in active_nodes if n != result["node_id"]
                    ]
                    self.metadata_manager.store_metadata(blob_id, metadata)

                    # Start background task for remaining uploads
                    remaining_tasks = [t for t in tasks if not t.done()]
                    if remaining_tasks:
                        asyncio.create_task(
                            self._handle_remaining_uploads(blob_id, remaining_tasks)
                        )

                    return {
                        "message": "File upload initiated successfully",
                        "metadata": metadata,
                    }
            except Exception as e:
                logger.error(f"Upload failed to node: {str(e)}")
        return None

    async def _handle_remaining_uploads(
        self, blob_id: str, remaining_tasks: List[asyncio.Task]
    ):
        """Handle remaining uploads in the background"""
        try:
            metadata = self.metadata_manager.get_blob_metadata(blob_id)
            if not metadata:
                logger.error(f"No metadata found for blob {blob_id}")
                return

            logger.info(
                f"Starting background uploads for blob {blob_id}. "
                f"Current state: successful={metadata.get('successful_nodes', [])}, "
                f"pending={metadata.get('pending_nodes', [])}"
            )

            successful_nodes, failed_nodes = await self._process_remaining_tasks(
                remaining_tasks
            )
            await self._update_final_metadata(blob_id, successful_nodes, failed_nodes)

        except Exception as e:
            logger.error(
                f"Error handling remaining uploads for blob {blob_id}: {str(e)}"
            )

    async def _process_remaining_tasks(
        self, tasks: List[asyncio.Task]
    ) -> tuple[set, set]:
        """Process remaining upload tasks and track successes/failures"""
        successful_nodes = set()
        failed_nodes = set()

        for completed_task in asyncio.as_completed(tasks):
            try:
                result = await completed_task
                node_id = result["node_id"]
                successful_nodes.add(node_id)
                logger.info(
                    f"Background upload succeeded for node {node_id}. "
                    f"Total successful: {len(successful_nodes)}"
                )
            except Exception as e:
                logger.error(f"Background upload failed: {str(e)}")
                if "node_id=" in str(e):
                    failed_node = str(e).split("node_id=")[1].split()[0]
                    failed_nodes.add(failed_node)
                    logger.error(
                        f"Upload failed for node {failed_node}. "
                        f"Total failed: {len(failed_nodes)}"
                    )

        return successful_nodes, failed_nodes

    async def _update_final_metadata(
        self, blob_id: str, successful_nodes: set, failed_nodes: set
    ):
        """Update final metadata after all uploads complete"""
        metadata = self.metadata_manager.get_blob_metadata(blob_id)
        if not metadata:
            return

        metadata["successful_nodes"] = list(successful_nodes)
        metadata["failed_nodes"] = list(failed_nodes)
        metadata["pending_nodes"] = []

        if len(failed_nodes) == 0:
            metadata["upload_status"] = "completed"
            logger.info(
                f"Blob {blob_id} upload completed successfully. "
                f"Stored on nodes: {successful_nodes}"
            )
        else:
            metadata["upload_status"] = "degraded"
            logger.warning(
                f"Blob {blob_id} upload degraded. "
                f"Successful: {successful_nodes}, Failed: {failed_nodes}"
            )

        self.metadata_manager.store_metadata(blob_id, metadata)
        logger.info(f"Updated final metadata for blob {blob_id}: {metadata}")

        # Check if we need to trigger auto-repair
        if len(successful_nodes) < len(self.node_manager.get_active_nodes()) * 0.5:
            logger.warning(f"Triggering auto-repair for blob {blob_id}")
            await self.repair_manager.trigger_auto_repair(blob_id)
