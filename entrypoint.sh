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
echo "=========================================="
echo "WEB ENTRYPOINT - Starting Gunicorn"
echo "PORT=$PORT (from environment or default)"
echo "Gunicorn will bind to: 0.0.0.0:$PORT"
echo "Health check should connect to: http://localhost:$PORT/health/"
echo "=========================================="
if [ -n "$REDIS_URL" ]; then
    echo "REDIS_URL is set (length: ${#REDIS_URL})"
else
    echo "WARNING: REDIS_URL is not set, using default"
fi

# Run database migrations on startup
# Retry migrations up to 5 times with exponential backoff if database is not ready
echo "Running database migrations..."
MAX_MIGRATION_RETRIES=5
RETRY_DELAY=5
for i in $(seq 1 $MAX_MIGRATION_RETRIES); do
    if python manage.py migrate --noinput; then
        echo "Migrations completed successfully"
        break
    else
        if [ $i -eq $MAX_MIGRATION_RETRIES ]; then
            echo "WARNING: Migrations failed after $MAX_MIGRATION_RETRIES attempts. Service will start but may have issues."
            echo "Migrations will be retried on next deployment/restart."
        else
            echo "Migrations failed (attempt $i/$MAX_MIGRATION_RETRIES). Retrying in ${RETRY_DELAY}s..."
            sleep $RETRY_DELAY
            RETRY_DELAY=$((RETRY_DELAY * 2))  # Exponential backoff
        fi
    fi
done

# Create admin user if it doesn't exist (only if ADMIN_EMAIL is set)
if [ -n "$ADMIN_EMAIL" ]; then
    echo "Creating/updating admin user: $ADMIN_EMAIL"
    python create_admin_user.py || echo "WARNING: Failed to create admin user"
fi

# Start Gunicorn
exec gunicorn --bind 0.0.0.0:$PORT --workers 3 --timeout 120 grants_aggregator.wsgi:application

