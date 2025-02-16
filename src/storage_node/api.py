# src/storage_node/api.py
import logging
import os
from typing import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile

from src.common.exceptions import BlobNotFoundError
from src.common.interfaces import IStorageNode
from src.models.schemas import UploadResponse
from src.storage_node.node import StorageNode

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for FastAPI app"""
    global storage_node
    try:
        node_id = os.getenv("NODE_ID")
        if not node_id:
            raise ValueError("NODE_ID environment variable not set")

        logger.info(f"Initializing storage node {node_id}")
        storage_node = StorageNode(node_id)
        app.port = storage_node.listen_port
        await storage_node.start()
        logger.info(f"Storage node {node_id} initialized successfully")
        yield
    finally:
        # Cleanup code here if needed
        pass


app = FastAPI(lifespan=lifespan)

# Create a global storage node instance
storage_node = None


async def get_storage_node() -> AsyncGenerator[IStorageNode, None]:
    """Dependency that provides the storage node instance"""
    if storage_node is None:
        raise HTTPException(status_code=500, detail="Storage node not initialized")
    try:
        yield storage_node
    finally:
        pass


# Add a health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint"""
    if storage_node is None:
        raise HTTPException(status_code=503, detail="Storage node not initialized")
    return {"status": "healthy", "node_id": storage_node.node_id}


@app.post("/blob/{blob_id}")
async def store_blob(
    blob_id: str,
    file: UploadFile = File(...),
    node: IStorageNode = Depends(get_storage_node),
) -> UploadResponse:
    try:
        return await node.store_blob(blob_id, file)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/blob/{blob_id}")
async def get_blob(blob_id: str, node: IStorageNode = Depends(get_storage_node)):
    try:
        return await node.get_blob(blob_id)
    except BlobNotFoundError:
        raise HTTPException(status_code=404, detail="Blob not found")
