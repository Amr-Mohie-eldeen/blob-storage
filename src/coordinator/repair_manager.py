import logging
from typing import List

from .metadata_manager import MetadataManager
from .node_manager import NodeManager
from .blob_storage import BlobStorage

logger = logging.getLogger(__name__)


class RepairManager:
    def __init__(
        self,
        metadata_manager: MetadataManager,
        node_manager: NodeManager,
        blob_storage: BlobStorage,
    ):
        self.metadata_manager = metadata_manager
        self.node_manager = node_manager
        self.blob_storage = blob_storage

    async def trigger_auto_repair(self, blob_id: str) -> None:
        """Initiates automatic repair process for a blob."""
        try:
            metadata = self.metadata_manager.get_blob_metadata(blob_id)
            if not metadata:
                logger.error(f"No metadata found for blob {blob_id}")
                return

            successful_nodes = set(metadata.get("successful_nodes", []))
            active_nodes = set(self.node_manager.get_active_nodes())
            nodes_needing_blob = active_nodes - successful_nodes

            if not nodes_needing_blob:
                logger.debug(f"No repair needed for blob {blob_id}")
                return

            logger.info(
                f"Auto-repair needed for blob {blob_id} on nodes {nodes_needing_blob}"
            )
            await self._repair_blob(
                blob_id, list(successful_nodes)[0], list(nodes_needing_blob)
            )

        except Exception as e:
            logger.error(f"Auto-repair failed for blob {blob_id}: {str(e)}")

    async def _repair_blob(
        self, blob_id: str, source_node: str, target_nodes: List[str]
    ) -> None:
        """Copies a blob from a source node to target nodes."""
        try:
            # Get the blob from source node
            source_response = await self.blob_storage.get_blob_from_node(
                source_node, blob_id
            )
            content = b""
            async for chunk in source_response.body_iterator:
                content += chunk

            # Get metadata for content type and filename
            metadata = self.metadata_manager.get_blob_metadata(blob_id)
            if not metadata:
                raise Exception(f"No metadata found for blob {blob_id}")

            # Store on target nodes
            for target_node in target_nodes:
                try:
                    await self.blob_storage.store_blob_on_node(
                        target_node,
                        blob_id,
                        content,
                        metadata.get("original_filename", "repaired_file"),
                        metadata.get("content_type", "application/octet-stream"),
                    )
                    logger.info(
                        f"Successfully repaired blob {blob_id} on node {target_node}"
                    )

                    # Update metadata
                    current_metadata = self.metadata_manager.get_blob_metadata(blob_id)
                    if current_metadata:
                        if target_node not in current_metadata["successful_nodes"]:
                            current_metadata["successful_nodes"].append(target_node)
                        if target_node in current_metadata.get("failed_nodes", []):
                            current_metadata["failed_nodes"].remove(target_node)
                        self.metadata_manager.store_metadata(blob_id, current_metadata)

                except Exception as e:
                    logger.error(
                        f"Failed to repair blob {blob_id} on node {target_node}: {str(e)}"
                    )

        except Exception as e:
            logger.error(f"Repair operation failed for blob {blob_id}: {str(e)}")
