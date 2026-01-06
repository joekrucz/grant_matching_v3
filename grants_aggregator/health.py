"""
Health check endpoint for deployment monitoring.
"""
from django.http import JsonResponse
from django.db import connection
from django.core.cache import cache


def health_check(request):
    """Simple health check endpoint."""
    from django.conf import settings
    try:
        # Check database
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        
        # Check cache (Redis)
        cache.set('health_check', 'ok', 10)
        cache.get('health_check')
        
        return JsonResponse({
            'status': 'healthy',
            'database': 'ok',
            'cache': 'ok'
        })
    except Exception as e:
        # SECURITY: Don't expose internal error details in production
        if settings.DEBUG:
            error_message = str(e)
        else:
            error_message = 'Service unavailable'
        return JsonResponse({
            'status': 'unhealthy',
            'error': error_message
        }, status=503)

