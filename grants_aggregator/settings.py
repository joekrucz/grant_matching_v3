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
PYTHON_SCRAPER_URL = env('PYTHON_SCRAPER_URL', default='http://python-scraper:8000')
SCRAPER_API_KEY = env('SCRAPER_API_KEY', default='')

# Django API URL (for scraper service)
DJANGO_API_URL = env('DJANGO_API_URL', default='http://web:8000')

# CORS settings (for API access from scraper service)
CORS_ALLOWED_ORIGINS = env.list('CORS_ALLOWED_ORIGINS', default=[])
CORS_ALLOW_CREDENTIALS = True

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
            'level': 'DEBUG',
            'propagate': False,
        },
    },
}

