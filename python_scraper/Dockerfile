FROM python:3.12-slim

# Build arg to force cache invalidation - scraper service only
ARG CACHE_BUST=scraper-v5
ARG SERVICE_NAME=scraper

# Force cache break with a unique RUN command
RUN echo "Scraper service build - $(date)" > /tmp/build-id.txt

WORKDIR /app

# Scraper service Dockerfile - v5 (force cache break)
# This service uses python:3.12-slim and does NOT use django/manage.py
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SERVICE_TYPE=scraper

# Install system dependencies (includes Chromium + driver for Selenium if needed)
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    unzip \
    curl \
    chromium \
    chromium-driver \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY app /app/app

# Copy and set up entrypoint script
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
