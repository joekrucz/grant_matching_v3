"""
Health check endpoint for deployment monitoring.
"""
from django.http import JsonResponse
from django.db import connection
from django.core.cache import cache


def health_check(request):
    """Simple health check endpoint."""
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
        return JsonResponse({
            'status': 'unhealthy',
            'error': str(e)
        }, status=503)

