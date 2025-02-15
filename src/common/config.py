# src/common/config.py
import os
from typing import Any, Dict

import yaml
from pydantic import BaseSettings


class Settings(BaseSettings):
    REDIS_HOST: str = os.getenv("REDIS_HOST", "localhost")
    REDIS_PORT: int = int(os.getenv("REDIS_PORT", "6379"))
    REPLICATION_FACTOR: int = int(os.getenv("REPLICATION_FACTOR", "3"))
    NODE_HEARTBEAT_INTERVAL: int = int(os.getenv("NODE_HEARTBEAT_INTERVAL", "10"))
    NODE_TIMEOUT: int = int(os.getenv("NODE_TIMEOUT", "30"))
    BASE_STORAGE_PATH: str = os.getenv("BASE_STORAGE_PATH", "data")
    DEBUG: bool = os.getenv("DEBUG", "0") == "1"

    NODE_TIMEOUT: int = 30

    class Config:
        env_file = ".env"


def load_yaml_config(config_path: str) -> Dict[str, Any]:
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


settings = Settings()
