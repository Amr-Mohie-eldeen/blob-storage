# scripts/run_storage_node.py
import uvicorn
import os
import sys
from src.storage_node.api import app

if __name__ == "__main__":
    node_id = sys.argv[1]
    os.environ["NODE_ID"] = node_id
    uvicorn.run(app, host="0.0.0.0", port=8000 + int(node_id))
