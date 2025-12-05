"""
Template filter for JSON formatting.
"""
import json
from django import template

register = template.Library()


@register.filter
def json_pretty(value):
    """Format JSON for display."""
    if value is None:
        return ""
    try:
        return json.dumps(value, indent=2, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(value)

