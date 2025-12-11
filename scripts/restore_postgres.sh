#!/bin/bash
# Script to restore PostgreSQL database dump locally
# Usage: ./scripts/restore_postgres.sh <dump_file>

set -e

if [ -z "$1" ]; then
    echo "ERROR: No dump file specified"
    echo ""
    echo "Usage: ./scripts/restore_postgres.sh <dump_file>"
    echo ""
    echo "Examples:"
    echo "  ./scripts/restore_postgres.sh backups/railway_postgres_20231211_120000.sql"
    echo "  ./scripts/restore_postgres.sh backups/railway_postgres_20231211_120000.dump"
    exit 1
fi

DUMP_FILE="$1"

if [ ! -f "$DUMP_FILE" ]; then
    echo "ERROR: Dump file not found: ${DUMP_FILE}"
    exit 1
fi

echo "=========================================="
echo "Restoring PostgreSQL Database"
echo "=========================================="
echo "Dump file: ${DUMP_FILE}"
echo ""

# Check if using Docker Compose
# First check if docker-compose.yml.local exists
USE_DOCKER_COMPOSE=false

if [ -f "docker-compose.yml.local" ]; then
    # Check if db container exists (running or stopped)
    if docker compose -f docker-compose.yml.local ps db 2>/dev/null | grep -qE "(Up|Exit)"; then
        USE_DOCKER_COMPOSE=true
    elif [ -f ".env" ] && grep -q "sqlite" .env 2>/dev/null; then
        # If DATABASE_URL is SQLite, use Docker Compose
        USE_DOCKER_COMPOSE=true
        echo "Detected SQLite in DATABASE_URL, using Docker Compose instead"
        echo "Starting Docker Compose services..."
        docker compose -f docker-compose.yml.local up -d db
        echo "Waiting for database to be ready..."
        sleep 5
    fi
fi

if [ "$USE_DOCKER_COMPOSE" = true ]; then
    echo "Detected Docker Compose database"
    echo ""
    
    # Ensure container is running
    if ! docker compose -f docker-compose.yml.local ps db 2>/dev/null | grep -q "Up"; then
        echo "Starting Docker Compose database container..."
        docker compose -f docker-compose.yml.local up -d db
        echo "Waiting for database to be ready..."
        # Wait up to 30 seconds for database to be ready
        for i in {1..30}; do
            if docker compose -f docker-compose.yml.local exec -T db pg_isready -U postgres >/dev/null 2>&1; then
                echo "Database is ready!"
                break
            fi
            if [ $i -eq 30 ]; then
                echo "ERROR: Database failed to start after 30 seconds"
                docker compose -f docker-compose.yml.local logs db | tail -20
                exit 1
            fi
            sleep 1
        done
    fi
    
    # Drop and recreate database
    echo "Dropping existing database (if exists)..."
    docker compose -f docker-compose.yml.local exec -T db psql -U postgres -d postgres -c "DROP DATABASE IF EXISTS grants_aggregator;" || true
    docker compose -f docker-compose.yml.local exec -T db psql -U postgres -d postgres -c "CREATE DATABASE grants_aggregator;"
    
    echo "Restoring database..."
    
    # Check if it's a custom format dump (.dump) or SQL (.sql)
    if [[ "$DUMP_FILE" == *.dump ]]; then
        # Custom format - use pg_restore
        cat "$DUMP_FILE" | docker compose -f docker-compose.yml.local exec -T db pg_restore -U postgres -d grants_aggregator --clean --if-exists
    else
        # SQL format - use psql
        cat "$DUMP_FILE" | docker compose -f docker-compose.yml.local exec -T db psql -U postgres -d grants_aggregator
    fi
else
    # Local PostgreSQL
    echo "Using local PostgreSQL"
    echo ""
    
    # Check if DATABASE_URL is set and is PostgreSQL (not SQLite)
    if [ -z "$DATABASE_URL" ]; then
        echo "ERROR: DATABASE_URL environment variable is not set"
        echo "Please set it in your .env file"
        exit 1
    fi
    
    if [[ "$DATABASE_URL" == sqlite* ]]; then
        echo "ERROR: DATABASE_URL is set to SQLite, but we need PostgreSQL to restore."
        echo "Please either:"
        echo "  1. Start Docker Compose: docker compose -f docker-compose.yml.local up -d db"
        echo "  2. Or set DATABASE_URL to a PostgreSQL connection string"
        exit 1
    fi
    
    # Extract connection details to connect to postgres database for drop/create
    # Parse DATABASE_URL to get base connection (without database name)
    BASE_URL="${DATABASE_URL%/*}"
    if [ "$BASE_URL" == "$DATABASE_URL" ]; then
        # No database specified, use postgres
        BASE_URL="${DATABASE_URL}/postgres"
    else
        BASE_URL="${BASE_URL}/postgres"
    fi
    
    # Drop and recreate database
    echo "Dropping existing database (if exists)..."
    psql "$BASE_URL" -c "DROP DATABASE IF EXISTS grants_aggregator;" || true
    psql "$BASE_URL" -c "CREATE DATABASE grants_aggregator;"
    
    echo "Restoring database..."
    
    # Check if it's a custom format dump (.dump) or SQL (.sql)
    if [[ "$DUMP_FILE" == *.dump ]]; then
        # Custom format - use pg_restore
        pg_restore -d "$DATABASE_URL" --clean --if-exists "$DUMP_FILE"
    else
        # SQL format - use psql
        psql "$DATABASE_URL" < "$DUMP_FILE"
    fi
fi

echo ""
echo "=========================================="
echo "Restore completed successfully!"
echo "=========================================="

