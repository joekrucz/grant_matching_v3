#!/bin/bash
set -e

# Get PORT from environment variable, default to 8000 if not set
PORT=${PORT:-8000}

# Debug: Log environment variables (without sensitive data)
echo "Starting with PORT=$PORT"
if [ -n "$REDIS_URL" ]; then
    echo "REDIS_URL is set (length: ${#REDIS_URL})"
else
    echo "WARNING: REDIS_URL is not set, using default"
fi

# Run database migrations on startup
echo "Running database migrations..."
python manage.py migrate --noinput || {
    echo "WARNING: Migrations failed, but continuing startup..."
}

# Start Gunicorn
exec gunicorn --bind 0.0.0.0:$PORT --workers 3 --timeout 120 grants_aggregator.wsgi:application

