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
    from django.conf import settings
    
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
    
    # Construct URL using STATIC_URL setting
    # This is more reliable than using storage backends which may fail if files aren't collected
    static_url = settings.STATIC_URL
    if not static_url.endswith('/'):
        static_url += '/'
    return static_url + logo_path


@register.simple_tag
def grant_source_logo_exists(source):
    """Check if a logo exists for a given grant source (for conditional rendering).
    
    Usage: {% grant_source_logo_exists grant.source as has_logo %}
    """
    valid_sources = ['ukri', 'bbsrc', 'epsrc', 'mrc', 'stfc', 'ahrc', 'esrc', 'nerc', 'nihr', 'catapult', 'innovate_uk']
    return source in valid_sources


@register.filter
def trl_levels_to_range(trl_levels):
    """Convert a list of TRL levels (e.g., ['TRL 1', 'TRL 2', 'TRL 3']) to a range string (e.g., 'TRL 1-3').
    
    Usage: {{ grant.trl_requirements.trl_levels|trl_levels_to_range }}
    """
    if not trl_levels:
        return ''
    
    # Extract numbers from TRL strings (e.g., "TRL 1" -> 1)
    trl_nums = []
    for trl in trl_levels:
        if isinstance(trl, str):
            # Match TRL followed by a number
            match = re.search(r'TRL\s*(\d+)', trl, re.IGNORECASE)
            if match:
                trl_nums.append(int(match.group(1)))
        elif isinstance(trl, int):
            trl_nums.append(trl)
    
    if not trl_nums:
        return ''
    
    trl_nums = sorted(set(trl_nums))  # Remove duplicates and sort
    
    if len(trl_nums) == 1:
        return f'TRL {trl_nums[0]}'
    else:
        return f'TRL {trl_nums[0]}-{trl_nums[-1]}'


@register.simple_tag
def check_project_trl_in_grant_range(project_trl_text, grant_trl_requirements):
    """Check if project TRL is within grant TRL range.
    
    Returns: 'yes', 'no', or 'don\'t know'
    
    Usage: {% check_project_trl_in_grant_range match.match_reasons.project_type_and_trl_focus match.grant.trl_requirements as trl_check_status %}
    """
    if not project_trl_text or not grant_trl_requirements:
        return 'don\'t know'
    
    # Extract project TRL number from text
    project_trl_match = re.search(r'TRL\s*(\d+)', str(project_trl_text), re.IGNORECASE)
    if not project_trl_match:
        return 'don\'t know'
    
    project_trl_num = int(project_trl_match.group(1))
    
    # Get grant TRL levels
    grant_trl_levels = grant_trl_requirements.get('trl_levels', [])
    grant_trl_range = grant_trl_requirements.get('trl_range', '')
    
    # Extract grant TRL numbers
    grant_trl_nums = []
    
    # First try to parse trl_range if it exists (e.g., "1-3" or "TRL 1-3")
    if grant_trl_range:
        range_match = re.search(r'(\d+)\s*-\s*(\d+)', str(grant_trl_range))
        if range_match:
            min_trl = int(range_match.group(1))
            max_trl = int(range_match.group(2))
            grant_trl_nums = list(range(min_trl, max_trl + 1))
            # Check if project TRL is in the contiguous range
            if project_trl_num in grant_trl_nums:
                return 'yes'
            else:
                return 'no'
    
    # If no range, extract from trl_levels and check if project TRL is within min-max range
    if grant_trl_levels:
        for trl in grant_trl_levels:
            if isinstance(trl, str):
                match = re.search(r'TRL\s*(\d+)', trl, re.IGNORECASE)
                if match:
                    grant_trl_nums.append(int(match.group(1)))
            elif isinstance(trl, int):
                grant_trl_nums.append(trl)
        
        # If we have TRL levels, check if project TRL is within the min-max range
        # This handles non-contiguous levels (e.g., ["TRL 1", "TRL 3", "TRL 5"] should accept TRL 2, 3, 4)
        if grant_trl_nums:
            min_grant_trl = min(grant_trl_nums)
            max_grant_trl = max(grant_trl_nums)
            # Check if project TRL is within the range (inclusive)
            if min_grant_trl <= project_trl_num <= max_grant_trl:
                return 'yes'
            else:
                return 'no'
    
    return 'don\'t know'

