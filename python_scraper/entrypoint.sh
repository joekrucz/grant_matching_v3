#!/bin/bash
set -e

# Get PORT from environment variable, default to 8000 if not set
PORT=${PORT:-8000}

echo "=========================================="
echo "SCRAPER ENTRYPOINT - Starting Uvicorn"
echo "PORT environment variable: ${PORT:-not set, using default 8000}"
echo "Starting scraper service on port $PORT"
echo "Service will be accessible at: http://scraper.railway.internal:$PORT"
echo "=========================================="

# Start uvicorn
exec uvicorn app.main:app --host 0.0.0.0 --port $PORT

