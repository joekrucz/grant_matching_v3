"""
API views for scraper service.
"""
import secrets
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.conf import settings
from django.utils import timezone
from .models import Grant, ScrapeLog
import json


def verify_api_key(request):
    """Verify API key from Authorization header."""
    auth_header = request.META.get('HTTP_AUTHORIZATION', '')
    if not auth_header.startswith('Bearer '):
        return False
    
    token = auth_header[7:]  # Remove 'Bearer ' prefix
    expected_token = settings.SCRAPER_API_KEY
    
    # Use constant-time comparison to prevent timing attacks
    return secrets.compare_digest(token, expected_token)


@require_http_methods(["GET"])
def get_grants(request):
    """Get existing grants for a source (for scraper service)."""
    if not verify_api_key(request):
        return JsonResponse({'error': 'Unauthorized'}, status=401)
    
    source = request.GET.get('source')
    if not source:
        return JsonResponse({'error': 'source parameter required'}, status=400)
    
    grants = Grant.objects.filter(source=source).values('url', 'hash_checksum', 'slug', 'title')
    return JsonResponse({'grants': list(grants)})


@csrf_exempt
@require_http_methods(["POST"])
def upsert_grants(request):
    """Upsert grants from scraper service."""
    if not verify_api_key(request):
        return JsonResponse({'error': 'Unauthorized'}, status=401)
    
    # SECURITY: Parse JSON with size limits
    from grants_aggregator.security_utils import safe_json_loads
    data, error_response = safe_json_loads(request, max_size=25 * 1024 * 1024)  # 25MB for scraper upserts
    if error_response:
        return error_response
    try:
        grants_data = data.get('grants', [])
        log_id = data.get('log_id')
        grants_found = data.get('grants_found')  # Get grants_found from payload
        
        # Debug logging
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"upsert_grants: log_id={log_id}, grants_found={grants_found}, grants_data_length={len(grants_data)}")
        
        if not grants_data:
            return JsonResponse({'error': 'grants array required'}, status=400)
        
        result = Grant.upsert_from_payload(grants_data, log_id=log_id, grants_found=grants_found)
        
        return JsonResponse({
            'success': True,
            'created': result['created'],
            'updated': result['updated'],
            'skipped': result['skipped'],
        })
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        # SECURITY: Don't expose internal error details to API clients
        # Log the full error server-side for debugging
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error in upsert_grants: {e}", exc_info=True)
        # Return generic error message
        return JsonResponse({'error': 'An error occurred processing the request'}, status=500)

