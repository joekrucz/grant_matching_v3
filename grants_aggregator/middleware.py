"""
Custom middleware for Railway deployment.
Allows all hosts when on Railway to handle dynamic domains.
"""
import os


class RailwayHostMiddleware:
    """
    Middleware to allow all hosts when running on Railway.
    This is necessary because Railway generates dynamic domains.
    """
    
    def __init__(self, get_response):
        self.get_response = get_response
        self.on_railway = bool(
            os.environ.get('RAILWAY_ENVIRONMENT') or 
            os.environ.get('RAILWAY_PROJECT_ID')
        )
    
    def __call__(self, request):
        # If on Railway and ALLOWED_HOSTS wasn't explicitly set,
        # bypass the host validation by setting a valid host
        if self.on_railway and not os.environ.get('ALLOWED_HOSTS'):
            # Get the host from the request
            host = request.get_host().split(':')[0]
            # Temporarily add it to ALLOWED_HOSTS for this request
            from django.conf import settings
            if host not in settings.ALLOWED_HOSTS:
                settings.ALLOWED_HOSTS.append(host)
        
        response = self.get_response(request)
        return response

