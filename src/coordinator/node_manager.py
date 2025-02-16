import json
import logging
from datetime import datetime
from typing import List, Optional, Dict

from fastapi import HTTPException
from redis import Redis

from src.common.config import settings

logger = logging.getLogger(__name__)


class NodeManager:
    def __init__(self, redis: Redis):
        self.redis = redis

    def get_active_nodes(self) -> List[str]:
        """Get list of active storage nodes"""
        try:
            active_nodes = []
            nodes = self.redis.hgetall("storage_nodes")
            current_time = datetime.now()

            for node_id, node_data in nodes.items():
                try:
                    node = json.loads(node_data)
                    last_heartbeat = datetime.fromisoformat(node["last_heartbeat"])
                    time_since_heartbeat = (
                        current_time - last_heartbeat
                    ).total_seconds()

                    if (
                        time_since_heartbeat < settings.NODE_TIMEOUT
                        and node.get("status") == "active"
                    ):
                        active_nodes.append(node_id)
                    else:
                        logger.debug(
                            f"Node {node_id} is inactive: "
                            f"timeout={time_since_heartbeat:.1f}s, status={node.get('status')}"
                        )

                except (json.JSONDecodeError, KeyError) as e:
                    logger.error(f"Invalid node data for node {node_id}: {str(e)}")

            if not active_nodes:
                logger.warning("No active storage nodes found")
            else:
                logger.debug(f"Active nodes: {active_nodes}")

            return active_nodes

        except Exception as e:
            logger.error(f"Error getting active nodes: {str(e)}")
            return []

    def get_node_info(self, node_id: str) -> Optional[Dict]:
        """Get information about a specific node"""
        try:
            node_data = self.redis.hget("storage_nodes", node_id)
            if not node_data:
                return None
            return json.loads(node_data)
        except Exception as e:
            logger.error(f"Failed to get node info for {node_id}: {str(e)}")
            return None

    def get_available_node_for_blob(self, metadata: dict) -> str:
        """Get an available node that has the blob"""
        successful_nodes = metadata.get("successful_nodes", [])
        if not successful_nodes:
            logger.error("No nodes found with blob")
            raise HTTPException(
                status_code=404, detail="No nodes available with this blob"
            )

        active_nodes = self.get_active_nodes()

        for node_id in successful_nodes:
            if node_id in active_nodes:
                logger.info(
                    f"Using node {node_id} for retrieval (active nodes: {active_nodes})"
                )
                return node_id

        logger.error(f"No active nodes among {successful_nodes}")
        raise HTTPException(
            status_code=503, detail="No active nodes available with this blob"
        )
