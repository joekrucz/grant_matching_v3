"""
Health check endpoint for deployment monitoring.
"""
from django.http import JsonResponse
from django.db import connection
from django.core.cache import cache


def health_check(request):
    """
    Simple health check endpoint.
    Returns 200 if service is ready, 503 if not ready.
    """
    try:
        # Check database connection
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        
        # Check cache (Redis) - but don't fail if Redis is unavailable
        # This allows the service to start even if Redis is temporarily down
        try:
            cache.set('health_check', 'ok', 10)
            cache.get('health_check')
            cache_status = 'ok'
        except Exception:
            cache_status = 'unavailable'
        
        return JsonResponse({
            'status': 'healthy',
            'database': 'ok',
            'cache': cache_status
        })
    except Exception as e:
        # Return 503 to indicate service is not ready
        return JsonResponse({
            'status': 'unhealthy',
            'error': str(e)
        }, status=503)

