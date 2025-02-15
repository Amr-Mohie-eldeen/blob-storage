from datetime import datetime
from typing import Dict, Any
import json
from redis import Redis
from .interfaces import IMetadataStore
from .exceptions import BlobNotFoundError


class RedisMetadataStore(IMetadataStore):
    def __init__(self, redis_client: Redis):
        self.redis = redis_client

    async def store_metadata(self, blob_id: str, metadata: Dict[str, Any]) -> bool:
        try:
            self.redis.hset("blob_metadata", blob_id, json.dumps(metadata))
            return True
        except Exception as e:
            raise Exception(f"Failed to store metadata: {str(e)}")

    async def get_metadata(self, blob_id: str) -> Dict[str, Any]:
        metadata = self.redis.hget("blob_metadata", blob_id)
        if not metadata:
            raise BlobNotFoundError(f"Blob {blob_id} not found")
        return json.loads(metadata)

    async def delete_metadata(self, blob_id: str) -> bool:
        return self.redis.hdel("blob_metadata", blob_id) > 0

    def update_node_heartbeat(self, node_id: str, timestamp: datetime):
        node_info = self.get_node_info(node_id)
        if node_info:
            node_info["last_heartbeat"] = timestamp.isoformat()
            self.redis.hset("storage_nodes", node_id, json.dumps(node_info))

    def get_node_info(self, node_id: str) -> Dict[str, Any]:
        node_data = self.redis.hget("storage_nodes", node_id)
        return json.loads(node_data) if node_data else None
