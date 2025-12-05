#!/bin/bash
set -e

# Get PORT from environment variable, default to 8000 if not set
PORT=${PORT:-8000}

echo "Starting scraper service on port $PORT"

# Start uvicorn
exec uvicorn app.main:app --host 0.0.0.0 --port $PORT

