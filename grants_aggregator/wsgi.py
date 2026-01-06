"""
WSGI config for grants_aggregator project.
"""
import os
import logging

# Initialize Sentry error tracking if DSN is configured
sentry_dsn = os.environ.get('SENTRY_DSN')
if sentry_dsn:
    try:
        import sentry_sdk
        from sentry_sdk.integrations.django import DjangoIntegration
        from sentry_sdk.integrations.celery import CeleryIntegration
        from sentry_sdk.integrations.logging import LoggingIntegration
        
        sentry_sdk.init(
            dsn=sentry_dsn,
            integrations=[
                DjangoIntegration(
                    transaction_style='url',
                    middleware_spans=True,
                    signals_spans=True,
                ),
                CeleryIntegration(),
                LoggingIntegration(
                    level=logging.INFO,  # Capture info and above as breadcrumbs
                    event_level=logging.ERROR  # Send errors as events
                ),
            ],
            # Set traces_sample_rate to 1.0 to capture 100%
            # of transactions for performance monitoring.
            # We recommend adjusting this value in production.
            traces_sample_rate=0.1 if os.environ.get('DEBUG', 'False').lower() == 'false' else 1.0,
            # If you wish to associate users to errors (assuming you are using
            # django.contrib.auth) you may enable sending PII data.
            send_default_pii=False,  # Don't send user data by default for privacy
            # Set profiles_sample_rate to profile performance
            profiles_sample_rate=0.1 if os.environ.get('DEBUG', 'False').lower() == 'false' else 1.0,
            environment=os.environ.get('ENVIRONMENT', 'production'),
            release=os.environ.get('RELEASE_VERSION', None),
        )
        logging.info("Sentry error tracking initialized")
    except ImportError:
        logging.warning("Sentry SDK not installed, error tracking disabled")
    except Exception as e:
        logging.warning(f"Failed to initialize Sentry: {e}")

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'grants_aggregator.settings')

logger = logging.getLogger(__name__)

# Log startup information
logger.info("Starting Django application...")
logger.info(f"DEBUG={os.environ.get('DEBUG', 'Not set')}")
logger.info(f"DATABASE_URL={'Set' if os.environ.get('DATABASE_URL') else 'Not set'}")

application = get_wsgi_application()

# Try to verify database connection on startup
try:
    from django.db import connection
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
    logger.info("Database connection successful")
except Exception as e:
    logger.error(f"Database connection failed: {e}")
    logger.warning("Application will start but database operations may fail. Run migrations: python manage.py migrate")

