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

