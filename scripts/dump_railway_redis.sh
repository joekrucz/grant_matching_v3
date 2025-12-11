#!/bin/bash
# Script to dump Redis database from Railway production
# Usage: ./scripts/dump_railway_redis.sh

set -e

echo "=========================================="
echo "Dumping Railway Redis Database"
echo "=========================================="

# Check if REDIS_URL is set
if [ -z "$RAILWAY_REDIS_URL" ]; then
    echo "ERROR: RAILWAY_REDIS_URL environment variable is not set"
    echo ""
    echo "Please set it in your .env file or export it:"
    echo "  export RAILWAY_REDIS_URL='redis://user:password@host:port/db'"
    echo ""
    echo "You can find this in Railway dashboard:"
    echo "  Redis Service → Connect → Public Networking → Connection String"
    exit 1
fi

# Create backups directory if it doesn't exist
mkdir -p backups

# Generate timestamp for filename
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
DUMP_FILE="backups/railway_redis_${TIMESTAMP}.rdb"

echo "Dumping Redis to: ${DUMP_FILE}"
echo "This may take a few minutes depending on database size..."
echo ""

# Parse Redis URL to extract components
# Format: redis://[username:password@]host:port[/db] or redis://[:password@]host:port[/db]
REDIS_URL=$RAILWAY_REDIS_URL

# Remove redis:// prefix
REDIS_URL=${REDIS_URL#redis://}

# Extract authentication and connection parts
if [[ $REDIS_URL == *"@"* ]]; then
    # Has authentication part
    AUTH_PART=${REDIS_URL%%@*}
    CONNECTION_PART=${REDIS_URL#*@}
    
    # Check if there's a username (format: username:password or :password)
    if [[ $AUTH_PART == *":"* ]]; then
        # Has username:password format
        USERNAME=${AUTH_PART%%:*}
        PASSWORD=${AUTH_PART#*:}
    elif [[ $AUTH_PART == ":"* ]]; then
        # Has :password format (no username)
        USERNAME=""
        PASSWORD=${AUTH_PART#:}
    else
        # Just password (no username, no colon)
        USERNAME=""
        PASSWORD=$AUTH_PART
    fi
else
    # No authentication
    CONNECTION_PART=$REDIS_URL
    USERNAME=""
    PASSWORD=""
fi

# Extract host, port, and database from connection part
HOST_PORT=${CONNECTION_PART%%/*}
DB=${CONNECTION_PART#*/}

if [[ $HOST_PORT == *":"* ]]; then
    HOST=${HOST_PORT%%:*}
    PORT=${HOST_PORT#*:}
else
    HOST=$HOST_PORT
    PORT=6379
fi

# Default to database 0 if not specified
if [ "$DB" == "$CONNECTION_PART" ]; then
    DB=0
fi

echo "Connecting to Redis:"
echo "  Host: $HOST"
echo "  Port: $PORT"
echo "  Database: $DB"
if [ -n "$USERNAME" ]; then
    echo "  Username: $USERNAME"
fi
if [ -n "$PASSWORD" ]; then
    echo "  Password: ****"
fi
echo ""

# Use redis-cli to save and copy RDB file
# Note: You may need to install redis-cli locally:
#   macOS: brew install redis
#   Ubuntu: sudo apt-get install redis-tools

# Connect and trigger BGSAVE, then wait and copy
# For Redis 6+, if username is provided, use --user and --pass
# For older Redis, just use -a for password
if [ -n "$USERNAME" ] && [ -n "$PASSWORD" ]; then
    # Redis 6+ with ACL (username + password)
    redis-cli -h "$HOST" -p "$PORT" --user "$USERNAME" --pass "$PASSWORD" -n "$DB" --rdb "$DUMP_FILE"
elif [ -n "$PASSWORD" ]; then
    # Redis with just password (no username)
    redis-cli -h "$HOST" -p "$PORT" -a "$PASSWORD" -n "$DB" --rdb "$DUMP_FILE"
else
    # No authentication
    redis-cli -h "$HOST" -p "$PORT" -n "$DB" --rdb "$DUMP_FILE"
fi

echo ""
echo "=========================================="
echo "Dump completed successfully!"
echo "=========================================="
echo "Redis dump: ${DUMP_FILE}"
echo ""
echo "To restore locally:"
echo "  ./scripts/restore_redis.sh ${DUMP_FILE}"

