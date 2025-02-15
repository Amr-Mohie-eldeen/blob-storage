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
from typing import List
from src.models.schemas import NodeInfo
from src.common.utils import get_available_space

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
        """
        Store a blob across storage nodes
        """
        try:
            blob_id = str(uuid.uuid4())

            logger.info(f"Processing upload for file: {file.filename}")
            self._store_file_name(file.filename, blob_id)

            active_nodes = self.get_active_nodes()
            if not active_nodes:
                logger.error("No active storage nodes available")
                raise HTTPException(
                    status_code=503, detail="No storage nodes available"
                )

            # Store on first available node (for now, later implement replication)
            node_id = active_nodes[0]
            logger.info(f"Selected node {node_id} for blob {blob_id}")

            # Store blob on node
            try:
                async with httpx.AsyncClient() as client:
                    logger.info(f"Sending blob to storage node {node_id}")
                    response = await client.post(
                        f"http://storage_node_{node_id}:8001/blob/{blob_id}",
                        files={
                            "file": (
                                file.filename,
                                await file.read(),
                                file.content_type,
                            )
                        },
                    )

                    if response.status_code != 200:
                        logger.error(
                            f"Storage node {node_id} returned status {response.status_code}: {response.text}"
                        )
                        raise HTTPException(
                            status_code=500,
                            detail=f"Failed to store blob on node {node_id}",
                        )

                    logger.info(f"Storage node response: {response.text}")
                    node_response = response.json()

            except httpx.RequestError as e:
                logger.error(f"Request to storage node failed: {str(e)}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to communicate with storage node: {str(e)}",
                )

            # Store metadata in Redis
            metadata = {
                "blob_id": blob_id,
                "original_filename": file.filename,
                "content_type": file.content_type,
                "size": str(node_response.get("size")),  # Convert to string
                "checksum": node_response.get("checksum"),
                "stored_nodes": json.dumps([node_id]),  # Serialize list to JSON string
                "created_at": datetime.now().isoformat(),
            }

            try:
                # Ensure all values are strings for Redis
                redis_metadata = {
                    key: str(value) if value is not None else ""
                    for key, value in metadata.items()
                }
                self.redis.hset(f"blob:{blob_id}", mapping=redis_metadata)
            except Exception as redis_error:
                logger.error(f"Redis error: {str(redis_error)}")
                raise HTTPException(status_code=500, detail="Failed to store metadata")

            # Return the original format for the response (deserialize stored_nodes)
            response_metadata = metadata.copy()
            response_metadata["stored_nodes"] = json.loads(metadata["stored_nodes"])
            response_metadata["size"] = int(metadata["size"])  # Convert back to int

            logger.info(f"Successfully stored blob {blob_id}")
            return {
                "message": "File uploaded successfully",
                "metadata": response_metadata,
            }

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Upload failed: {str(e)}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")

    async def get_blob(self, file_name: str):
        """
        Retrieve a blob by its ID
        """
        try:
            blob_id = self._get_blob_id_by_file_name(file_name)
            # Get metadata from Redis

            metadata = self.redis.hgetall(f"blob:{blob_id}")
            if not metadata:
                logger.error(f"Blob not found: {blob_id}")
                raise HTTPException(status_code=404, detail="Blob not found")

            # Get the nodes that have this blob
            stored_nodes = json.loads(metadata.get("stored_nodes", "[]"))
            if not stored_nodes:
                logger.error(f"No nodes found for blob: {blob_id}")
                raise HTTPException(
                    status_code=404, detail="No nodes available with this blob"
                )

            # Try to get from first available node
            node_id = stored_nodes[0]
            logger.info(f"Retrieving blob {blob_id} from node {node_id}")

            try:
                async with httpx.AsyncClient() as client:
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

                    # Return the response with appropriate headers
                    return StreamingResponse(
                        content=response.iter_bytes(),
                        media_type=metadata.get(
                            "content_type", "application/octet-stream"
                        ),
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

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error retrieving blob {blob_id}: {str(e)}", exc_info=True)
            raise HTTPException(
                status_code=500, detail=f"Failed to retrieve blob: {str(e)}"
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
