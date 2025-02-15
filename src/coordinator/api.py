# src/coordinator/api.py
from fastapi import FastAPI, UploadFile, File, HTTPException, Depends
from src.coordinator.coordinator import Coordinator
import logging
from src.common.interfaces import ICoordinator

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()
coordinator: ICoordinator = Coordinator()


def get_coordinator() -> ICoordinator:
    """FastAPI dependency to get coordinator instance"""
    return coordinator


@app.post("/upload")
async def upload_file(
    file: UploadFile = File(...), coordinator: ICoordinator = Depends(get_coordinator)
):
    """Upload a file to all available storage nodes"""
    try:
        result = await coordinator.store_blob(file)
        return result
    except Exception as e:
        logger.error(f"Upload failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/blob/{file_name}")
async def get_blob(
    file_name: str, coordinator: ICoordinator = Depends(get_coordinator)
):
    try:
        return await coordinator.get_blob(file_name)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/nodes")
async def get_active_nodes(coordinator: ICoordinator = Depends(get_coordinator)):
    """Get information about active storage nodes"""
    try:
        active_nodes = coordinator.get_active_nodes()
        return {"active_nodes_count": len(active_nodes), "active_nodes": active_nodes}
    except Exception as e:
        logger.error(f"Failed to get active nodes: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/blob/{file_name}/status")
async def get_blob_status(
    file_name: str, coordinator: ICoordinator = Depends(get_coordinator)
):
    """Get the status of a blob's storage across nodes"""
    try:
        blob_id = coordinator._get_blob_id_by_file_name(file_name)
        if not blob_id:
            raise HTTPException(status_code=404, detail="File not found")

        metadata = coordinator._get_blob_metadata(blob_id)
        return {
            "blob_id": blob_id,
            "status": metadata.get("upload_status"),
            "successful_nodes": metadata.get("successful_nodes", []),
            "failed_nodes": metadata.get("failed_nodes", []),
            "pending_nodes": metadata.get("pending_nodes", []),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
