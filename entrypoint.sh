#!/bin/bash
set -e

# Check if this should be running as Celery worker instead
if [ "$RAILWAY_SERVICE_NAME" = "celery" ] || [ "$CELERY_WORKER" = "true" ]; then
    echo "=========================================="
    echo "ENTRYPOINT.SH - Detected Celery service, redirecting to celery_entrypoint.sh"
    echo "RAILWAY_SERVICE_NAME: ${RAILWAY_SERVICE_NAME:-not set}"
    echo "CELERY_WORKER: ${CELERY_WORKER:-not set}"
    echo "=========================================="
    exec /app/celery_entrypoint.sh
fi

# Get PORT from environment variable, default to 8000 if not set
PORT=${PORT:-8000}

# Debug: Log environment variables (without sensitive data)
echo "WEB ENTRYPOINT - Starting Gunicorn"
echo "Starting with PORT=$PORT"
if [ -n "$REDIS_URL" ]; then
    echo "REDIS_URL is set (length: ${#REDIS_URL})"
else
    echo "WARNING: REDIS_URL is not set, using default"
fi

# Run database migrations on startup
echo "Running database migrations..."
python manage.py migrate --noinput
if [ $? -eq 0 ]; then
    echo "Migrations completed successfully"
else
    echo "ERROR: Migrations failed!"
    exit 1
fi

# Create admin user if it doesn't exist (only if ADMIN_EMAIL is set)
if [ -n "$ADMIN_EMAIL" ]; then
    echo "Creating/updating admin user: $ADMIN_EMAIL"
    python create_admin_user.py || echo "WARNING: Failed to create admin user"
fi

# Start Gunicorn
exec gunicorn --bind 0.0.0.0:$PORT --workers 3 --timeout 120 grants_aggregator.wsgi:application

