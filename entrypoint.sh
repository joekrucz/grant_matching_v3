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

# Get PORT from environment variable, default to 8080 if not set
# Railway automatically sets PORT to 8080 (or another port), but we provide a fallback
if [ -z "$PORT" ]; then
    PORT=8080
    echo "WARNING: PORT environment variable not set, using default: $PORT"
else
    # Validate PORT is a number
    if ! [[ "$PORT" =~ ^[0-9]+$ ]]; then
        echo "ERROR: PORT must be a number, got: '$PORT'"
        exit 1
    fi
    echo "Using PORT from Railway environment: $PORT"
fi

# Debug: Log environment variables (without sensitive data)
echo "WEB ENTRYPOINT - Starting Gunicorn"
echo "Starting with PORT=$PORT"
if [ -n "$REDIS_URL" ]; then
    echo "REDIS_URL is set (length: ${#REDIS_URL})"
else
    echo "WARNING: REDIS_URL is not set, using default"
fi

# Run database migrations on startup
# Allow migrations to fail gracefully if database is not ready yet
echo "Running database migrations..."
python manage.py migrate --noinput || {
    echo "WARNING: Migrations failed or database not ready. Will retry on next startup."
    # Don't exit - allow service to start and retry migrations later
}

# Create admin user if it doesn't exist (only if ADMIN_EMAIL is set)
if [ -n "$ADMIN_EMAIL" ]; then
    echo "Creating/updating admin user: $ADMIN_EMAIL"
    python create_admin_user.py || echo "WARNING: Failed to create admin user"
fi

# Start Gunicorn
exec gunicorn --bind 0.0.0.0:$PORT --workers 3 --timeout 120 grants_aggregator.wsgi:application

