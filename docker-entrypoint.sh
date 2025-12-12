#!/bin/bash
set -e

# Debug: Print all relevant environment variables
echo "=========================================="
echo "DOCKER ENTRYPOINT - Service Detection"
echo "RAILWAY_SERVICE_NAME: ${RAILWAY_SERVICE_NAME:-not set}"
echo "CELERY_WORKER: ${CELERY_WORKER:-not set}"
echo "START_COMMAND: ${START_COMMAND:-not set}"
echo "=========================================="

# Detect which service this is
# Check multiple ways: RAILWAY_SERVICE_NAME, CELERY_WORKER env var, or START_COMMAND
if [ "$RAILWAY_SERVICE_NAME" = "celery" ] || [ "$CELERY_WORKER" = "true" ] || [ "$START_COMMAND" = "/app/celery_entrypoint.sh" ]; then
    echo "=========================================="
    echo "Detected Celery service, starting worker..."
    echo "RAILWAY_SERVICE_NAME: ${RAILWAY_SERVICE_NAME:-not set}"
    echo "CELERY_WORKER: ${CELERY_WORKER:-not set}"
    echo "START_COMMAND: ${START_COMMAND:-not set}"
    echo "=========================================="
    exec /app/celery_entrypoint.sh
else
    echo "=========================================="
    echo "Detected Web service, starting Gunicorn..."
    echo "RAILWAY_SERVICE_NAME: ${RAILWAY_SERVICE_NAME:-not set}"
    echo "=========================================="
    exec /app/entrypoint.sh
fi

