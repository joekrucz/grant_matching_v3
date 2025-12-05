#!/bin/bash
set -e

# Get PORT from environment variable, default to 8000 if not set
PORT=${PORT:-8000}

# Start Gunicorn
exec gunicorn --bind 0.0.0.0:$PORT --workers 3 --timeout 120 grants_aggregator.wsgi:application

