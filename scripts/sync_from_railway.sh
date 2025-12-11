#!/bin/bash
# Master script to sync both PostgreSQL and Redis from Railway
# Usage: ./scripts/sync_from_railway.sh

set -e

echo "=========================================="
echo "Syncing Data from Railway Production"
echo "=========================================="
echo ""

# Load environment variables from .env if it exists
if [ -f .env ]; then
    echo "Loading environment variables from .env..."
    export $(grep -v '^#' .env | xargs)
fi

# Check for required environment variables
if [ -z "$RAILWAY_DATABASE_URL" ]; then
    echo "ERROR: RAILWAY_DATABASE_URL not set in .env"
    echo "Please add it to your .env file:"
    echo "  RAILWAY_DATABASE_URL='postgresql://user:password@host:port/database'"
    exit 1
fi

if [ -z "$RAILWAY_REDIS_URL" ]; then
    echo "ERROR: RAILWAY_REDIS_URL not set in .env"
    echo "Please add it to your .env file:"
    echo "  RAILWAY_REDIS_URL='redis://user:password@host:port/db'"
    exit 1
fi

# Make sure scripts are executable
chmod +x scripts/dump_railway_postgres.sh
chmod +x scripts/dump_railway_redis.sh
chmod +x scripts/restore_postgres.sh
chmod +x scripts/restore_redis.sh

echo "Step 1: Dumping PostgreSQL from Railway..."
./scripts/dump_railway_postgres.sh

echo ""
echo "Step 2: Dumping Redis from Railway..."
./scripts/dump_railway_redis.sh

echo ""
echo "Step 3: Restoring PostgreSQL locally..."
# Get the most recent PostgreSQL dump
LATEST_POSTGRES_DUMP=$(ls -t backups/railway_postgres_*.sql backups/railway_postgres_*.dump 2>/dev/null | head -1)
if [ -n "$LATEST_POSTGRES_DUMP" ]; then
    ./scripts/restore_postgres.sh "$LATEST_POSTGRES_DUMP"
else
    echo "ERROR: No PostgreSQL dump found"
    exit 1
fi

echo ""
echo "Step 4: Restoring Redis locally..."
# Get the most recent Redis dump
LATEST_REDIS_DUMP=$(ls -t backups/railway_redis_*.rdb 2>/dev/null | head -1)
if [ -n "$LATEST_REDIS_DUMP" ]; then
    ./scripts/restore_redis.sh "$LATEST_REDIS_DUMP"
else
    echo "ERROR: No Redis dump found"
    exit 1
fi

echo ""
echo "=========================================="
echo "Sync completed successfully!"
echo "=========================================="
echo ""
echo "Your local environment now has a snapshot of production data."
echo "You can now:"
echo "  1. Use the same login credentials"
echo "  2. See the same scrape logs"
echo "  3. View all grants and companies"
echo ""
echo "To start your local environment:"
echo "  docker compose -f docker-compose.yml.local up"

