# Makefile
.PHONY: build build-dev up up-dev down logs test clean

# Get the current directory
PROJECT_ROOT=$(shell pwd)

# Default build mode
BUILD_MODE?=production

build:
	@echo "Building Docker images in production mode..."
	@BUILD_MODE=production bash scripts/docker-build.sh

build-dev:
	@echo "Building Docker images in development mode..."
	@BUILD_MODE=development bash scripts/docker-build.sh

up:
	@echo "Starting services in production mode..."
	@docker compose up -d

up-dev:
	@echo "Starting services in development mode..."
	@docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d

down:
	@echo "Stopping services..."
	@docker compose down

logs:
	@docker compose logs -f

test:
	@docker compose run --rm coordinator pytest

clean:
	@echo "Cleaning up..."
	@docker compose down -v
	@docker system prune -f

status:
	@docker compose ps

refresh:
	@docker compose down -v
	@make build-dev
	@make up-dev

logs:
	@docker compose logs -f
