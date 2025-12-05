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

