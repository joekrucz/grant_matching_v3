"""
WSGI config for grants_aggregator project.
"""
import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'grants_aggregator.settings')

application = get_wsgi_application()

