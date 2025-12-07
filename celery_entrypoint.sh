#!/bin/bash
set -e

echo "=========================================="
echo "CELERY ENTRYPOINT - Starting Celery Worker"
echo "RAILWAY_SERVICE_NAME: ${RAILWAY_SERVICE_NAME:-not set}"
echo "=========================================="

# Run database migrations on startup (Celery also needs DB access)
# Allow migrations to fail gracefully if database is not ready yet
echo "Running database migrations..."
python manage.py migrate --noinput || {
    echo "WARNING: Migrations failed or database not ready for Celery. Will retry on next startup."
    # Don't exit - allow Celery to start and retry migrations later
}

# Create admin user if needed (optional)
if [ -n "$ADMIN_EMAIL" ]; then
    echo "Creating/updating admin user: $ADMIN_EMAIL"
    python create_admin_user.py || echo "WARNING: Failed to create admin user"
fi

# Start Celery worker
echo "Starting Celery worker..."
echo "CELERY_BROKER_URL will be set from Django settings"
echo "Attempting to start Celery worker..."

# Try to start Celery worker with error handling
exec celery -A grants_aggregator worker -l info --logfile=/tmp/celery.log || {
    echo "ERROR: Celery worker failed to start!"
    echo "Check the error above for details."
    exit 1
}

