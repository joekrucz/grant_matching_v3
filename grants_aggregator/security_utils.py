"""
Security utilities for the grants_aggregator project.
"""
import json
import logging
from django.conf import settings
from django.http import JsonResponse

logger = logging.getLogger(__name__)

# Maximum JSON payload size (10MB)
MAX_JSON_PAYLOAD_SIZE = 10 * 1024 * 1024


def safe_json_loads(request, max_size=None):
    """
    Safely parse JSON from request body with size limits.
    
    Args:
        request: Django request object
        max_size: Maximum size in bytes (defaults to MAX_JSON_PAYLOAD_SIZE)
        
    Returns:
        tuple: (data: dict or None, error_response: JsonResponse or None)
    """
    if max_size is None:
        max_size = MAX_JSON_PAYLOAD_SIZE
    
    # Check request body size
    if hasattr(request, 'body') and len(request.body) > max_size:
        logger.warning(f"JSON payload too large: {len(request.body)} bytes (max: {max_size})")
        return None, JsonResponse({
            "error": f"Payload too large. Maximum size is {max_size // 1024 // 1024}MB"
        }, status=413)
    
    # Parse JSON
    try:
        body_str = request.body.decode('utf-8') if request.body else "{}"
        data = json.loads(body_str)
        return data, None
    except json.JSONDecodeError as e:
        logger.warning(f"Invalid JSON payload: {str(e)}")
        return None, JsonResponse({"error": "Invalid JSON payload"}, status=400)
    except UnicodeDecodeError as e:
        logger.warning(f"Invalid encoding in request body: {str(e)}")
        return None, JsonResponse({"error": "Invalid request encoding"}, status=400)
    except Exception as e:
        logger.error(f"Unexpected error parsing JSON: {str(e)}", exc_info=True)
        # SECURITY: Don't expose internal error details in production
        if settings.DEBUG:
            error_msg = f"Error parsing request: {str(e)}"
        else:
            error_msg = "An error occurred processing your request"
        return None, JsonResponse({"error": error_msg}, status=500)

