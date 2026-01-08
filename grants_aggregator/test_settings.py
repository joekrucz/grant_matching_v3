"""
Test settings for pytest-django.
Uses in-memory SQLite for fast test execution.
"""
from .settings import *
import tempfile
import os

# Use in-memory SQLite for speed
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    }
}

# Disable migrations in tests (use schema from models directly)
class DisableMigrations:
    def __contains__(self, item):
        return True
    def __getitem__(self, item):
        return None

MIGRATION_MODULES = DisableMigrations()

# Fast password hashing for tests
PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']

# Media files in temp directory
MEDIA_ROOT = tempfile.mkdtemp()

# Disable external services
CELERY_TASK_ALWAYS_EAGER = True  # Execute tasks synchronously
CELERY_TASK_EAGER_PROPAGATES = True

# Mock external API keys
COMPANIES_HOUSE_API_KEY = 'test-key'
OPENAI_API_KEY = 'test-key'
SCRAPER_API_KEY = 'test-key'

# Disable Sentry in tests
SENTRY_DSN = None

# Disable security features that interfere with testing
SECURE_SSL_REDIRECT = False
CSRF_COOKIE_SECURE = False
SESSION_COOKIE_SECURE = False

# Allow all hosts in tests
ALLOWED_HOSTS = ['*']

# Simplified CORS for tests
CORS_ALLOW_ALL_ORIGINS = True

# Disable rate limiting in tests
RATELIMIT_ENABLE = False

# Email backend for tests
EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'

# Logging for tests
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'WARNING',
    },
}




