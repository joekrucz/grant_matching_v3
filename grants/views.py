"""
Grant views.
"""
from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from .models import Grant


def index(request):
    """Dashboard/landing page."""
    return render(request, 'grants/index.html')


@login_required
def grants_list(request):
    """List all grants with search and filters."""
    grants = Grant.objects.all()
    
    # Search
    query = request.GET.get('q', '')
    if query:
        grants = grants.filter(
            Q(title__icontains=query) |
            Q(summary__icontains=query) |
            Q(description__icontains=query)
        )
    
    # Filters
    source = request.GET.get('source', '')
    if source:
        grants = grants.filter(source=source)
    
    status = request.GET.get('status', '')
    if status:
        grants = grants.filter(status=status)
    
    # Ordering
    grants = grants.order_by('-deadline', '-created_at')
    
    # Pagination
    paginator = Paginator(grants, 20)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    
    context = {
        'page_obj': page_obj,
        'query': query,
        'source_filter': source,
        'status_filter': status,
    }
    return render(request, 'grants/list.html', context)


def grant_detail(request, slug):
    """Grant detail page (public)."""
    grant = get_object_or_404(Grant, slug=slug)
    
    # Prepare sections for Catapult and NIHR grants if available
    sections_list = []
    if grant.raw_data and grant.raw_data.get('sections'):
        sections_dict = grant.raw_data.get('sections', {})
        # Convert dict to list of dicts for template iteration
        # Handle nested structure (tabs with sections) and flat structure
        for key, value in sections_dict.items():
            if isinstance(value, dict):
                # Check if this is a tab with nested sections (Catapult)
                if value.get('is_tab') and 'sections' in value:
                    # This is a tab containing multiple sections
                    tab_title = value.get('title', key.replace('_', ' ').title())
                    nested_sections = value.get('sections', [])
                    sections_list.append({
                        'key': key,
                        'content': '',  # Tab itself has no content
                        'title': tab_title,
                        'is_tab': True,
                        'sections': nested_sections  # Nested sections within this tab
                    })
                else:
                    # Regular section with title and content
                    section_title = value.get('title', key.replace('_', ' ').title())
                    section_content = value.get('content', '')
                    sections_list.append({
                        'key': key,
                        'content': section_content,
                        'title': section_title,
                        'is_tab': False
                    })
            else:
                # Old format: just a string
                sections_list.append({
                    'key': key,
                    'content': value or "",
                    'title': None,
                    'is_tab': False
                })
        
        # Sort sections by preferred order (different for each source)
        if grant.source == 'catapult':
            # For Catapult, prioritize tabs in order, then general sections
            section_order = ["summary", "overview", "eligibility", "how_to_apply", "supporting_information", "general"]
        elif grant.source == 'nihr':
            # Matches NIHR site tab order
            section_order = ["overview", "research_specification", "application_guidance", "application_process", "contact"]
        elif grant.source == 'ukri':
            section_order = ["overview", "scope", "eligibility", "funding", "how_to_apply", "dates", "assessment", "contact", "terms"]
        elif grant.source == 'innovate_uk':
            # Matches Innovate UK site tab order
            section_order = ["summary", "eligibility", "scope", "dates", "how_to_apply", "supporting_information", "funding", "assessment", "contact", "terms"]
        else:
            section_order = ["overview"]  # Default order
        
        # Sort: sections in order first, then others alphabetically
        sections_list.sort(key=lambda x: (section_order.index(x['key']) if x['key'] in section_order else 999, x['key']))
    
    context = {
        'grant': grant,
        'sections_list': sections_list,
    }
    return render(request, 'grants/detail.html', context)

