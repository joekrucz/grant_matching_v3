# Initialize Sentry error tracking if DSN is configured (for Celery workers)
import os
sentry_dsn = os.environ.get('SENTRY_DSN')
if sentry_dsn:
    try:
        import sentry_sdk
        from sentry_sdk.integrations.django import DjangoIntegration
        from sentry_sdk.integrations.celery import CeleryIntegration
        from sentry_sdk.integrations.logging import LoggingIntegration
        import logging
        
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
            traces_sample_rate=0.1 if os.environ.get('DEBUG', 'False').lower() == 'false' else 1.0,
            send_default_pii=False,  # Don't send user data by default for privacy
            profiles_sample_rate=0.1 if os.environ.get('DEBUG', 'False').lower() == 'false' else 1.0,
            environment=os.environ.get('ENVIRONMENT', 'production'),
            release=os.environ.get('RELEASE_VERSION', None),
        )
        logger = logging.getLogger(__name__)
        logger.info("Sentry error tracking initialized for Celery worker")
    except ImportError:
        import logging
        logger = logging.getLogger(__name__)
        logger.warning("Sentry SDK not installed, error tracking disabled")
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"Failed to initialize Sentry: {e}")

# This will make sure the app is always imported when
# Django starts so that shared_task will use this app.
# Make Celery optional - don't crash Django if Redis/Celery is unavailable
try:
    from .celery import app as celery_app
    CELERY_AVAILABLE = True
except Exception as e:
    import logging
    logger = logging.getLogger(__name__)
    logger.warning(f"Celery not available: {e}. Background tasks will be disabled.")
    celery_app = None
    CELERY_AVAILABLE = False

__all__ = ('celery_app', 'CELERY_AVAILABLE')

