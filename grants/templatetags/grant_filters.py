"""
Template filters for grant formatting.
"""
from django import template

register = template.Library()


@register.filter
def split_sections(value, delimiter="##"):
    """Split text by delimiter and return list of sections."""
    if not value:
        return []
    return [section.strip() for section in str(value).split(delimiter) if section.strip()]


@register.filter
def split_lines(value, delimiter="\n\n"):
    """Split text by delimiter."""
    if not value:
        return []
    return [line.strip() for line in str(value).split(delimiter) if line.strip()]


@register.filter
def replace(value, arg):
    """Replace occurrences of a substring in a string.
    
    Usage: {{ value|replace:"old":"new" }}
    Note: Django template filters can only take one argument, so this uses a colon-separated format.
    """
    if not value:
        return value
    
    if not arg or ':' not in arg:
        return value
    
    try:
        old, new = arg.split(':', 1)
        return str(value).replace(old, new)
    except ValueError:
        return value

