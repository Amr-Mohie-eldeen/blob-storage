# Distributed Blob Storage System

A simple implementation of blob storage an attempt to learn about systems engineering

## Repository Structure

```
.
├── api-collection
│   └── Blob-storage
│       └── bruno.json
├── docker-compose.dev.yml
├── docker-compose.yml
├── pyproject.toml
├── README.md
├── requirements.txt
├── scripts
│   ├── docker-build.sh
│   ├── healthcheck.py
│   ├── run_coordinator.py
│   └── run_storage_node.py
└── src
    ├── common
    │   ├── config.py
    │   ├── exceptions.py
    │   └── utils.py
    ├── coordinator
    │   ├── api.py
    │   └── coordinator.py
    ├── models
    │   └── schemas.py
    └── storage_node
        ├── api.py
        └── node.py
```

### Key Files:

- `docker-compose.yml`: Defines the production Docker services for the system.
- `docker-compose.dev.yml`: Defines the development Docker services with additional volume mounts and debug settings.
- `requirements.txt`: Lists all Python dependencies for the project.
- `scripts/docker-build.sh`: Shell script for building Docker images.
- `scripts/run_coordinator.py`: Entry point for the coordinator service.
- `scripts/run_storage_node.py`: Entry point for the storage node service.
- `src/coordinator/api.py`: FastAPI application for the coordinator service.
- `src/storage_node/api.py`: FastAPI application for the storage node service.
- `src/coordinator/coordinator.py`: Core logic for the coordinator service.
- `src/storage_node/node.py`: Core logic for the storage node service.

### Important Integration Points:

- Redis: Used for metadata storage and node management.
- FastAPI: Provides the RESTful API for both coordinator and storage nodes.
- Docker: Used for containerization and deployment of services.

## Usage Instructions

### Installation

Prerequisites:
- Docker (version 19.03 or later)
- Docker Compose (version 1.27 or later)
- Python 3.8 or later (for local development)

To set up the Distributed Blob Storage System:

1. Clone the repository:
   ```
   git clone <repository_url>
   cd distributed-blob-storage
   ```

2. Build the Docker images:
   ```
   make build
   ```

3. Start the services:
   ```
   make up
   ```

### Getting Started

Once the services are up and running, you can interact with the system using the provided API endpoints:

1. Upload a blob:
   ```
   curl -X POST -F "file=@/path/to/your/file" http://localhost:8000/upload
   ```

2. Retrieve a blob:
   ```
   curl -O -J http://localhost:8000/blob/<file_name>
   ```

### Configuration Options

The system can be configured using environment variables or by modifying the `src/common/config.py` file. Key configuration options include:

- `REDIS_HOST`: Hostname of the Redis server (default: "redis")
- `REDIS_PORT`: Port of the Redis server (default: 6379)
- `BASE_STORAGE_PATH`: Base path for blob storage on nodes (default: "/data")
- `NODE_HEARTBEAT_INTERVAL`: Interval for node heartbeats in seconds (default: 30)
- `NODE_TIMEOUT`: Timeout for considering a node inactive in seconds (default: 90)

### Testing & Quality

To run the test suite:

1. Install development dependencies:
   ```
   pip install -r requirements.txt
   ```

2. Run the tests:
   ```
   pytest
   ```

### Troubleshooting

Common issues and solutions:

1. Problem: Services fail to start
   - Error message: "Error starting userland proxy: listen tcp 0.0.0.0:6379: bind: address already in use"
   - Solution: Stop any running Redis instances or change the Redis port in `docker-compose.yml`

2. Problem: Unable to connect to Redis
   - Error message: "Redis connection failed: Error 111 connecting to redis:6379. Connection refused."
   - Solution: Ensure Redis service is running and accessible. Check Redis logs for any startup issues.

3. Problem: Blob upload fails
   - Error message: "HTTPException: 500 Internal Server Error: Upload failed"
   - Solution: Check coordinator logs for detailed error messages. Ensure storage nodes are running and have sufficient disk space.

Debugging:
- Enable debug mode by setting the `DEBUG` environment variable to 1 in `docker-compose.yml` or `docker-compose.dev.yml`
- Check service logs using `docker-compose logs <service_name>`
- For more verbose logging, modify the logging configuration in `src/common/config.py`

Performance optimization:
- Monitor Redis performance using `redis-cli info`
- Use `docker stats` to monitor container resource usage
- Consider adding more storage nodes for improved performance and fault tolerance

## Data Flow

The Distributed Blob Storage System handles data flow in the following manner:

1. Client sends a blob upload request to the coordinator service.
2. Coordinator selects an available storage node.
3. Coordinator forwards the blob to the selected storage node.
4. Storage node stores the blob and returns metadata.
5. Coordinator stores metadata in Redis and returns confirmation to the client.

For retrieval:
1. Client requests a blob from the coordinator.
2. Coordinator looks up blob metadata in Redis.
3. Coordinator requests the blob from the appropriate storage node.
4. Storage node returns the blob to the coordinator.
5. Coordinator streams the blob back to the client.

```
Client -> Coordinator -> Storage Node
  ^                         |
  |                         |
  +-------------------------+
```

Note: Future versions will implement data replication across multiple storage nodes for improved fault tolerance.

## Deployment

### Prerequisites

- A Docker-capable host machine or cluster
- Access to a Redis instance (can be deployed as part of the stack)

### Deployment Steps

1. Ensure all configuration files are properly set up (`docker-compose.yml`, environment variables).
2. Build the Docker images using the provided script:
   ```
   ./scripts/docker-build.sh
   ```
3. Deploy the stack using Docker Compose:
   ```
   docker-compose up -d
   ```
4. Verify all services are running:
   ```
   docker-compose ps
   ```

### Environment Configurations

- Production: Use `docker-compose.yml`
- Development: Use `docker-compose.yml` and `docker-compose.dev.yml` together

### Monitoring Setup

- Use Docker's built-in health checks (defined in Dockerfiles)
- Implement additional monitoring using tools like Prometheus and Grafana
- Set up log aggregation using ELK stack or similar solutions

## Infrastructure

The Distributed Blob Storage System uses Docker Compose to define and manage its infrastructure. Key resources include:

### Services

- redis:
  - Type: Redis database
  - Purpose: Metadata storage and node management

- coordinator:
  - Type: Custom service (FastAPI application)
  - Purpose: Manages blob distribution and retrieval

- storage_node_1:
  - Type: Custom service (FastAPI application)
  - Purpose: Stores and serves blob data

### Networks

- blob_network:
  - Type: Docker bridge network
  - Purpose: Enables communication between services

### Volumes

- redis_data:
  - Type: Docker volume
  - Purpose: Persistent storage for Redis data

- coordinator_data:
  - Type: Docker volume
  - Purpose: Persistent storage for coordinator service

- storage_node_1_data:
  - Type: Docker volume
  - Purpose: Persistent storage for blob data on storage node 1