"""
URL configuration for grants_aggregator project.
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from .health import health_check

urlpatterns = [
    path('admin/', admin.site.urls),
    path('health/', health_check, name='health_check'),  # Health check for deployment
    path('', include('grants.urls')),
    path('users/', include('users.urls')),
    path('companies/', include('companies.urls')),
    path('funding_searches/', include('companies.urls')),  # Funding searches are part of companies app
    # Custom admin panel lives under /admin-panel to avoid clashing with Django admin
    path('admin-panel/', include('admin_panel.urls')),
    path('api/', include('grants.api_urls')),
]

# SECURITY: Serve media files with authentication in production
if settings.DEBUG:
    # In development, serve media files directly
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
else:
    # In production, serve media files through Django with authentication
    # This ensures only authenticated users can access uploaded files
    from django.contrib.auth.decorators import login_required
    from django.views.static import serve
    
    urlpatterns += [
        path(f'{settings.MEDIA_URL.strip("/")}<path:path>', login_required(serve), {'document_root': settings.MEDIA_ROOT}),
    ]
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

