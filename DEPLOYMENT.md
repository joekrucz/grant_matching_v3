# Deployment Guide

## Recommended: Railway Deployment

### Why Railway?
- ✅ Docker Compose support
- ✅ Managed PostgreSQL & Redis
- ✅ Automatic SSL certificates
- ✅ Simple environment variable management
- ✅ Free tier available
- ✅ Easy scaling

### Step-by-Step Deployment

#### 1. Prepare Your Repository
- Ensure all code is pushed to GitHub
- Verify `.env` is in `.gitignore` (never commit secrets!)
- Ensure `railway.json` and/or `Procfile` are present (prevents Rails auto-detection)
- Verify `Dockerfile` uses Gunicorn for production

#### 2. Sign Up & Connect
1. Go to [railway.app](https://railway.app)
2. Sign up with GitHub
3. Click "New Project" → "Deploy from GitHub repo"
4. Select your repository
5. **IMPORTANT:** If your Django project is in a subdirectory (e.g., `grants_aggregator_V2/`):
   - In Railway dashboard → Service Settings → Deploy
   - Set **Root Directory** to: `grants_aggregator_V2`
   - This prevents Railway from detecting Rails in the parent directory

#### 3. Configure Services

**Option A: Using Docker Compose (Recommended)**
Railway will detect your `docker-compose.yml`. You'll need to configure:

**Web Service:**
- Port: 8000
- Health check: `/health/` (health check endpoint)

**Celery Worker:**
- Command: `celery -A grants_aggregator worker -l info`
- No port needed (background service)

**Python Scraper:**
- Port: 8001 (internal only, or expose if needed)

**Option B: Individual Services (Alternative)**
If Docker Compose doesn't work, deploy as separate services:
1. **Web Service**: Uses `railway.json` or `Procfile` for configuration
2. **Celery Worker**: Background worker with command `celery -A grants_aggregator worker -l info`
3. **Scraper Service**: Separate service for the Python scraper

**Important:** Railway may auto-detect Rails. If you see Rails errors, ensure:
- `railway.json` is present (tells Railway it's Django)
- `Procfile` is present (alternative configuration)
- Dockerfile uses Gunicorn, not Rails

#### 4. Add Managed Services

In Railway dashboard:
1. Click "+ New" → "Database" → "PostgreSQL"
2. Click "+ New" → "Database" → "Redis"

#### 5. Set Environment Variables

In Railway, go to each service → Variables tab:

**Required Variables:**
```
SECRET_KEY=<generate-a-strong-secret-key>
DEBUG=False
ALLOWED_HOSTS=your-domain.railway.app,*.railway.app
DATABASE_URL=<from-postgres-service>
REDIS_URL=<from-redis-service>
COMPANIES_HOUSE_API_KEY=<your-key>
OPENAI_API_KEY=<your-key>
SCRAPER_API_KEY=<generate-random-string>
PYTHON_SCRAPER_URL=http://python-scraper:8000
DJANGO_API_URL=https://your-domain.railway.app
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=<your-email>
EMAIL_HOST_PASSWORD=<your-app-password>
DEFAULT_FROM_EMAIL=noreply@yourdomain.com
```

#### 6. Update docker-compose.yml for Production

Create `docker-compose.prod.yml`:
```yaml
version: '3.8'

services:
  web:
    build: .
    command: gunicorn --bind 0.0.0.0:8000 --workers 3 --timeout 120 grants_aggregator.wsgi:application
    environment:
      - DATABASE_URL=${DATABASE_URL}
      - REDIS_URL=${REDIS_URL}
    # Remove volumes in production (code is in image)
    
  celery:
    build: .
    command: celery -A grants_aggregator worker -l info
    environment:
      - DATABASE_URL=${DATABASE_URL}
      - REDIS_URL=${REDIS_URL}
    
  python-scraper:
    build:
      context: ./python_scraper
      dockerfile: Dockerfile
    environment:
      - DJANGO_API_URL=${DJANGO_API_URL}
```

#### 7. Run Migrations & Create Admin User

After first deployment, run:
```bash
# Run migrations
railway run python manage.py migrate

# Collect static files
railway run python manage.py collectstatic

# Create admin user (recommended - non-interactive)
railway run python manage.py create_admin --email admin@yourdomain.com --password YourSecurePassword --name "Admin User"

# OR use Django's createsuperuser (interactive)
railway run python manage.py createsuperuser
```

**Important:** You **must** create an admin user after deployment, as there's no frontend signup for admin users. The `create_admin` command is recommended as it's non-interactive and works well in CI/CD pipelines.

**To create additional admin users later:**
```bash
railway run python manage.py create_admin --email another@yourdomain.com --password SecurePassword
```

#### 8. Custom Domain (Optional)

1. In Railway dashboard → Settings → Domains
2. Add your custom domain
3. Railway provides SSL automatically

---

## Alternative: Render Deployment

### Steps

1. **Create Account**: [render.com](https://render.com)

2. **Create PostgreSQL Database**:
   - New → PostgreSQL
   - Note the connection string

3. **Create Redis Instance**:
   - New → Redis
   - Note the connection string

4. **Create Web Service**:
   - New → Web Service
   - Connect GitHub repo
   - Build Command: `pip install -r requirements.txt && python manage.py collectstatic --noinput`
   - Start Command: `gunicorn grants_aggregator.wsgi:application`
   - Environment: Add all variables

5. **Create Background Worker** (Celery):
   - New → Background Worker
   - Same repo
   - Start Command: `celery -A grants_aggregator worker -l info`

6. **Create Web Service** (Scraper):
   - New → Web Service
   - Build Command: `cd python_scraper && pip install -r requirements.txt`
   - Start Command: `cd python_scraper && uvicorn app.main:app --host 0.0.0.0 --port 8000`

7. **Create Admin User**:
   ```bash
   # Via Render Shell or SSH
   python manage.py create_admin --email admin@yourdomain.com --password YourSecurePassword
   ```

---

## Production Settings Checklist

### Initial Setup
- [ ] Run database migrations
- [ ] Collect static files
- [ ] **Create admin user** (required - no frontend signup for admins)
- [ ] Test admin login

### Security
- [ ] Set `DEBUG=False`
- [ ] Set strong `SECRET_KEY`
- [ ] Configure `ALLOWED_HOSTS`
- [ ] Use HTTPS only
- [ ] Set secure cookies
- [ ] Configure CORS properly

### Static & Media Files
- [ ] Use WhiteNoise for static files (already in requirements)
- [ ] Configure media file storage (S3, Cloudinary, etc.)
- [ ] Run `collectstatic` on deploy

### Database
- [ ] Use managed PostgreSQL
- [ ] Set up database backups
- [ ] Run migrations on deploy

### Monitoring
- [ ] Set up error tracking (Sentry)
- [ ] Configure logging
- [ ] Set up uptime monitoring

### Performance
- [ ] Use Gunicorn (not runserver)
- [ ] Configure worker processes
- [ ] Set up CDN for static files
- [ ] Enable caching

---

## Environment Variables Reference

```bash
# Django
SECRET_KEY=<generate-strong-key>
DEBUG=False
ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com

# Database
DATABASE_URL=postgresql://user:pass@host:5432/dbname

# Redis
REDIS_URL=redis://host:6379/0

# APIs
COMPANIES_HOUSE_API_KEY=<your-key>
OPENAI_API_KEY=<your-key>
SCRAPER_API_KEY=<random-string>

# URLs
DJANGO_API_URL=https://yourdomain.com
PYTHON_SCRAPER_URL=http://python-scraper:8000

# Email
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=<your-email>
EMAIL_HOST_PASSWORD=<app-password>
DEFAULT_FROM_EMAIL=noreply@yourdomain.com
```

---

## Quick Start: Railway (5 minutes)

1. Push code to GitHub
2. Go to railway.app → New Project → GitHub
3. Add PostgreSQL service
4. Add Redis service
5. Set environment variables
6. Deploy!
7. **Create admin user (REQUIRED):**
   ```bash
   railway run python manage.py create_admin --email admin@yourdomain.com --password YourSecurePassword
   ```

Railway will automatically:
- Build your Docker images
- Run migrations
- Deploy all services
- Provide HTTPS

**⚠️ Important:** You must create an admin user after deployment. There's no frontend interface to create admin users - use the `create_admin` management command.

---

## Cost Estimates

### Railway
- Starter: $5/month (512MB RAM)
- Developer: $20/month (2GB RAM)
- Pro: $100/month (8GB RAM)

### Render
- Free tier: Limited hours
- Starter: $7/month per service
- Standard: $25/month per service

### DigitalOcean
- Basic: $12/month
- Professional: $24/month

---

## Troubleshooting

### Error: "Missing secret_key_base" or Rails commands running

**Problem:** Deployment platform is detecting Rails instead of Django. This often happens when:
- Your Django project is in a subdirectory (e.g., `grants_aggregator_V2/`) and there's a Rails app in the parent directory
- Railway auto-detects the Rails app in the parent directory

**Solution:**
1. **Set Root Directory in Railway:**
   - Go to Railway dashboard → Your Service → Settings → Deploy
   - Set **Root Directory** to: `grants_aggregator_V2` (or your Django project subdirectory)
   - This tells Railway to ignore the parent directory and use your Django project

2. **Verify Configuration Files:**
   - Ensure `railway.json` is in your Django project root (not parent directory)
   - Ensure `Procfile` is in your Django project root
   - Verify `Dockerfile` uses Gunicorn (not Rails)

3. **Manual Override:**
   - In Railway dashboard → Service Settings → Deploy:
     - Set **Build Command**: `pip install -r requirements.txt && python manage.py collectstatic --noinput`
     - Set **Start Command**: `gunicorn --bind 0.0.0.0:$PORT --workers 3 grants_aggregator.wsgi:application`
     - Set **Root Directory**: `grants_aggregator_V2` (your Django project folder)

4. **Alternative: Use Docker:**
   - Set builder to "Dockerfile"
   - Ensure Dockerfile is in the Django project directory
   - Railway will use Docker instead of auto-detecting frameworks

### Error: "ModuleNotFoundError" or missing dependencies

**Solution:**
- Ensure `requirements.txt` includes all dependencies
- Check that Gunicorn is in requirements.txt
- Verify the build process installs requirements

### Error: Database connection issues

**Solution:**
- Verify `DATABASE_URL` environment variable is set correctly
- Check that PostgreSQL service is running
- Ensure database migrations have run: `python manage.py migrate`

### Error: Static files not loading

**Solution:**
- Run `python manage.py collectstatic` after deployment
- Verify WhiteNoise is in `requirements.txt` and `MIDDLEWARE`
- Check `STATIC_ROOT` and `STATIC_URL` settings

---

## Need Help?

- Railway Docs: https://docs.railway.app
- Render Docs: https://render.com/docs
- Django Deployment: https://docs.djangoproject.com/en/5.0/howto/deployment/

