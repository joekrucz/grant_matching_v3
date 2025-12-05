"""
Template filter for JSON formatting.
"""
import json
from django import template
from django.utils.safestring import mark_safe

register = template.Library()


@register.filter
def json_pretty(value):
    """Format JSON for display."""
    if value is None:
        return ""
    try:
        if isinstance(value, str):
            # Try to parse if it's a JSON string
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                return value
        return mark_safe(json.dumps(value, indent=2, ensure_ascii=False))
    except (TypeError, ValueError):
        return str(value)

