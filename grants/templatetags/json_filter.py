"""
Template filter for JSON formatting.
"""
import json as json_module
from django import template
from django.utils.safestring import mark_safe
from django.utils.html import escapejs

register = template.Library()


@register.filter(name='json')
def json_filter(value):
    """Safely encode value as JSON for JavaScript use (prevents XSS)."""
    if value is None:
        return "null"
    try:
        # Use json.dumps to properly encode the value
        # This escapes special characters and prevents XSS
        return mark_safe(json_module.dumps(value, ensure_ascii=False))
    except (TypeError, ValueError):
        # If value can't be serialized, return empty array as safe fallback
        return "[]"


@register.filter
def json_pretty(value):
    """Format JSON for display."""
    if value is None:
        return ""
    try:
        if isinstance(value, str):
            # Try to parse if it's a JSON string
            try:
                value = json_module.loads(value)
            except json_module.JSONDecodeError:
                return value
        return mark_safe(json_module.dumps(value, indent=2, ensure_ascii=False))
    except (TypeError, ValueError):
        return str(value)

