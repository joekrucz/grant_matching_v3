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

# Expose port
EXPOSE 8000

# Use environment variable PORT if available (for Railway/Render), otherwise default to 8000
# Default command uses gunicorn for production
# Use exec form with shell to ensure PORT variable expansion works
CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:${PORT:-8000} --workers 3 --timeout 120 grants_aggregator.wsgi:application"]

