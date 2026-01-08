"""
Template filters for string manipulation.
"""
from django import template

register = template.Library()


@register.filter
def replace(value, arg):
    """
    Replace occurrences of a substring in a string.
    Usage: {{ value|replace:"old:new" }}
    """
    if not value or not arg:
        return value
    
    try:
        old, new = arg.split(':', 1)
        return value.replace(old, new)
    except (ValueError, AttributeError):
        return value

