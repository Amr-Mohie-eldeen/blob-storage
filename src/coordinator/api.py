# src/coordinator/api.py
from fastapi import FastAPI, UploadFile, File, HTTPException
from .coordinator import Coordinator
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()
coordinator = Coordinator()


@app.post("/upload")  # Remove the trailing slash
async def upload_file(file: UploadFile = File(...)):
    """Upload a file to the distributed storage"""
    try:
        result = await coordinator.store_blob(file)
        return result
    except Exception as e:
        logger.error(f"Upload failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/blob/{blob_id}")
async def get_blob(blob_id: str):
    try:
        return await coordinator.get_blob(blob_id)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))
