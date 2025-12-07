"""
Django settings for grants_aggregator project.
"""
import os
from pathlib import Path
import environ

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Initialize environment variables
env = environ.Env(
    DEBUG=(bool, False)
)
environ.Env.read_env(os.path.join(BASE_DIR, '.env'))

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = env('SECRET_KEY', default='django-insecure-change-me-in-production')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = env('DEBUG', default=False)

# ALLOWED_HOSTS: Allow Railway domains by default
# Railway provides RAILWAY_PUBLIC_DOMAIN or you can set ALLOWED_HOSTS manually
default_hosts = ['localhost', '127.0.0.1']

# Check for Railway environment variables
if 'RAILWAY_PUBLIC_DOMAIN' in os.environ:
    railway_domain = os.environ['RAILWAY_PUBLIC_DOMAIN']
    default_hosts.append(railway_domain)
    # Also add without port if it has one
    if ':' in railway_domain:
        default_hosts.append(railway_domain.split(':')[0])

# Also check for any custom domain
if 'RAILWAY_CUSTOM_DOMAIN' in os.environ:
    default_hosts.append(os.environ['RAILWAY_CUSTOM_DOMAIN'])

# Use explicit ALLOWED_HOSTS or defaults
# Note: RailwayHostMiddleware will dynamically add hosts when on Railway
ALLOWED_HOSTS = env.list('ALLOWED_HOSTS', default=default_hosts)

# CSRF Configuration for Railway
# Railway is behind a proxy, so we need to trust Railway domains
default_csrf_origins = []
# Add Railway public domain if available
if 'RAILWAY_PUBLIC_DOMAIN' in os.environ:
    railway_domain = os.environ['RAILWAY_PUBLIC_DOMAIN']
    # Add both http and https versions
    default_csrf_origins.append(f'https://{railway_domain.split(":")[0]}')
    default_csrf_origins.append(f'http://{railway_domain.split(":")[0]}')
# Add custom domain if available
if 'RAILWAY_CUSTOM_DOMAIN' in os.environ:
    custom_domain = os.environ['RAILWAY_CUSTOM_DOMAIN']
    default_csrf_origins.append(f'https://{custom_domain}')
    default_csrf_origins.append(f'http://{custom_domain}')

CSRF_TRUSTED_ORIGINS = env.list('CSRF_TRUSTED_ORIGINS', default=default_csrf_origins)

# CSRF Cookie settings for Railway
# Railway uses HTTPS, so we should set secure cookies
CSRF_COOKIE_SECURE = env.bool('CSRF_COOKIE_SECURE', default=not DEBUG)
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = 'Lax'

# Session cookie settings (for consistency)
SESSION_COOKIE_SECURE = env.bool('SESSION_COOKIE_SECURE', default=not DEBUG)
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'

# Proxy settings for Railway
# Railway is behind a proxy, so we need to trust the X-Forwarded-* headers
if os.environ.get('RAILWAY_ENVIRONMENT') or os.environ.get('RAILWAY_PROJECT_ID'):
    # Trust proxy headers from Railway
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    USE_X_FORWARDED_HOST = True
    USE_X_FORWARDED_PORT = True

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'corsheaders',
    'users',
    'grants',
    'companies',
    'admin_panel',
]

MIDDLEWARE = [
    'grants_aggregator.middleware.RailwayHostMiddleware',  # Allow Railway dynamic domains (must be before SecurityMiddleware)
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',  # Serve static files in production
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'grants_aggregator.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'grants_aggregator.wsgi.application'

# Database
# Support both SQLite (for local dev) and PostgreSQL (for production)
database_url = env('DATABASE_URL', default='sqlite:///db.sqlite3')
if database_url.startswith('sqlite'):
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }
else:
    DATABASES = {
        'default': env.db('DATABASE_URL', default='postgresql://postgres:postgres@db:5432/grants_aggregator')
    }

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']

# WhiteNoise configuration for static files
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

# Media files
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Allow larger JSON payloads from scraper upserts
DATA_UPLOAD_MAX_MEMORY_SIZE = 25 * 1024 * 1024  # 25 MB
FILE_UPLOAD_MAX_MEMORY_SIZE = 25 * 1024 * 1024  # 25 MB

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Custom User Model
AUTH_USER_MODEL = 'users.User'

# Email settings
EMAIL_BACKEND = env('EMAIL_BACKEND', default='django.core.mail.backends.console.EmailBackend')
EMAIL_HOST = env('EMAIL_HOST', default='')
EMAIL_PORT = env.int('EMAIL_PORT', default=587)
EMAIL_USE_TLS = env.bool('EMAIL_USE_TLS', default=True)
EMAIL_HOST_USER = env('EMAIL_HOST_USER', default='')
EMAIL_HOST_PASSWORD = env('EMAIL_HOST_PASSWORD', default='')
DEFAULT_FROM_EMAIL = env('DEFAULT_FROM_EMAIL', default='noreply@grantsaggregator.com')

