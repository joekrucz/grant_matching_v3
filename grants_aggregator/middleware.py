"""
Custom middleware for Railway deployment.
Allows all hosts when on Railway to handle dynamic domains.
"""
import os
import logging

logger = logging.getLogger(__name__)


class RailwayHostMiddleware:
    """
    Middleware to allow all hosts when running on Railway.
    This is necessary because Railway generates dynamic domains.
    Runs before SecurityMiddleware to modify ALLOWED_HOSTS before validation.
    """
    
    def __init__(self, get_response):
        self.get_response = get_response
        self.on_railway = bool(
            os.environ.get('RAILWAY_ENVIRONMENT') or 
            os.environ.get('RAILWAY_PROJECT_ID') or
            os.environ.get('RAILWAY_PUBLIC_DOMAIN')
        )
        self.explicit_allowed_hosts = bool(os.environ.get('ALLOWED_HOSTS'))
        
        if self.on_railway and not self.explicit_allowed_hosts:
            logger.warning(
                "Running on Railway without explicit ALLOWED_HOSTS. "
                "Allowing all hosts dynamically. For production, set ALLOWED_HOSTS explicitly."
            )
    
    def __call__(self, request):
        # If on Railway and ALLOWED_HOSTS wasn't explicitly set,
        # add the request host to ALLOWED_HOSTS before SecurityMiddleware checks it
        if self.on_railway and not self.explicit_allowed_hosts:
            # Get the host from the request (without port)
            host = request.get_host().split(':')[0]
            # Add it to ALLOWED_HOSTS if not already there
            from django.conf import settings
            if host and host not in settings.ALLOWED_HOSTS:
                settings.ALLOWED_HOSTS.append(host)
                logger.debug(f"Added host '{host}' to ALLOWED_HOSTS for Railway request")
        
        response = self.get_response(request)
        return response
