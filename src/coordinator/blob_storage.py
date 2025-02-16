import json
import logging

import httpx
from fastapi import HTTPException
from fastapi.responses import StreamingResponse

from .metadata_manager import MetadataManager
from .node_manager import NodeManager

logger = logging.getLogger(__name__)


class BlobStorage:
    def __init__(self, metadata_manager: MetadataManager, node_manager: NodeManager):
        self.metadata_manager = metadata_manager
        self.node_manager = node_manager

    async def store_blob_on_node(
        self,
        node_id: str,
        blob_id: str,
        content: bytes,
        filename: str,
        content_type: str,
    ) -> dict:
        """Store blob on a specific node"""
        try:
            # Get node info including port
            node_info = self.node_manager.get_node_info(node_id)
            if not node_info:
                raise Exception(f"Node info not found for {node_id}")

            # Parse node info if it's a string
            if isinstance(node_info, str):
                node_info = json.loads(node_info)

            node_port = node_info.get("listen_port", 8001)

            async with httpx.AsyncClient(timeout=30.0) as client:
                files = {"file": (filename, content, content_type)}
                url = f"http://storage_node_{node_id}:{node_port}/blob/{blob_id}"

                response = await client.post(url, files=files)
                logger.info(
                    f'HTTP Request: POST {url} "{response.status_code} {response.reason_phrase}"'
                )

                if response.status_code == 200:
                    result = response.json()
                    result["node_id"] = node_id
                    return result

                logger.error(
                    f"Storage node {node_id} failed with status {response.status_code}: {response.text}"
                )
                raise Exception(f"Upload failed with status {response.status_code}")

        except Exception as e:
            logger.error(f"Failed to store blob on node {node_id}: {str(e)}")
            raise Exception(f"Upload failed for node_id={node_id}: {str(e)}")

    async def get_blob_from_node(self, node_id: str, blob_id: str) -> StreamingResponse:
        """Retrieve blob from specified node"""
        try:
            node_info = self.node_manager.get_node_info(node_id)
            if not node_info:
                raise HTTPException(status_code=404, detail=f"Node {node_id} not found")

            # Parse node info if it's a string
            if isinstance(node_info, str):
                node_info = json.loads(node_info)

            node_port = node_info.get("listen_port", 8001)
            url = f"http://storage_node_{node_id}:{node_port}/blob/{blob_id}"

            logger.info(f"Retrieving blob from node {node_id} at port {node_port}")

            async with httpx.AsyncClient(timeout=30.0) as client:
                try:
                    response = await client.get(url, follow_redirects=True)
                    logger.info(
                        f'HTTP Request: GET {url} "{response.status_code} {response.reason_phrase}"'
                    )

                    if response.status_code != 200:
                        logger.error(
                            f"Node {node_id} returned {response.status_code}: {response.text}"
                        )
                        raise HTTPException(
                            status_code=500,
                            detail=f"Failed to retrieve from node {node_id}",
                        )

                    logger.info(f"Successfully retrieved blob from node {node_id}")

                    # Get metadata for content type and filename
                    metadata = self.metadata_manager.get_blob_metadata(blob_id)

                    return StreamingResponse(
                        content=response.iter_bytes(),
                        media_type=metadata.get(
                            "content_type", "application/octet-stream"
                        ),
                        headers={
                            "Content-Disposition": f"attachment; filename={metadata.get('original_filename', 'download')}",
                            "Content-Length": response.headers.get(
                                "content-length", ""
                            ),
                        },
                    )

                except httpx.RequestError as e:
                    logger.error(f"Connection failed to node {node_id}: {str(e)}")
                    raise HTTPException(
                        status_code=500,
                        detail=f"Failed to communicate with node {node_id}",
                    )

        except Exception as e:
            logger.error(f"Error retrieving from node {node_id}: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))
