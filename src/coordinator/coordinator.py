# src/coordinator/coordinator.py
from fastapi import UploadFile, HTTPException
import uuid
from datetime import datetime
import json
from redis import Redis
from src.common.config import settings
import logging
import httpx
from fastapi.responses import StreamingResponse
from src.common.interfaces import ICoordinator
from src.common.redis_metadata_store import RedisMetadataStore
from typing import List, Dict, Tuple
from src.models.schemas import NodeInfo
from src.common.utils import get_available_space
import asyncio

logger = logging.getLogger(__name__)


class Coordinator(ICoordinator):
    def __init__(self):
        try:
            self.redis = Redis(
                host=settings.REDIS_HOST,
                port=settings.REDIS_PORT,
                decode_responses=True,
            )
            self.metadata_store = RedisMetadataStore(self.redis)
            # Test Redis connection
            self.redis.ping()
        except Exception as e:
            logger.error(f"Redis connection failed: {str(e)}")
            raise Exception(f"Failed to initialize Redis: {str(e)}")

    def _store_file_name(self, filename: str, blob_id: str):
        """Store the file name associated with a blob ID"""
        try:
            self.redis.hset("filename_to_blob", filename, blob_id)
        except Exception as e:
            logger.error(f"Failed to store file name: {e}")

    def _get_blob_id_by_file_name(self, file_name: str) -> str:
        """Retrieve the blob ID associated with a file name"""
        try:
            blob_id = self.redis.hget("filename_to_blob", file_name)
            return blob_id
        except Exception as e:
            logger.error(f"Failed to retrieve blob ID by file name: {e}")
            return None

    async def store_blob(self, file: UploadFile) -> dict:
        """Store a blob across all available storage nodes concurrently"""
        try:
            blob_id = str(uuid.uuid4())
            logger.info(f"Processing upload for file: {file.filename}")

            # Store filename mapping
            self._store_file_name(file.filename, blob_id)

            # Get all active nodes
            active_nodes = self.get_active_nodes()
            if not active_nodes:
                raise HTTPException(
                    status_code=503, detail="No storage nodes available"
                )

            # Read file content once
            content = await file.read()

            # Initialize metadata with "in_progress" status
            initial_metadata = {
                "blob_id": blob_id,
                "original_filename": file.filename,
                "content_type": file.content_type,
                "upload_status": "in_progress",
                "successful_nodes": [],
                "pending_nodes": active_nodes,
                "failed_nodes": [],
                "created_at": datetime.now().isoformat(),
                "size": None,
                "checksum": None,
            }
            self._store_metadata(blob_id, initial_metadata)

            # Create and gather upload tasks
            tasks = []
            for node_id in active_nodes:
                task = asyncio.create_task(
                    self._store_blob_on_node(
                        node_id, blob_id, content, file.filename, file.content_type
                    )
                )
                tasks.append(task)

            # Wait for first successful upload
            first_success = None
            for completed_task in asyncio.as_completed(tasks):
                try:
                    result = await completed_task
                    if not first_success:
                        first_success = result
                        # Update metadata with first success
                        metadata = self._get_blob_metadata(blob_id)
                        if metadata:
                            metadata["successful_nodes"] = [result["node_id"]]
                            metadata["size"] = result["size"]
                            metadata["checksum"] = result["checksum"]
                            metadata["pending_nodes"] = [
                                n for n in active_nodes if n != result["node_id"]
                            ]
                            self._store_metadata(blob_id, metadata)

                            # Start background task for remaining uploads
                            remaining_tasks = [t for t in tasks if not t.done()]
                            if remaining_tasks:
                                asyncio.create_task(
                                    self._handle_remaining_uploads(
                                        blob_id, remaining_tasks
                                    )
                                )

                            # Return success response
                            return {
                                "message": "File upload initiated successfully",
                                "metadata": metadata,
                            }
                except Exception as e:
                    logger.error(f"Upload failed to node: {str(e)}")

            # If we get here, all uploads failed
            raise HTTPException(status_code=500, detail="Failed to upload to any nodes")

        except Exception as e:
            logger.error(f"Upload failed: {str(e)}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))

    async def _handle_remaining_uploads(
        self, blob_id: str, remaining_tasks: List[asyncio.Task]
    ):
        """Handle remaining uploads in the background"""
        try:
            metadata = self._get_blob_metadata(blob_id)
            successful_nodes = set(metadata.get("successful_nodes", []))
            failed_nodes = set()

            # Wait for all remaining tasks to complete
            for task in remaining_tasks:
                try:
                    result = await task
                    successful_nodes.add(result["node_id"])
                except Exception as e:
                    logger.error(f"Background upload failed: {str(e)}")
                    # Extract node_id from error message
                    error_msg = str(e)
                    if "node_id=" in error_msg:
                        failed_node = error_msg.split("node_id=")[1].split()[0]
                        failed_nodes.add(failed_node)

            # Update final metadata
            metadata["successful_nodes"] = list(successful_nodes)
            metadata["failed_nodes"] = list(failed_nodes)
            metadata["pending_nodes"] = []
            metadata["upload_status"] = (
                "completed" if len(failed_nodes) == 0 else "degraded"
            )

            self._store_metadata(blob_id, metadata)

            # Check if we need to trigger auto-repair
            if (
                len(successful_nodes) < len(self.get_active_nodes()) * 0.5
            ):  # Less than 50% success
                asyncio.create_task(self._trigger_auto_repair(blob_id))

        except Exception as e:
            logger.error(f"Error handling remaining uploads: {str(e)}")

    async def _store_blob_on_node(
        self,
        node_id: str,
        blob_id: str,
        content: bytes,
        filename: str,
        content_type: str,
    ) -> dict:
        """Store blob on a specific node"""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                files = {"file": (filename, content, content_type)}

                # Add retry logic
                max_retries = 3
                retry_delay = 1.0

                for attempt in range(max_retries):
                    try:
                        response = await client.post(
                            f"http://storage_node_{node_id}:8001/blob/{blob_id}",
                            files=files,
                        )

                        if response.status_code == 200:
                            result = response.json()
                            result["node_id"] = node_id
                            return result

                        logger.error(
                            f"Storage node {node_id} failed with status {response.status_code}: {response.text}"
                        )
                    except Exception as e:
                        logger.error(
                            f"Attempt {attempt + 1} failed for node {node_id}: {str(e)}"
                        )
                        if attempt < max_retries - 1:
                            await asyncio.sleep(retry_delay)
                            retry_delay *= 2  # Exponential backoff
                        continue

                raise Exception(f"All {max_retries} attempts failed for node {node_id}")

        except Exception as e:
            logger.error(f"Failed to store blob on node {node_id}: {str(e)}")
            raise Exception(f"Upload failed for node_id={node_id}: {str(e)}")

    async def _trigger_auto_repair(self, blob_id: str):
        """Trigger auto-repair for degraded blobs"""
        try:
            metadata = self._get_blob_metadata(blob_id)
            successful_nodes = set(metadata.get("successful_nodes", []))
            active_nodes = set(self.get_active_nodes())

            # Find nodes that need the blob
            nodes_needing_blob = active_nodes - successful_nodes

            if not nodes_needing_blob:
                return

            # Get blob from a successful node
            source_node = next(iter(successful_nodes))

            # Copy to nodes that need it
            for target_node in nodes_needing_blob:
                try:
                    await self._copy_blob_between_nodes(
                        blob_id, source_node, target_node
                    )
                    successful_nodes.add(target_node)
                except Exception as e:
                    logger.error(f"Auto-repair failed for node {target_node}: {str(e)}")

            # Update metadata
            metadata["successful_nodes"] = list(successful_nodes)
            metadata["upload_status"] = (
                "completed"
                if len(successful_nodes) == len(active_nodes)
                else "degraded"
            )
            self._store_metadata(blob_id, metadata)

        except Exception as e:
            logger.error(f"Auto-repair failed for blob {blob_id}: {str(e)}")

    def _get_storage_node(self) -> str:
        """Select an appropriate storage node"""
        active_nodes = self.get_active_nodes()
        if not active_nodes:
            logger.error("No active storage nodes available")
            raise HTTPException(status_code=503, detail="No storage nodes available")
        return active_nodes[0]  # For now, just return first node

    def _prepare_metadata(
        self, blob_id: str, file: UploadFile, node_response: dict, node_id: str
    ) -> dict:
        """Prepare metadata for storage"""
        return {
            "blob_id": blob_id,
            "original_filename": file.filename,
            "content_type": file.content_type,
            "size": str(node_response.get("size")),
            "checksum": node_response.get("checksum"),
            "stored_nodes": json.dumps([node_id]),
            "created_at": datetime.now().isoformat(),
        }

    def _store_metadata(self, blob_id: str, metadata: dict) -> None:
        """Store metadata in Redis"""
        try:
            # Convert all values to strings to ensure Redis compatibility
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

    def _prepare_response_metadata(self, metadata: dict) -> dict:
        """Prepare metadata for response"""
        response_metadata = metadata.copy()
        response_metadata["stored_nodes"] = json.loads(metadata["stored_nodes"])
        response_metadata["size"] = int(metadata["size"])
        return response_metadata

    async def get_blob(self, file_name: str):
        """Retrieve a blob by its file name"""
        try:
            # Get blob ID from filename
            blob_id = self._get_blob_id_by_file_name(file_name)
            if not blob_id:
                raise HTTPException(status_code=404, detail="File not found")

            # Get and validate metadata
            metadata = self._get_blob_metadata(blob_id)
            if not metadata:
                raise HTTPException(status_code=404, detail="Blob metadata not found")

            # Get available node
            node_id = self._get_available_node_for_blob(metadata)

            # Retrieve blob from node
            return await self._retrieve_blob_from_node(blob_id, node_id, metadata)

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error retrieving blob: {str(e)}", exc_info=True)
            raise HTTPException(
                status_code=500, detail=f"Failed to retrieve blob: {str(e)}"
            )

    def _get_blob_metadata(self, blob_id: str) -> dict:
        """Get and parse blob metadata"""
        try:
            metadata = self.redis.hgetall(f"blob:{blob_id}")
            logger.debug(f"Retrieved raw metadata for blob {blob_id}: {metadata}")
            if not metadata:
                return None

            # Parse JSON strings back to Python objects
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

    def _get_available_node_for_blob(self, metadata: dict) -> str:
        """Get an available node that has the blob"""
        successful_nodes = metadata.get("successful_nodes", [])
        if not successful_nodes:
            logger.error("No nodes found for blob")
            raise HTTPException(
                status_code=404, detail="No nodes available with this blob"
            )

        # Get active nodes
        active_nodes = self.get_active_nodes()

        # Find first available node that has the blob
        for node_id in successful_nodes:
            if node_id in active_nodes:
                return node_id

        logger.error("No active nodes found with the blob")
        raise HTTPException(
            status_code=503, detail="No active nodes available with this blob"
        )

    async def _retrieve_blob_from_node(
        self, blob_id: str, node_id: str, metadata: dict
    ):
        """Retrieve blob from specified node"""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"http://storage_node_{node_id}:8001/blob/{blob_id}",
                    follow_redirects=True,
                )

                if response.status_code != 200:
                    logger.error(
                        f"Storage node {node_id} returned status {response.status_code}"
                    )
                    raise HTTPException(
                        status_code=500,
                        detail=f"Failed to retrieve blob from node {node_id}",
                    )

                return StreamingResponse(
                    content=response.iter_bytes(),
                    media_type=metadata.get("content_type", "application/octet-stream"),
                    headers={
                        "Content-Disposition": f"attachment; filename={metadata.get('original_filename', 'download')}"
                    },
                )

        except httpx.RequestError as e:
            logger.error(f"Request to storage node failed: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to communicate with storage node: {str(e)}",
            )

    def get_active_nodes(self) -> List[str]:
        """Get list of active storage nodes"""
        try:
            active_nodes = []
            nodes = self.redis.hgetall("storage_nodes")
            logger.info(f"Raw nodes data from Redis: {nodes}")

            current_time = datetime.now()
            for node_id, node_data in nodes.items():
                try:
                    node = json.loads(node_data)
                    logger.info(f"Processing node {node_id}: {node}")

                    last_heartbeat = datetime.fromisoformat(node["last_heartbeat"])
                    time_since_heartbeat = (
                        current_time - last_heartbeat
                    ).total_seconds()

                    logger.info(f"Time since last heartbeat: {time_since_heartbeat}s")

                    is_active = (
                        time_since_heartbeat < settings.NODE_TIMEOUT
                        and node.get("status") == "active"
                    )

                    if is_active:
                        active_nodes.append(node_id)
                    else:
                        logger.info(
                            f"Node {node_id} is inactive: timeout={time_since_heartbeat}s, status={node.get('status')}"
                        )

                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse node info for {node_id}: {e}")
                except KeyError as e:
                    logger.error(
                        f"Missing required field in node info for {node_id}: {e}"
                    )

            logger.info(f"Found {len(active_nodes)} active nodes: {active_nodes}")
            return active_nodes
        except Exception as e:
            logger.error(f"Error getting active nodes: {e}")
            return []

    def _is_node_active(self, node: dict) -> bool:
        """Check if a node is active"""
        try:
            last_heartbeat = datetime.fromisoformat(node["last_heartbeat"])
            time_since_heartbeat = (datetime.now() - last_heartbeat).total_seconds()

            # Node is considered active if heartbeat is within the timeout period
            # and status is "active"
            is_active = (
                time_since_heartbeat < settings.NODE_TIMEOUT
                and node.get("status") == "active"
            )

            if not is_active:
                logger.debug(
                    f"Node {node.get('node_id')} is inactive: "
                    f"last heartbeat {time_since_heartbeat}s ago, "
                    f"status: {node.get('status')}"
                )

            return is_active
        except (KeyError, ValueError) as e:
            logger.error(f"Error checking node status: {e}")
            return False

    def register_node(self):
        """Register this node with the coordinator"""
        try:
            node_info = NodeInfo(
                node_id=self.node_id,
                storage_dir=self.storage_dir,
                available_space=get_available_space(self.storage_dir),
                status="active",
                last_heartbeat=datetime.now(),
            )
            # Add debug logging
            logger.info(f"Attempting to register node with info: {node_info.dict()}")
            logger.info(f"Redis connection status: {self.redis.ping()}")

            self.redis.hset("storage_nodes", self.node_id, node_info.json())
            logger.info(f"Node {self.node_id} registered successfully")

            # Verify registration
            stored_info = self.redis.hget("storage_nodes", self.node_id)
            logger.info(f"Stored node info: {stored_info}")
        except Exception as e:
            logger.error(f"Failed to register node: {str(e)}", exc_info=True)
            raise
