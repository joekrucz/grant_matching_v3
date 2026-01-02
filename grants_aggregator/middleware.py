"""
Middleware for grants_aggregator project.
"""
from django.shortcuts import redirect


class RailwayHostMiddleware:
    """
    Middleware to dynamically allow Railway domains.
    This allows the app to work on Railway without hardcoding domains.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Railway sets these headers, but we handle ALLOWED_HOSTS in settings
        # This middleware is here for any Railway-specific logic if needed
        return self.get_response(request)


class NonAdminRestrictionMiddleware:
    """
    Middleware that restricts non-admin users to only access the landing page
    and authentication-related pages.
    """
    
    # URLs that non-admins are allowed to access
    ALLOWED_PATHS = [
        '/',  # Landing page
        '/health/',  # Health check
        '/users/sign_in',
        '/users/sign_up',
        '/users/sign_out',
        '/users/confirmation/',  # Email confirmation
        '/users/password/',  # Password reset
        '/static/',  # Static files
        '/media/',  # Media files
    ]
    
    # URL patterns that non-admins are allowed to access (partial matches)
    ALLOWED_PATTERNS = [
        '/users/confirmation/',
        '/users/password/',
    ]
    
    def __init__(self, get_response):
        self.get_response = get_response
    
    def __call__(self, request):
        # Check if user is authenticated and not an admin
        if request.user.is_authenticated and not request.user.admin:
            # Check if the current path is allowed
            path = request.path
            
            # Check exact matches
            if path in self.ALLOWED_PATHS:
                return self.get_response(request)
            
            # Check pattern matches
            allowed = False
            for pattern in self.ALLOWED_PATTERNS:
                if path.startswith(pattern):
                    allowed = True
                    break
            
            # If not allowed, redirect to landing page
            if not allowed:
                # Don't redirect if already on landing page to avoid redirect loops
                if path != '/':
                    return redirect('/')
        
        return self.get_response(request)


