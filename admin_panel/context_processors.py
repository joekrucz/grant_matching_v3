"""
Context processors for admin_panel app.
"""
from .models import SystemSettings


def system_settings(request):
    """Add system settings to template context."""
    return {
        'system_settings': SystemSettings.get_settings(),
    }
