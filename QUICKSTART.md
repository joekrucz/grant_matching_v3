# Quick Start Guide

## Step 1: Create Environment File

Create a `.env` file in the project root with these minimum required variables:

```bash
# Django Settings
SECRET_KEY=your-secret-key-here-change-this
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1

# Database (Docker will use these)
DATABASE_URL=postgresql://postgres:postgres@db:5432/grants_aggregator

# Redis
REDIS_URL=redis://redis:6379/0

# Companies House API (optional for basic testing)
COMPANIES_HOUSE_API_KEY=your-key-here

# Scraper Service
PYTHON_SCRAPER_URL=http://python-scraper:8000
SCRAPER_API_KEY=your-scraper-api-key-here

# Django API URL (for scraper service)
DJANGO_API_URL=http://web:8000

# Email (console backend for development)
EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
```

**Quick way to generate SECRET_KEY:**
```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

## Step 2: Launch with Docker Compose

```bash
# Build and start all services
docker-compose up --build
```

This will start:
- PostgreSQL database
- Redis
- Django web server (port 8000)
- Celery worker
- Python scraper service (port 8001)

## Step 3: Initialize Database

In a new terminal, run:

```bash
# Run migrations
docker-compose exec web python manage.py migrate

# Create admin user
docker-compose exec web python manage.py createsuperuser
```

## Step 4: Access the Application

- **Main App**: http://localhost:8000
- **Django Admin**: http://localhost:8000/admin
- **Scraper API**: http://localhost:8001/health

## Alternative: Local Development (without Docker)

If you prefer to run locally:

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Set up PostgreSQL** locally and update `DATABASE_URL` in `.env`

3. **Run migrations:**
   ```bash
   python manage.py migrate
   ```

4. **Create superuser:**
   ```bash
   python manage.py createsuperuser
   ```

5. **Start Django server:**
   ```bash
   python manage.py runserver
   ```

6. **Start Celery worker** (in separate terminal):
   ```bash
   celery -A grants_aggregator worker -l info
   ```

## First Steps After Launch

1. **Sign up** at http://localhost:8000/users/sign_up
2. **Check terminal** for email confirmation link (console backend)
3. **Sign in** and explore the app
4. **Add a company** (requires Companies House API key)
5. **Browse grants** (requires authentication)

## Stopping the App

Press `Ctrl+C` in the terminal running `docker-compose up`, or:

```bash
docker-compose down
```

To also remove volumes (database data):
```bash
docker-compose down -v
```

