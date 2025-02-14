# src/coordinator/coordinator.py
from fastapi import UploadFile, HTTPException
import hashlib
import uuid
from datetime import datetime
import json
from redis import Redis
from ..common.config import settings
import logging
import httpx
from fastapi import UploadFile, HTTPException
from fastapi.responses import StreamingResponse
import hashlib
import uuid
from datetime import datetime
import json
from redis import Redis
from ..common.config import settings
import logging
import httpx
from io import BytesIO

logger = logging.getLogger(__name__)


class Coordinator:
    def __init__(self):
        try:
            self.redis = Redis(
                host=settings.REDIS_HOST,
                port=settings.REDIS_PORT,
                decode_responses=True,
            )
            # Test Redis connection
            self.redis.ping()
        except Exception as e:
            logger.error(f"Redis connection failed: {str(e)}")
            raise Exception(f"Failed to initialize Redis: {str(e)}")

    async def store_blob(self, file: UploadFile) -> dict:
        """
        Store a blob across storage nodes
        """
        try:
            # Generate unique blob ID
            blob_id = str(uuid.uuid4())
            logger.info(f"Processing upload for file: {file.filename}")

            # Get active nodes
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

    # src/coordinator/coordinator.py

    async def get_blob(self, blob_id: str):
        """
        Retrieve a blob by its ID
        """
        try:
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

    def get_active_nodes(self) -> list:
        """Get list of active storage nodes"""
        try:
            nodes = []
            node_data = self.redis.hgetall("storage_nodes")
            logger.info(f"Found {len(node_data)} storage nodes")

            for node_info in node_data.values():
                try:
                    node = json.loads(node_info)
                    if self._is_node_active(node):
                        nodes.append(node["node_id"])
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse node info: {e}")
                except KeyError as e:
                    logger.error(f"Missing required field in node info: {e}")

            logger.info(f"Found {len(nodes)} active nodes")
            return nodes
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
