FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    postgresql-client \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . .

# Collect static files (for production)
RUN python manage.py collectstatic --noinput || true

# Copy and set up entrypoint scripts
COPY entrypoint.sh /app/entrypoint.sh
COPY celery_entrypoint.sh /app/celery_entrypoint.sh
RUN chmod +x /app/entrypoint.sh /app/celery_entrypoint.sh

# Expose port
EXPOSE 8000

# Use entrypoint script to handle PORT variable at runtime
# If RAILWAY_SERVICE_NAME is "celery", use celery entrypoint, otherwise use web entrypoint
# Also check for CELERY_WORKER env var as fallback
ENTRYPOINT ["/bin/bash", "-c", "if [ \"$RAILWAY_SERVICE_NAME\" = \"celery\" ] || [ \"$CELERY_WORKER\" = \"true\" ]; then echo 'Detected Celery service, starting worker...'; /app/celery_entrypoint.sh; else echo 'Detected Web service, starting Gunicorn...'; /app/entrypoint.sh; fi"]

