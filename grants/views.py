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
    return render(request, 'grants/detail.html', {'grant': grant})