# Celery Configuration
# Railway may provide REDIS_URL or REDISCLOUD_URL
# Ensure database number is included (default to /0 if not present)
raw_redis_url = env('REDIS_URL', default=env('REDISCLOUD_URL', default='redis://redis:6379/0'))
# Add /0 if no database number is specified
if raw_redis_url and not raw_redis_url.endswith('/0') and not raw_redis_url.endswith('/1'):
    if '/' not in raw_redis_url.split('@')[-1]:
        raw_redis_url = f"{raw_redis_url}/0"
REDIS_URL = raw_redis_url

# Log Redis URL for debugging (mask password)
import logging
logger = logging.getLogger(__name__)
if REDIS_URL.startswith('redis://'):
    # Mask password in logs
    masked_url = REDIS_URL
    if '@' in REDIS_URL:
        parts = REDIS_URL.split('@')
        if ':' in parts[0]:
            user_pass = parts[0].split(':', 1)
            if len(user_pass) > 1:
                masked_url = f"redis://{user_pass[0]}:****@{parts[1]}"
    logger.warning(f"Using Redis URL: {masked_url}")

CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE
# Don't connect to broker on startup - wait until first task
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_BROKER_CONNECTION_RETRY = True
CELERY_BROKER_CONNECTION_MAX_RETRIES = 10
# Reduce connection retry spam
CELERY_BROKER_CONNECTION_RETRY_DELAY = 5.0

# Companies House API
COMPANIES_HOUSE_API_KEY = env('COMPANIES_HOUSE_API_KEY', default='')

# OpenAI API (for grant matching)
OPENAI_API_KEY = env('OPENAI_API_KEY', default='')

# Scraper Service
# On Railway, services are accessible via {service-name}.railway.internal
# The port is dynamic, so PYTHON_SCRAPER_URL must be set explicitly in Railway
# Default is for Docker Compose (python-scraper:8000) or local development
if os.environ.get('RAILWAY_ENVIRONMENT') or os.environ.get('RAILWAY_PROJECT_ID'):
    # On Railway, default to scraper.railway.internal with port 8080 (common Railway port)
    # But this should be overridden with the actual port via PYTHON_SCRAPER_URL env var
    default_scraper_url = 'http://scraper.railway.internal:8080'
else:
    # Docker Compose or local development
    default_scraper_url = 'http://python-scraper:8000'

PYTHON_SCRAPER_URL = env('PYTHON_SCRAPER_URL', default=default_scraper_url)
SCRAPER_API_KEY = env('SCRAPER_API_KEY', default='')

# Log scraper URL for debugging (mask any credentials)
if PYTHON_SCRAPER_URL:
    logger.info(f"PYTHON_SCRAPER_URL configured: {PYTHON_SCRAPER_URL}")

# Django API URL (for scraper service)
DJANGO_API_URL = env('DJANGO_API_URL', default='http://web:8000')

# CORS settings (for API access from scraper service)
# SECURITY: Only allow specific origins - never use wildcards in production
CORS_ALLOWED_ORIGINS = env.list('CORS_ALLOWED_ORIGINS', default=[])
# If CORS_ALLOWED_ORIGINS is empty, disable CORS credentials for security
CORS_ALLOW_CREDENTIALS = True if CORS_ALLOWED_ORIGINS else False
# Explicitly deny all origins if not configured
CORS_ALLOW_ALL_ORIGINS = False

# Security Headers (only in production)
if not DEBUG:
    # Force HTTPS redirects
    SECURE_SSL_REDIRECT = True
    
    # HSTS (HTTP Strict Transport Security) - 1 year
    SECURE_HSTS_SECONDS = 31536000  # 1 year
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    
    # Prevent clickjacking
    X_FRAME_OPTIONS = 'DENY'
    
    # XSS Protection
    SECURE_BROWSER_XSS_FILTER = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    
    # Referrer Policy
    SECURE_REFERRER_POLICY = 'strict-origin-when-cross-origin'
else:
    # In development, disable strict security for easier debugging
    SECURE_SSL_REDIRECT = False
    X_FRAME_OPTIONS = 'SAMEORIGIN'

# Login URLs
LOGIN_URL = '/users/sign_in'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/'

# Logging configuration
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {message}',
            'style': '{',
        },
        'simple': {
            'format': '{levelname} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
        'django.db.backends': {
            'handlers': ['console'],
            'level': 'WARNING',  # Set to DEBUG to see SQL queries
            'propagate': False,
        },
        'grants_aggregator': {
            'handlers': ['console'],
            'level': 'INFO' if not DEBUG else 'DEBUG',  # SECURITY: Don't use DEBUG in production
            'propagate': False,
        },
    },
}

