#!/bin/bash
set -e

# Run database migrations on startup (Celery also needs DB access)
echo "Running database migrations..."
python manage.py migrate --noinput || {
    echo "WARNING: Migrations failed, but continuing..."
}

# Create admin user if needed (optional)
if [ -n "$ADMIN_EMAIL" ]; then
    echo "Creating/updating admin user: $ADMIN_EMAIL"
    python create_admin_user.py || echo "WARNING: Failed to create admin user"
fi

# Start Celery worker
echo "Starting Celery worker..."
exec celery -A grants_aggregator worker -l info

