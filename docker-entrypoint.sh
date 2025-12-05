#!/bin/bash
set -e

# Detect which service this is
if [ "$RAILWAY_SERVICE_NAME" = "celery" ] || [ "$CELERY_WORKER" = "true" ]; then
    echo "=========================================="
    echo "Detected Celery service, starting worker..."
    echo "RAILWAY_SERVICE_NAME: ${RAILWAY_SERVICE_NAME:-not set}"
    echo "CELERY_WORKER: ${CELERY_WORKER:-not set}"
    echo "=========================================="
    exec /app/celery_entrypoint.sh
else
    echo "=========================================="
    echo "Detected Web service, starting Gunicorn..."
    echo "RAILWAY_SERVICE_NAME: ${RAILWAY_SERVICE_NAME:-not set}"
    echo "=========================================="
    exec /app/entrypoint.sh
fi

