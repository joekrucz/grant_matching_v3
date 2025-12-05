"""
WSGI config for grants_aggregator project.
"""
import os
import logging

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

