#!/bin/bash
# Script to dump PostgreSQL database from Railway production
# Usage: ./scripts/dump_railway_postgres.sh

set -e

echo "=========================================="
echo "Dumping Railway PostgreSQL Database"
echo "=========================================="

# Check if DATABASE_URL is set
if [ -z "$RAILWAY_DATABASE_URL" ]; then
    echo "ERROR: RAILWAY_DATABASE_URL environment variable is not set"
    echo ""
    echo "Please set it in your .env file or export it:"
    echo "  export RAILWAY_DATABASE_URL='postgresql://user:password@host:port/database'"
    echo ""
    echo "You can find this in Railway dashboard:"
    echo "  PostgreSQL Service → Connect → Public Networking → Connection String"
    exit 1
fi

# Create backups directory if it doesn't exist
mkdir -p backups

# Generate timestamp for filename
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
DUMP_FILE="backups/railway_postgres_${TIMESTAMP}.sql"
DUMP_FILE_CUSTOM="backups/railway_postgres_${TIMESTAMP}.dump"

echo "Dumping database to: ${DUMP_FILE}"
echo "This may take a few minutes depending on database size..."
echo ""

# Dump using pg_dump
# Note: You may need to install postgresql-client locally:
#   macOS: brew install postgresql
#   Ubuntu: sudo apt-get install postgresql-client
pg_dump "$RAILWAY_DATABASE_URL" > "$DUMP_FILE"

# Also create a custom format dump (smaller, faster to restore)
echo "Creating custom format dump: ${DUMP_FILE_CUSTOM}"
pg_dump -Fc "$RAILWAY_DATABASE_URL" > "$DUMP_FILE_CUSTOM"

echo ""
echo "=========================================="
echo "Dump completed successfully!"
echo "=========================================="
echo "SQL dump: ${DUMP_FILE}"
echo "Custom dump: ${DUMP_FILE_CUSTOM}"
echo ""
echo "To restore locally:"
echo "  ./scripts/restore_postgres.sh ${DUMP_FILE}"
echo "  OR"
echo "  ./scripts/restore_postgres.sh ${DUMP_FILE_CUSTOM}"

