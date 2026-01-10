"""
Grant views.
"""
import json
import re
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.core.paginator import Paginator
from django.db.models import Q
from django.db import models
from django.utils import timezone
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django_ratelimit.decorators import ratelimit
from .models import Grant
from admin_panel.ai_client import build_grant_context, AiAssistantClient, AiAssistantError
from companies.models import Company, FundingSearch


@login_required
def index(request):
    """Dashboard/landing page."""
    return render(request, 'grants/index.html')


def terms_and_conditions(request):
    """Terms and conditions page - publicly accessible."""
    return render(request, 'grants/terms_and_conditions.html')


def cookie_policy(request):
    """Cookie policy page - publicly accessible."""
    return render(request, 'grants/cookie_policy.html')


def cookie_preferences(request):
    """Cookie preferences page - allows users to view and manage cookie settings."""
    from django.contrib import messages
    
    # Get current cookie preferences from session
    cookie_prefs = request.session.get('cookie_preferences', {
        'essential': True,  # Always required
        'analytics': request.session.get('cookie_preferences', {}).get('analytics', False),
        'marketing': request.session.get('cookie_preferences', {}).get('marketing', False),
    })
    
    if request.method == 'POST':
        # Update cookie preferences
        analytics = request.POST.get('analytics', 'off') == 'on'
        marketing = request.POST.get('marketing', 'off') == 'on'
        
        # Essential cookies are always enabled
        cookie_prefs = {
            'essential': True,
            'analytics': analytics,
            'marketing': marketing,
        }
        
        request.session['cookie_preferences'] = cookie_prefs
        request.session['cookie_preferences_updated'] = True
        messages.success(request, 'Your cookie preferences have been saved.')
        return redirect('grants:cookie_preferences')
    
    # Check if preferences have been set before
    preferences_set = 'cookie_preferences' in request.session
    
    context = {
        'cookie_prefs': cookie_prefs,
        'preferences_set': preferences_set,
    }
    
    return render(request, 'grants/cookie_preferences.html', context)


def privacy_policy(request):
    """Privacy policy page - publicly accessible."""
    return render(request, 'grants/privacy_policy.html')


def support(request):
    """Support/contact page - publicly accessible."""
    return render(request, 'grants/support.html')


def about(request):
    """About us page - publicly accessible."""
    return render(request, 'grants/about.html')


@login_required
def grants_list(request):
    """List all grants with search and filters."""
    # Get total count before any filtering
    total_grants_count = Grant.objects.count()
    
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
        # Filter by computed status using date ranges
        now = timezone.now()
        if status == 'open':
            # Open: deadline is in future (or null) and (opening_date is null or in past)
            grants = grants.filter(
                Q(deadline__isnull=True) | Q(deadline__gt=now)
            ).exclude(
                Q(opening_date__isnull=False) & Q(opening_date__gt=now)
            )
        elif status == 'closed':
            # Closed: deadline is in the past
            grants = grants.filter(deadline__lt=now)
        elif status == 'unknown':
            # Unknown: no opening_date and no deadline
            grants = grants.filter(opening_date__isnull=True, deadline__isnull=True)
    
    # Get filtered count before pagination
    filtered_grants_count = grants.count()
    
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
            'total_grants_count': total_grants_count,
            'filtered_grants_count': filtered_grants_count,
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
        'total_grants_count': total_grants_count,
        'filtered_grants_count': filtered_grants_count,
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
        elif grant.source in ['ukri', 'bbsrc', 'epsrc', 'mrc', 'stfc', 'ahrc', 'esrc', 'nerc']:
            # All UKRI councils use the same section ordering
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
    # SECURITY: Parse JSON with size limits
    from grants_aggregator.security_utils import safe_json_loads
    payload, error_response = safe_json_loads(request)
    if error_response:
        return error_response
    
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


