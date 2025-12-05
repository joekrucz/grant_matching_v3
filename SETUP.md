# Setup Instructions

## Initial Setup

1. **Copy environment file:**
   ```bash
   cp .env.example .env
   ```

2. **Edit `.env` and set required values:**
   - `SECRET_KEY` - Generate a Django secret key
   - `COMPANIES_HOUSE_API_KEY` - Get from https://developer.company-information.service.gov.uk/
   - `SCRAPER_API_KEY` - Generate a secure random string for API authentication
   - Email settings if you want email confirmation to work

3. **Start services with Docker:**
   ```bash
   docker-compose up --build
   ```

4. **Run migrations:**
   ```bash
   docker-compose exec web python manage.py migrate
   ```

5. **Create superuser:**
   ```bash
   docker-compose exec web python manage.py createsuperuser
   ```

6. **Access the application:**
   - Web: http://localhost:8000
   - Admin: http://localhost:8000/admin
   - Scraper API: http://localhost:8001

## Generating Django Secret Key

```python
from django.core.management.utils import get_random_secret_key
print(get_random_secret_key())
```

## Companies House API Key

1. Register at https://developer.company-information.service.gov.uk/
2. Create an application
3. Copy the API key to `.env` as `COMPANIES_HOUSE_API_KEY`

## Testing the Application

1. **Create a user account:**
   - Visit http://localhost:8000/users/sign_up
   - Register with your email
   - Check console output for confirmation email (if using console backend)
   - Confirm email and sign in

2. **Add a company:**
   - Sign in and go to Companies
   - Click "Add Company"
   - Enter a Companies House number (e.g., "12345678")
   - Company details will be fetched automatically

3. **Browse grants:**
   - Go to Grants (requires authentication)
   - Use search and filters to find grants

4. **Admin functions:**
   - Sign in as admin user
   - Go to Admin Dashboard
   - Trigger scrapers (will run sequentially: UKRI → NIHR → Catapult)
   - View scrape logs

## Development Notes

- The Python scraper service endpoints are placeholders - implement actual scraping logic in `python_scraper/main.py`
- Email confirmation uses console backend by default - check terminal output for confirmation links
- For production, configure proper email backend (SMTP, SendGrid, etc.)
- Celery tasks run in background - check logs with `docker-compose logs celery`

## Troubleshooting

### Database connection errors
- Ensure PostgreSQL container is running: `docker-compose ps`
- Check database credentials in `.env`

### Celery not processing tasks
- Check Redis is running: `docker-compose ps redis`
- Check Celery logs: `docker-compose logs celery`

### Companies House API errors
- Verify API key is correct in `.env`
- Check API key has proper permissions
- Verify company number format (8 digits)

### Scraper service not connecting
- Check `DJANGO_API_URL` in `.env` matches Django service URL
- Verify `SCRAPER_API_KEY` matches in both services
- Check network connectivity between containers

