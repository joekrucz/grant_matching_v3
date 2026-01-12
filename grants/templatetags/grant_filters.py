"""
Template filters for grant formatting.
"""
import re
from django import template
from django.utils.html import escape
from django.utils.safestring import mark_safe

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
    
    Usage: {{ value|replace:"old|new" }}
    Note: Django template filters can only take one argument, so this uses a pipe-separated format.
    Example: {{ section_key|replace:"_| " }} replaces underscores with spaces
    """
    if not value:
        return value
    
    if not arg or '|' not in arg:
        return value
    
    try:
        old, new = arg.split('|', 1)
        return str(value).replace(old, new)
    except ValueError:
        return value


@register.filter
def markdown_headers(value):
    """Convert markdown-style headers to HTML headers with Tailwind styling.
    
    Converts:
    - # Header -> <h1>
    - ## Header -> <h2>
    - ### Header -> <h3>
    - #### Header -> <h4>
    - • List item -> <li>
    
    Preserves other text and line breaks.
    """
    if not value:
        return value
    
    text = str(value)
    
    # Split into lines to process line by line
    lines = text.split('\n')
    output_lines = []
    in_list = False
    
    for line in lines:
        stripped = line.strip()
        
        # Skip empty lines (will be handled by paragraph spacing)
        if not stripped:
            if in_list:
                output_lines.append('</ul>')
                in_list = False
            output_lines.append('')
            continue
        
        # Check for markdown headers (must be at start of line)
        if stripped.startswith('#### '):
            if in_list:
                output_lines.append('</ul>')
                in_list = False
            header_text = escape(stripped[5:].strip())
            output_lines.append(f'<h4 class="text-lg font-semibold mt-4 mb-2 text-primary">{header_text}</h4>')
        elif stripped.startswith('### '):
            if in_list:
                output_lines.append('</ul>')
                in_list = False
            header_text = escape(stripped[4:].strip())
            output_lines.append(f'<h3 class="text-xl font-semibold mt-4 mb-2 text-primary">{header_text}</h3>')
        elif stripped.startswith('## '):
            if in_list:
                output_lines.append('</ul>')
                in_list = False
            header_text = escape(stripped[3:].strip())
            output_lines.append(f'<h2 class="text-2xl font-semibold mt-6 mb-3 text-primary">{header_text}</h2>')
        elif stripped.startswith('# '):
            if in_list:
                output_lines.append('</ul>')
                in_list = False
            header_text = escape(stripped[2:].strip())
            output_lines.append(f'<h1 class="text-3xl font-bold mt-8 mb-4 text-primary">{header_text}</h1>')
        # Check for list items (bullet points)
        elif stripped.startswith('• ') or stripped.startswith('- ') or stripped.startswith('* '):
            if not in_list:
                output_lines.append('<ul class="list-disc list-inside space-y-1 my-3 ml-4">')
                in_list = True
            list_text = escape(stripped[2:].strip())
            output_lines.append(f'<li class="ml-2">{list_text}</li>')
        else:
            # Regular text - close list if open, then add as paragraph
            if in_list:
                output_lines.append('</ul>')
                in_list = False
            # Escape HTML in regular text for security, but preserve line breaks
            escaped = escape(line)
            output_lines.append(f'<p class="mb-3">{escaped}</p>')
    
    # Close any open list
    if in_list:
        output_lines.append('</ul>')
    
    # Join all lines
    html = '\n'.join(output_lines)
    
    # Clean up multiple consecutive empty paragraphs
    html = re.sub(r'(<p class="mb-3"></p>\n?)+', '<p class="mb-3"></p>\n', html)
    
    return mark_safe(html)


@register.simple_tag
def grant_source_logo(source):
    """Return the full static URL to the logo file for a given grant source.
    
    Usage: {% grant_source_logo grant.source %}
    """
    from django.templatetags.static import static
    
    logo_map = {
        'ukri': 'logos/ukri-research-england-standard-logo.png',  # Using Research England as general UKRI
        'bbsrc': 'logos/ukri-bbsrc-standard-logo.png',
        'epsrc': 'logos/ukri-epsrc-standard-logo.png',
        'mrc': 'logos/ukri-mrc-standard-logo.png',
        'stfc': 'logos/ukri-stfc-standard-logo.png',
        'ahrc': 'logos/ukri-ahrc-standard-logo.png',
        'esrc': 'logos/ukri-esrc-standard-logo.png',
        'nerc': 'logos/ukri-nerc-standard-logo.png',
        'innovate_uk': 'logos/ukri-innovate-uk-standard-logo.png',
        'nihr': 'logos/nihr-logo.png',
        'catapult': 'logos/catapult-logo.png',
    }
    logo_path = logo_map.get(source, 'logos/default.svg')
    return static(logo_path)


@register.simple_tag
def grant_source_logo_exists(source):
    """Check if a logo exists for a given grant source (for conditional rendering).
    
    Usage: {% grant_source_logo_exists grant.source as has_logo %}
    """
    valid_sources = ['ukri', 'bbsrc', 'epsrc', 'mrc', 'stfc', 'ahrc', 'esrc', 'nerc', 'nihr', 'catapult', 'innovate_uk']
    return source in valid_sources

