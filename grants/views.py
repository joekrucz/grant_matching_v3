"""
Grant views.
"""
import json
import re
from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django_ratelimit.decorators import ratelimit
from .models import Grant
from admin_panel.ai_client import build_grant_context, AiAssistantClient, AiAssistantError


@login_required
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
    sort_by = request.GET.get('sort', 'title')
    sort_order = request.GET.get('order', 'asc')
    
    if sort_by == 'deadline':
        if sort_order == 'desc':
            grants = grants.order_by('-deadline', 'title')
        else:
            # Soonest first: nulls last, then ascending
            grants = grants.extra(
                select={'deadline_null': 'CASE WHEN deadline IS NULL THEN 1 ELSE 0 END'}
            ).order_by('deadline_null', 'deadline', 'title')
    elif sort_by == 'funding':
        # For funding amount, we need to extract numeric values from strings
        # Since funding_amount is stored as a string (e.g., "£500,000", "Up to £1M")
        # we'll sort in Python after fetching
        grants_list = list(grants)
        
        def extract_funding_value(funding_str):
            """Extract numeric value from funding amount string."""
            if not funding_str:
                return 0
            # Remove currency symbols and extract numbers
            # Handle formats like "£500,000", "Up to £1M", "£1.5M", etc.
            numbers = re.findall(r'[\d,]+\.?\d*', funding_str.replace(',', ''))
            if numbers:
                value = float(numbers[0].replace(',', ''))
                # Handle multipliers (M = million, K = thousand)
                if 'M' in funding_str.upper() or 'million' in funding_str.lower():
                    value *= 1000000
                elif 'K' in funding_str.upper() or 'thousand' in funding_str.lower():
                    value *= 1000
                return value
            return 0
        
        if sort_order == 'desc':
            grants_list.sort(key=lambda g: extract_funding_value(g.funding_amount), reverse=True)
        else:
            grants_list.sort(key=lambda g: extract_funding_value(g.funding_amount))
        
        # Pagination for in-memory list
        paginator = Paginator(grants_list, 20)
        page_number = request.GET.get('page', 1)
        page_obj = paginator.get_page(page_number)
        
        context = {
            'page_obj': page_obj,
            'query': query,
            'source_filter': source,
            'status_filter': status,
            'sort_by': sort_by,
            'sort_order': sort_order,
        }
        return render(request, 'grants/list.html', context)
    else:
        # Default: alphabetical by title
        if sort_order == 'desc':
            grants = grants.order_by('-title')
        else:
            grants = grants.order_by('title')
    
    # Pagination
    paginator = Paginator(grants, 20)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    
    context = {
        'page_obj': page_obj,
        'query': query,
        'source_filter': source,
        'status_filter': status,
        'sort_by': sort_by,
        'sort_order': sort_order,
    }
    return render(request, 'grants/list.html', context)


@login_required
def grant_detail(request, slug):
    """Grant detail page."""
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


@login_required
@require_http_methods(["POST"])
@ratelimit(key='user_or_ip', rate='30/h', block=True)
def eligibility_checklist(request):
    """API endpoint: generate eligibility checklist for a grant."""
    try:
        payload = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON payload"}, status=400)
    
    grant_id = payload.get("grant_id")
    if not grant_id:
        return JsonResponse({"error": "grant_id is required"}, status=400)
    
    grant = get_object_or_404(Grant, id=grant_id)
    
    try:
        client = AiAssistantClient()
    except AiAssistantError as e:
        return JsonResponse({"error": str(e)}, status=503)
    
    grant_ctx = build_grant_context(grant)
    parsed, raw_meta, latency_ms = client.eligibility_checklist(grant_ctx)
    
    checklist_items = parsed.get("checklist_items") or []
    notes = parsed.get("notes") or []
    missing_info = parsed.get("missing_info") or []
    
    # Save checklist to grant
    checklist_data = {
        "checklist_items": checklist_items,
        "notes": notes,
        "missing_info": missing_info,
        "meta": {
            "model": raw_meta.get("model"),
            "input_tokens": (raw_meta.get("usage") or {}).get("input_tokens"),
            "output_tokens": (raw_meta.get("usage") or {}).get("output_tokens"),
            "latency_ms": latency_ms,
        },
    }
    grant.eligibility_checklist = checklist_data
    grant.save(update_fields=['eligibility_checklist'])
    
    return JsonResponse({
        "checklist_items": checklist_items,
        "notes": notes,
        "missing_info": missing_info,
        "meta": {
            "model": raw_meta.get("model"),
            "input_tokens": (raw_meta.get("usage") or {}).get("input_tokens"),
            "output_tokens": (raw_meta.get("usage") or {}).get("output_tokens"),
            "latency_ms": latency_ms,
        },
    })

