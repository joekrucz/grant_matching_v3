#!/bin/bash
# Script to restore Redis database dump locally
# Usage: ./scripts/restore_redis.sh <dump_file>

set -e

if [ -z "$1" ]; then
    echo "ERROR: No dump file specified"
    echo ""
    echo "Usage: ./scripts/restore_redis.sh <dump_file>"
    echo ""
    echo "Example:"
    echo "  ./scripts/restore_redis.sh backups/railway_redis_20231211_120000.rdb"
    exit 1
fi

DUMP_FILE="$1"

if [ ! -f "$DUMP_FILE" ]; then
    echo "ERROR: Dump file not found: ${DUMP_FILE}"
    exit 1
fi

echo "=========================================="
echo "Restoring Redis Database"
echo "=========================================="
echo "Dump file: ${DUMP_FILE}"
echo ""

# Check if using Docker Compose
USE_DOCKER_COMPOSE=false

if [ -f "docker-compose.yml.local" ]; then
    # Check if redis container exists (running or stopped)
    if docker compose -f docker-compose.yml.local ps redis 2>/dev/null | grep -qE "(Up|Exit)"; then
        USE_DOCKER_COMPOSE=true
    fi
fi

if [ "$USE_DOCKER_COMPOSE" = true ]; then
    echo "Detected Docker Compose Redis running"
    echo ""
    
    # Ensure container is running first
    if ! docker compose -f docker-compose.yml.local ps redis 2>/dev/null | grep -q "Up"; then
        echo "Starting Docker Compose Redis container..."
        docker compose -f docker-compose.yml.local up -d redis
        sleep 2
    fi
    
    # Stop Redis to replace RDB file
    echo "Stopping Redis container..."
    docker compose -f docker-compose.yml.local stop redis
    
    # Copy dump file into container
    echo "Copying dump file into Redis container..."
    docker compose -f docker-compose.yml.local cp "$DUMP_FILE" redis:/data/dump.rdb
    
    # Start Redis
    echo "Starting Redis container..."
    docker compose -f docker-compose.yml.local start redis
    
    echo "Waiting for Redis to load dump..."
    sleep 2
else
    # Local Redis
    echo "Using local Redis"
    echo ""
    
    # Find Redis data directory (default locations)
    REDIS_DATA_DIR=""
    if [ -d "/usr/local/var/db/redis" ]; then
        REDIS_DATA_DIR="/usr/local/var/db/redis"
    elif [ -d "/var/lib/redis" ]; then
        REDIS_DATA_DIR="/var/lib/redis"
    elif [ -d "$HOME/.redis" ]; then
        REDIS_DATA_DIR="$HOME/.redis"
    else
        echo "ERROR: Could not find Redis data directory"
        echo "Please specify REDIS_DATA_DIR environment variable"
        exit 1
    fi
    
    echo "Redis data directory: ${REDIS_DATA_DIR}"
    
    # Stop Redis if running
    if command -v redis-cli &> /dev/null; then
        echo "Stopping Redis..."
        redis-cli SHUTDOWN SAVE 2>/dev/null || true
    fi
    
    # Copy dump file
    echo "Copying dump file to Redis data directory..."
    cp "$DUMP_FILE" "${REDIS_DATA_DIR}/dump.rdb"
    
    # Start Redis
    echo "Starting Redis..."
    if command -v brew &> /dev/null; then
        brew services start redis
    elif command -v systemctl &> /dev/null; then
        sudo systemctl start redis
    else
        echo "Please start Redis manually"
    fi
fi

echo ""
echo "=========================================="
echo "Restore completed successfully!"
echo "=========================================="
echo "Redis should now have the production data loaded"

