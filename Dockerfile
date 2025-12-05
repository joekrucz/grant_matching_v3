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

# Use a wrapper script to detect service type
COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh

# Use wrapper script to handle service detection
ENTRYPOINT ["/app/docker-entrypoint.sh"]

