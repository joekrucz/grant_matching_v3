"""
Template filter to convert decimal score (0.0-1.0) to percentage.
"""
from django import template

register = template.Library()


@register.filter
def percentage(value):
    """Convert decimal (0.0-1.0) to percentage (0-100)."""
    try:
        return int(float(value) * 100)
    except (ValueError, TypeError):
        return 0

