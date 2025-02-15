from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, List

from fastapi import UploadFile


class IStorageNode(ABC):
    @abstractmethod
    async def store_blob(self, blob_id: str, file: UploadFile) -> Dict[str, Any]:
        """Store a blob file and return metadata"""
        pass

    @abstractmethod
    async def get_blob(self, blob_id: str):
        """Retrieve a blob file"""
        pass

    @abstractmethod
    async def delete_blob(self, blob_id: str) -> bool:
        """Delete a blob file"""
        pass

    @abstractmethod
    def get_node_status(self) -> Dict[str, Any]:
        """Get current node status"""
        pass

    @abstractmethod
    async def start(self):
        """Start the storage node"""
        pass

    @abstractmethod
    def register_node(self):
        """Register this node with the coordinator"""
        pass


class IMetadataStore(ABC):
    @abstractmethod
    async def store_metadata(self, blob_id: str, metadata: Dict[str, Any]) -> bool:
        """Store blob metadata"""
        pass

    @abstractmethod
    async def get_metadata(self, blob_id: str) -> Dict[str, Any]:
        """Retrieve blob metadata"""
        pass

    @abstractmethod
    async def delete_metadata(self, blob_id: str) -> bool:
        """Delete blob metadata"""
        pass

    @abstractmethod
    def update_node_heartbeat(self, node_id: str, timestamp: datetime):
        """Update node heartbeat"""
        pass

    @abstractmethod
    def get_node_info(self, node_id: str) -> Dict[str, Any]:
        """Get node information"""
        pass


class ICoordinator(ABC):
    @abstractmethod
    async def store_blob(self, file: UploadFile) -> Dict[str, Any]:
        """Store a blob across storage nodes"""
        pass

    @abstractmethod
    async def get_blob(self, file_name: str):
        """Retrieve a blob by file name"""
        pass

    @abstractmethod
    def get_active_nodes(self) -> List[str]:
        """Get list of active storage nodes"""
        pass

    @abstractmethod
    def _store_file_name(self, filename: str, blob_id: str):
        """Store filename to blob_id mapping"""
        pass
