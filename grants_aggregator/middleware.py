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
        # validate and add the request host to ALLOWED_HOSTS before SecurityMiddleware checks it
        if self.on_railway and not self.explicit_allowed_hosts:
            # Get the host from the request (without port)
            host = request.get_host().split(':')[0]
            
            # SECURITY: Validate host against Railway domain patterns to prevent host header injection
            # Railway domains typically match: *.railway.app or *.up.railway.app
            # Also allow custom domains if RAILWAY_CUSTOM_DOMAIN is set
            is_valid_railway_host = False
            
            # Check if it's a Railway domain
            if host.endswith('.railway.app') or host.endswith('.up.railway.app'):
                is_valid_railway_host = True
            
            # Check if it matches custom domain
            custom_domain = os.environ.get('RAILWAY_CUSTOM_DOMAIN')
            if custom_domain and host == custom_domain.split(':')[0]:
                is_valid_railway_host = True
            
            # Check if it matches public domain
            public_domain = os.environ.get('RAILWAY_PUBLIC_DOMAIN')
            if public_domain and host == public_domain.split(':')[0]:
                is_valid_railway_host = True
            
            # Only add to ALLOWED_HOSTS if it's a valid Railway domain
            if is_valid_railway_host:
                from django.conf import settings
                if host and host not in settings.ALLOWED_HOSTS:
                    settings.ALLOWED_HOSTS.append(host)
                    logger.debug(f"Added valid Railway host '{host}' to ALLOWED_HOSTS")
                
                # Also add to CSRF_TRUSTED_ORIGINS if not explicitly set
                if not os.environ.get('CSRF_TRUSTED_ORIGINS'):
                    # Get the scheme (http or https) from the request
                    scheme = 'https' if request.is_secure() else 'http'
                    origin = f'{scheme}://{host}'
                    if origin not in settings.CSRF_TRUSTED_ORIGINS:
                        settings.CSRF_TRUSTED_ORIGINS.append(origin)
                        logger.debug(f"Added origin '{origin}' to CSRF_TRUSTED_ORIGINS")
            else:
                # Log suspicious host attempts
                logger.warning(
                    f"Rejected suspicious host header '{host}' on Railway. "
                    f"Set ALLOWED_HOSTS explicitly in production."
                )
        
        response = self.get_response(request)
        return response
