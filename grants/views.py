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
        # Convert dict to list of tuples for template iteration
        sections_list = [(key, value) for key, value in sections_dict.items() if value]
        
        # Sort sections by preferred order (different for each source)
        if grant.source == 'catapult':
            section_order = ["overview", "challenge", "eligibility", "ipec", "funding", "dates", "how_to_apply"]
        elif grant.source == 'nihr':
            section_order = ["overview", "eligibility", "funding", "how_to_apply", "dates", "assessment", "contact", "terms"]
        elif grant.source == 'ukri':
            section_order = ["overview", "scope", "eligibility", "funding", "how_to_apply", "dates", "assessment", "contact", "terms"]
        elif grant.source == 'innovate_uk':
            # Matches Innovate UK site tab order
            section_order = ["summary", "eligibility", "scope", "dates", "how_to_apply", "supporting_information", "funding", "assessment", "contact", "terms"]
        else:
            section_order = ["overview"]  # Default order
        
        sections_list.sort(key=lambda x: (section_order.index(x[0]) if x[0] in section_order else 999, x[0]))
    
    context = {
        'grant': grant,
        'sections_list': sections_list,
    }
    return render(request, 'grants/detail.html', context)

