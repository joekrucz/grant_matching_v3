# Grants Aggregator V2

A full-stack web application for aggregating UK funding opportunities from multiple providers (UKRI, NIHR, Catapult) and matching them with companies.

## Tech Stack

- **Backend**: Django 5.x with PostgreSQL
- **Frontend**: Datastar (hypermedia-driven with declarative HTML attributes)
- **Background Jobs**: Celery with Redis
- **Authentication**: Django's built-in authentication system (with email confirmation)
- **Styling**: TailwindCSS
- **Containerization**: Docker + docker-compose
- **Python Scraper Service**: FastAPI

## Setup

### Prerequisites

- Docker and Docker Compose
- Python 3.11+ (for local development)

### Environment Variables

Copy `.env.example` to `.env` and fill in the required values:

```bash
cp .env.example .env
```

Key environment variables:
- `SECRET_KEY` - Django secret key
- `COMPANIES_HOUSE_API_KEY` - Companies House API key
- `SCRAPER_API_KEY` - API key for scraper service authentication
- `EMAIL_*` - Email configuration for sending confirmation emails

### Running with Docker

1. Build and start all services:
```bash
docker-compose up --build
```

2. Run database migrations:
```bash
docker-compose exec web python manage.py migrate
```

3. Create a superuser:
```bash
docker-compose exec web python manage.py createsuperuser
```

4. Access the application:
- Web: http://localhost:8000
- Python Scraper: http://localhost:8001

### Local Development

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Set up PostgreSQL database and update `DATABASE_URL` in `.env`

3. Run migrations:
```bash
python manage.py migrate
```

4. Create superuser:
```bash
python manage.py createsuperuser
```

5. Start development server:
```bash
python manage.py runserver
```

6. Start Celery worker (in separate terminal):
```bash
celery -A grants_aggregator worker -l info
```

## Project Structure

```
grants_aggregator_V2/
├── grants_aggregator/     # Main Django project
├── users/                 # User authentication app
├── grants/                # Grants and scraping app
├── companies/             # Companies and funding searches app
├── admin_panel/           # Admin panel app
├── python_scraper/        # FastAPI scraper service
├── templates/             # Django templates
└── docker-compose.yml     # Docker Compose configuration
```

## Features

### Public Features
- Browse grants (requires authentication)
- View grant details
- User registration with email confirmation
- Password reset

### Authenticated Features
- Create and manage companies (via Companies House API)
- Create funding searches for companies
- View and edit profile

### Admin Features
- Admin dashboard with statistics
- Trigger scraper workers
- View scrape logs
- Manage users
- Wipe all grants (dangerous operation)

## API Endpoints

### Public API (for scraper service)

- `GET /api/grants?source=<source>` - Get existing grants for a source
- `POST /api/grants/upsert` - Upsert grants (requires API key authentication)

## Scraper Service

The Python scraper service (FastAPI) provides endpoints for scraping grants:

- `POST /run/ukri` - Trigger UKRI scraper
- `POST /run/nihr` - Trigger NIHR scraper
- `POST /run/catapult` - Trigger Catapult scraper
- `GET /health` - Health check

The scraper service should:
1. Fetch existing grants from Django API
2. Scrape grants from the source
3. POST results to Django API for upsert

## Database Models

- **User**: Custom user model with email confirmation and password reset
- **Grant**: Funding opportunities with hash-based change detection
- **Company**: Companies from Companies House
- **FundingSearch**: Funding search criteria for companies
- **ScrapeLog**: Log entries for scraper runs
- **CompanyGrant**: Many-to-many relationship between companies and grants
- **GrantMatchWorkpackage**: Workpackages for matching companies with grants

## Development

### Running Tests

```bash
python manage.py test
```

### Creating Migrations

```bash
python manage.py makemigrations
python manage.py migrate
```

### Accessing Django Admin

1. Create superuser (see setup above)
2. Visit http://localhost:8000/admin

## License

[Your License Here]

