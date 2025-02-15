# scripts/run_coordinator.py
import uvicorn

from src.coordinator.api import app

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
