# src/storage_node/api.py
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import FileResponse
from .node import StorageNode
from ..models.schemas import BlobMetadata, UploadResponse
from ..common.exceptions import BlobNotFoundError
import os

app = FastAPI()
node: StorageNode = None


@app.on_event("startup")
async def startup_event():
    global node
    # Node ID would be passed as an environment variable
    node = StorageNode(os.getenv("NODE_ID"))
    await node.start()


@app.post("/blob/{blob_id}")
async def store_blob(blob_id: str, file: UploadFile = File(...)) -> UploadResponse:
    try:
        return await node.store_blob(blob_id, file)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/blob/{blob_id}")
async def get_blob(blob_id: str):
    try:
        return await node.get_blob(blob_id)
    except BlobNotFoundError:
        raise HTTPException(status_code=404, detail="Blob not found")
