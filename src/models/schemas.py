# src/models/schemas.py
from pydantic import BaseModel
from datetime import datetime
from typing import List, Optional


class NodeInfo(BaseModel):
    node_id: str
    storage_dir: str
    available_space: int
    status: str
    last_heartbeat: datetime


class BlobMetadata(BaseModel):
    blob_id: str
    original_filename: str
    content_type: str
    size: int
    checksum: str
    created_at: datetime
    nodes: List[str]

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}


class UploadResponse(BaseModel):
    blob_id: str
    stored_nodes: List[str]
    size: int
    checksum: str


class StorageNodeStatus(BaseModel):
    status: str
    available_space: int
    blob_count: int
    last_heartbeat: datetime
