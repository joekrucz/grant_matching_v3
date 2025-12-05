"""
Admin panel views.
"""
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from grants.models import Grant, ScrapeLog
from users.models import User
from companies.models import Company
from grants_aggregator import CELERY_AVAILABLE

# Import tasks only if Celery is available
if CELERY_AVAILABLE:
    from .tasks import trigger_ukri_scrape
else:
    trigger_ukri_scrape = None


def admin_required(view_func):
    """Decorator to require admin access."""
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated or not request.user.admin:
            messages.error(request, 'Admin access required.')
            return redirect('/')
        return view_func(request, *args, **kwargs)
    return wrapper


@login_required
@admin_required
def dashboard(request):
    """Admin dashboard."""
    total_grants = Grant.objects.count()
    open_grants = Grant.objects.filter(status='open').count()
    last_scrape = ScrapeLog.objects.filter(status='success').order_by('-completed_at').first()
    
    # Check Celery worker status
    celery_status = "Unknown"
    if CELERY_AVAILABLE:
        try:
            from celery import current_app
            inspect = current_app.control.inspect()
            active_workers = inspect.active()
            if active_workers:
                celery_status = f"Active ({len(active_workers)} worker(s))"
            else:
                celery_status = "No active workers"
        except Exception as e:
            celery_status = f"Error checking: {str(e)}"
    else:
        celery_status = "Celery not available"
    
    context = {
        'total_grants': total_grants,
        'open_grants': open_grants,
        'last_scrape': last_scrape,
        'celery_status': celery_status,
    }
    return render(request, 'admin_panel/dashboard.html', context)


@login_required
@admin_required
def run_scrapers(request):
    """Trigger scraper workers."""
    if request.method == 'POST':
        import logging
        logger = logging.getLogger(__name__)
        
        logger.info(f"Run scrapers button clicked. CELERY_AVAILABLE={CELERY_AVAILABLE}, trigger_ukri_scrape={trigger_ukri_scrape}")
        
        if not CELERY_AVAILABLE or trigger_ukri_scrape is None:
            error_msg = 'Background task service (Celery) is not available. Please check Redis connection.'
            logger.error(error_msg)
            messages.error(request, error_msg)
            return redirect('admin_panel:dashboard')
        
        try:
            # Trigger the scraper chain
            logger.info("Calling trigger_ukri_scrape.delay()...")
            result = trigger_ukri_scrape.delay()
            logger.info(f"Task queued successfully. Task ID: {result.id}")
            messages.success(request, f'Scrapers triggered (Task ID: {result.id}). Check scrape logs for progress.')
        except Exception as e:
            error_msg = f'Failed to trigger scrapers: {str(e)}'
            logger.error(f"Error triggering scrapers: {e}", exc_info=True)
            messages.error(request, error_msg)
        return redirect('admin_panel:scrape_logs')
    
    return redirect('admin_panel:dashboard')


@login_required
@admin_required
def wipe_grants(request):
    """Delete all grants (admin only)."""
    if request.method == 'POST':
        count = Grant.objects.count()
        Grant.objects.all().delete()
        messages.success(request, f'Deleted {count} grants.')
        return redirect('admin_panel:dashboard')
    
    return render(request, 'admin_panel/wipe_grants.html')


@login_required
@admin_required
def scrape_logs(request):
    """List scrape logs."""
    logs = ScrapeLog.objects.all().order_by('-started_at')
    
    # Pagination
    paginator = Paginator(logs, 50)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    
    return render(request, 'admin_panel/scrape_logs.html', {'page_obj': page_obj})


@login_required
@admin_required
def users_list(request):
    """List all users."""
    users = User.objects.all().order_by('-date_joined')
    
    # Pagination
    paginator = Paginator(users, 50)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    
    return render(request, 'admin_panel/users_list.html', {'page_obj': page_obj})


@login_required
@admin_required
def user_detail(request, id):
    """User detail page."""
    user = User.objects.get(id=id)
    
    if request.method == 'POST':
        user.name = request.POST.get('name', user.name)
        user.email = request.POST.get('email', user.email)
        user.admin = request.POST.get('admin') == 'on'
        user.is_active = request.POST.get('is_active') == 'on'
        user.save()
        messages.success(request, 'User updated successfully.')
        return redirect('admin_panel:user_detail', id=id)
    
    context = {
        'target_user': user,
    }
    return render(request, 'admin_panel/user_detail.html', context)


@login_required
@admin_required
def user_delete(request, id):
    """Delete user (admin only)."""
    user = User.objects.get(id=id)
    
    if request.method == 'POST':
        if user == request.user:
            messages.error(request, 'You cannot delete your own account.')
            return redirect('admin_panel:user_detail', id=id)
        
        user_email = user.email
        user.delete()
        messages.success(request, f'User {user_email} deleted successfully.')
        return redirect('admin_panel:users_list')
    
    return render(request, 'admin_panel/user_delete.html', {'target_user': user})

