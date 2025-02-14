#!/bin/bash

# Exit on any error
set -e

# Get the project root directory
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Configuration
COMPOSE_FILE="${PROJECT_ROOT}/docker-compose.yml"
COMPOSE_DEV_FILE="${PROJECT_ROOT}/docker-compose.dev.yml"
BASE_DOCKERFILE="${PROJECT_ROOT}/docker/Dockerfile.base"
COORDINATOR_DOCKERFILE="${PROJECT_ROOT}/docker/Dockerfile.coordinator"
STORAGE_NODE_DOCKERFILE="${PROJECT_ROOT}/docker/Dockerfile.storage_node"
BASE_IMAGE_NAME="distributed-blob-storage-base"
BUILD_MODE="${BUILD_MODE:-production}" # Can be 'production' or 'development'

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Helper functions
log_info() {
    echo -e "${GREEN}INFO: ${1}${NC}"
}

log_warning() {
    echo -e "${YELLOW}WARNING: ${1}${NC}"
}

log_error() {
    echo -e "${RED}ERROR: ${1}${NC}"
}

check_required_files() {
    local missing_files=0

    # Array of required files
    local required_files=(
        "$BASE_DOCKERFILE"
        "$COORDINATOR_DOCKERFILE"
        "$STORAGE_NODE_DOCKERFILE"
        "${PROJECT_ROOT}/requirements.txt"
        "$COMPOSE_FILE"
    )

    for file in "${required_files[@]}"; do
        if [ ! -f "$file" ]; then
            log_error "Required file not found: $file"
            missing_files=1
        fi
    done

    if [ $missing_files -eq 1 ]; then
        log_error "Missing required files. Please check the project structure."
        exit 1
    fi
}

check_docker() {
    if ! command -v docker &> /dev/null; then
        log_error "Docker is not installed or not in PATH"
        exit 1
    fi

    if ! docker info &> /dev/null; then
        log_error "Docker daemon is not running"
        exit 1
    fi
}

build_images() {
    log_info "Building base image..."
    docker build \
        --no-cache \
        -t "$BASE_IMAGE_NAME" \
        -f "$BASE_DOCKERFILE" \
        "${PROJECT_ROOT}"

    log_info "Building service images..."
    if [ "$BUILD_MODE" = "development" ]; then
        if [ -f "$COMPOSE_DEV_FILE" ]; then
            docker compose \
                -f "$COMPOSE_FILE" \
                -f "$COMPOSE_DEV_FILE" \
                build
        else
            log_warning "Development compose file not found, using production configuration"
            docker compose \
                -f "$COMPOSE_FILE" \
                build
        fi
    else
        docker compose \
            -f "$COMPOSE_FILE" \
            build
    fi
}

main() {
    log_info "Starting build process in $BUILD_MODE mode"
    log_info "Project root: $PROJECT_ROOT"

    # Check requirements
    check_docker
    check_required_files

    # Build images
    build_images

    log_info "Build completed successfully!"
}

# Run the script
main