@login_required
@require_http_methods(["POST"])
@ratelimit(key='user_or_ip', rate='30/h', block=True)
def competitiveness_checklist(request):
    """API endpoint: generate competitiveness checklist for a grant."""
    # SECURITY: Parse JSON with size limits
    from grants_aggregator.security_utils import safe_json_loads
    payload, error_response = safe_json_loads(request)
    if error_response:
        return error_response
    
    grant_id = payload.get("grant_id")
    if not grant_id:
        return JsonResponse({"error": "grant_id is required"}, status=400)
    
    grant = get_object_or_404(Grant, id=grant_id)
    
    try:
        client = AiAssistantClient()
    except AiAssistantError as e:
        return JsonResponse({"error": str(e)}, status=503)
    
    grant_ctx = build_grant_context(grant)
    parsed, raw_meta, latency_ms = client.competitiveness_checklist(grant_ctx)
    
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
    grant.competitiveness_checklist = checklist_data
    grant.save(update_fields=['competitiveness_checklist'])
    
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


@login_required
@require_http_methods(["POST"])
@ratelimit(key='user_or_ip', rate='30/h', block=True)
def exclusions_checklist(request):
    """API endpoint: generate exclusions checklist for a grant."""
    # SECURITY: Parse JSON with size limits
    from grants_aggregator.security_utils import safe_json_loads
    payload, error_response = safe_json_loads(request)
    if error_response:
        return error_response
    
    grant_id = payload.get("grant_id")
    if not grant_id:
        return JsonResponse({"error": "grant_id is required"}, status=400)
    
    grant = get_object_or_404(Grant, id=grant_id)
    
    try:
        client = AiAssistantClient()
    except AiAssistantError as e:
        return JsonResponse({"error": str(e)}, status=503)
    
    grant_ctx = build_grant_context(grant)
    parsed, raw_meta, latency_ms = client.exclusions_checklist(grant_ctx)
    
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
    grant.exclusions_checklist = checklist_data
    grant.save(update_fields=['exclusions_checklist'])
    
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


@login_required
@require_POST
def delete_grant(request, slug):
    """Delete a grant (admin only)."""
    grant = get_object_or_404(Grant, slug=slug)
    
    # Check if user is admin
    if not request.user.admin:
        messages.error(request, 'You do not have permission to delete grants.')
        return redirect('grants:detail', slug=slug)
    
    grant_title = grant.title
    grant.delete()
    messages.success(request, f'Grant "{grant_title}" has been deleted.')
    return redirect('grants:list')


@login_required
def global_search(request):
    """Global search across Grants, Companies, and Funding Searches."""
    query = request.GET.get('q', '').strip()
    
    grants = []
    companies = []
    funding_searches = []
    
    if query:
        # Search Grants
        grants = Grant.objects.filter(
            Q(title__icontains=query) |
            Q(summary__icontains=query) |
            Q(description__icontains=query)
        ).order_by('-created_at')[:10]
        
        # Search Companies (only user's companies)
        companies = Company.objects.filter(
            user=request.user
        ).filter(
            Q(name__icontains=query) |
            Q(company_number__icontains=query) |
            Q(notes__icontains=query)
        ).order_by('-created_at')[:10]
        
        # Search Funding Searches (only user's funding searches)
        funding_searches = FundingSearch.objects.filter(
            user=request.user
        ).filter(
            Q(name__icontains=query) |
            Q(notes__icontains=query) |
            Q(project_description__icontains=query)
        ).order_by('-created_at')[:10]
    
    # If AJAX request, return JSON
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        from django.http import JsonResponse
        from django.urls import reverse
        
        results = {
            'grants': [
                {
                    'id': g.id,
                    'title': g.title,
                    'slug': g.slug,
                    'source': g.get_source_display(),
                    'url': reverse('grants:detail', args=[g.slug]),
                    'summary': g.summary[:100] + '...' if g.summary and len(g.summary) > 100 else (g.summary or '')
                }
                for g in grants
            ],
            'companies': [
                {
                    'id': c.id,
                    'name': c.name,
                    'company_number': c.company_number or '',
                    'url': reverse('companies:detail', args=[c.id])
                }
                for c in companies
            ],
            'funding_searches': [
                {
                    'id': fs.id,
                    'name': fs.name,
                    'company_name': fs.company.name,
                    'url': reverse('companies:funding_search_detail', args=[fs.id])
                }
                for fs in funding_searches
            ]
        }
        return JsonResponse(results)
    
    context = {
        'query': query,
        'grants': grants,
        'companies': companies,
        'funding_searches': funding_searches,
        'grants_count': len(grants),
        'companies_count': len(companies),
        'funding_searches_count': len(funding_searches),
    }
    
    return render(request, 'grants/search_results.html', context)

