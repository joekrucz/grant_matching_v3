"""
Health check endpoint for deployment monitoring.
"""
from django.http import JsonResponse
from django.db import connection
from django.core.cache import cache


def health_check(request):
    """
    Simple health check endpoint.
    Returns 200 if service is running (even if database/cache are temporarily unavailable).
    This allows Railway to mark the service as healthy during startup.
    """
    database_status = 'unknown'
    cache_status = 'unknown'
    
    # Check database connection - but don't fail health check if it's not ready
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        database_status = 'ok'
    except Exception as e:
        database_status = f'unavailable: {str(e)[:50]}'
    
    # Check cache (Redis) - but don't fail if Redis is unavailable
    try:
        cache.set('health_check', 'ok', 10)
        cache.get('health_check')
        cache_status = 'ok'
    except Exception:
        cache_status = 'unavailable'
    
    # Always return 200 - service is running, even if dependencies aren't ready yet
    # Railway will mark service as healthy, and it can retry database connections
    return JsonResponse({
        'status': 'running',
        'database': database_status,
        'cache': cache_status,
        'message': 'Service is running. Dependencies may still be initializing.'
    })

