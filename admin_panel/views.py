"""
Admin panel views.
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.urls import reverse
from grants.models import Grant, ScrapeLog
from users.models import User
from companies.models import Company
from grants_aggregator import CELERY_AVAILABLE

# Import tasks only if Celery is available
if CELERY_AVAILABLE:
    from .tasks import trigger_ukri_scrape, refresh_companies_house_data
else:
    trigger_ukri_scrape = None
    refresh_companies_house_data = None


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
    
    # Check for recent Companies House refresh task
    last_refresh_task = None
    if CELERY_AVAILABLE:
        try:
            from celery.result import AsyncResult
            from django.core.cache import cache
            
            # Try to get last task ID from cache or URL
            task_id = request.GET.get('task_id') or cache.get('last_companies_refresh_task_id')
            if task_id:
                task_result = AsyncResult(task_id)
                if task_result.ready():
                    if task_result.state == 'SUCCESS':
                        last_refresh_task = {
                            'task_id': task_id,
                            'status': 'completed',
                            'result': task_result.result,
                            'completed': True
                        }
                    elif task_result.state == 'FAILURE':
                        last_refresh_task = {
                            'task_id': task_id,
                            'status': 'error',
                            'error': str(task_result.info),
                            'completed': True
                        }
                else:
                    last_refresh_task = {
                        'task_id': task_id,
                        'status': 'running',
                        'completed': False
                    }
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Error checking refresh task status: {e}")
    
    # Check Celery worker status
    celery_status = "Unknown"
    celery_details = ""
    if CELERY_AVAILABLE:
        try:
            from celery import current_app
            inspect = current_app.control.inspect()
            active_workers = inspect.active()
            if active_workers:
                celery_status = f"Active ({len(active_workers)} worker(s))"
                celery_details = f"Workers: {', '.join(active_workers.keys())}"
            else:
                celery_status = "No active workers"
                celery_details = "Tasks are queued but no workers are processing them. Check Celery service is running."
        except Exception as e:
            celery_status = f"Error checking: {str(e)}"
            celery_details = "Cannot connect to Celery workers. They may not be running or Redis connection failed."
    else:
        celery_status = "Celery not available"
        celery_details = "Celery is not initialized. Check Redis connection and web service logs."
    
    context = {
        'total_grants': total_grants,
        'open_grants': open_grants,
        'last_scrape': last_scrape,
        'celery_status': celery_status,
        'celery_details': celery_details,
        'last_refresh_task': last_refresh_task,
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
def scraper_status(request):
    """API endpoint to get scraper chain status and progress (for AJAX polling)."""
    from django.http import JsonResponse
    from django.utils import timezone
    from datetime import timedelta
    
    # Get the most recent chain (scrapers started in the last 10 minutes)
    recent_time = timezone.now() - timedelta(minutes=10)
    recent_logs = ScrapeLog.objects.filter(
        started_at__gte=recent_time
    ).order_by('-started_at')[:3]
    
    # Group by chain_started_at from metadata
    chains = {}
    for log in recent_logs:
        chain_started_at = log.metadata.get('chain_started_at') if log.metadata else None
        if chain_started_at:
            if chain_started_at not in chains:
                chains[chain_started_at] = []
            chains[chain_started_at].append(log)
    
    # Get the most recent chain
    if not chains:
        return JsonResponse({
            'status': 'idle',
            'progress': {'current': 0, 'total': 3, 'percentage': 0},
            'scrapers': []
        })
    
    # Get the most recent chain
    most_recent_chain_time = max(chains.keys())
    chain_logs = chains[most_recent_chain_time]
    
    # Sort by chain_position
    chain_logs.sort(key=lambda x: x.metadata.get('chain_position', 0) if x.metadata else 0)
    
    # Build scraper statuses
    scrapers = []
    completed_count = 0
    running_count = 0
    error_count = 0
    total_grants = 0
    
    for log in chain_logs:
        scraper_status = log.status
        if scraper_status == 'success':
            completed_count += 1
        elif scraper_status == 'running':
            running_count += 1
        elif scraper_status == 'error':
            error_count += 1
        
        total_grants += log.total_grants_processed()
        
        scrapers.append({
            'source': log.source,
            'status': scraper_status,
            'grants_created': log.grants_created,
            'grants_updated': log.grants_updated,
            'grants_skipped': log.grants_skipped,
            'error_message': log.error_message,
            'started_at': log.started_at.isoformat() if log.started_at else None,
            'completed_at': log.completed_at.isoformat() if log.completed_at else None,
        })
    
    # Determine overall status
    if error_count > 0:
        overall_status = 'error'
    elif running_count > 0:
        overall_status = 'running'
    elif completed_count == 3:
        overall_status = 'completed'
    else:
        overall_status = 'idle'
    
    # Calculate progress
    progress_percentage = (completed_count / 3) * 100
    
    return JsonResponse({
        'status': overall_status,
        'progress': {
            'current': completed_count,
            'total': 3,
            'percentage': round(progress_percentage, 1)
        },
        'scrapers': scrapers,
        'total_grants_processed': total_grants,
    })


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
    # SECURITY: get_object_or_404 provides better error handling
    user = get_object_or_404(User, id=id)
    
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
    # SECURITY: get_object_or_404 provides better error handling
    user = get_object_or_404(User, id=id)
    
    if request.method == 'POST':
        if user == request.user:
            messages.error(request, 'You cannot delete your own account.')
            return redirect('admin_panel:user_detail', id=id)
        
        user_email = user.email
        user.delete()
        messages.success(request, f'User {user_email} deleted successfully.')
        return redirect('admin_panel:users_list')
    
    return render(request, 'admin_panel/user_delete.html', {'target_user': user})


@login_required
@admin_required
def refresh_companies(request):
    """Trigger Companies House data refresh for all companies."""
    if request.method == 'POST':
        import logging
        logger = logging.getLogger(__name__)
        
        if not CELERY_AVAILABLE or refresh_companies_house_data is None:
            error_msg = 'Background task service (Celery) is not available. Please check Redis connection.'
            logger.error(error_msg)
            messages.error(request, error_msg)
            return redirect('admin_panel:dashboard')
        
        try:
            # Trigger the refresh task
            logger.info("Calling refresh_companies_house_data.delay()...")
            result = refresh_companies_house_data.delay()
            logger.info(f"Task queued successfully. Task ID: {result.id}")
            messages.success(request, f'Companies House data refresh started (Task ID: {result.id}).')
            
            # Store task ID in cache for later retrieval
            from django.core.cache import cache
            cache.set('last_companies_refresh_task_id', result.id, timeout=3600)  # 1 hour
            
            # Return JSON response with task ID for AJAX handling
            from django.http import JsonResponse
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'task_id': result.id, 'status': 'started'})
            
            # Redirect with task ID for non-AJAX requests
            return redirect(f"{reverse('admin_panel:dashboard')}?task_id={result.id}")
        except Exception as e:
            error_msg = f'Failed to start refresh: {str(e)}'
            logger.error(f"Error triggering refresh: {e}", exc_info=True)
            messages.error(request, error_msg)
        
        return redirect('admin_panel:dashboard')
    
    return redirect('admin_panel:dashboard')


@login_required
@admin_required
def companies_refresh_status(request):
    """API endpoint to get Companies House refresh status and progress (for AJAX polling)."""
    from django.http import JsonResponse
    from celery.result import AsyncResult
    
    # Get task ID from request
    task_id = request.GET.get('task_id')
    if not task_id:
        return JsonResponse({
            'status': 'idle',
            'progress': {'current': 0, 'total': 0, 'percentage': 0}
        })
    
    try:
        task_result = AsyncResult(task_id)
        
        if task_result.state == 'PENDING':
            status = 'running'
            progress = {'current': 0, 'total': 0, 'percentage': 0}
        elif task_result.state == 'PROGRESS':
            status = 'running'
            meta = task_result.info or {}
            progress = {
                'current': meta.get('current', 0),
                'total': meta.get('total', 0),
                'percentage': meta.get('percentage', 0),
                'updated': meta.get('updated', 0),
                'errors': meta.get('errors', 0)
            }
        elif task_result.state == 'SUCCESS':
            status = 'completed'
            result = task_result.result or {}
            progress = {
                'current': result.get('total', 0),
                'total': result.get('total', 0),
                'percentage': 100,
                'updated': result.get('updated', 0),
                'errors': result.get('errors', 0),
                'error_messages': result.get('error_messages', [])
            }
        elif task_result.state == 'FAILURE':
            status = 'error'
            progress = {
                'current': 0,
                'total': 0,
                'percentage': 0,
                'error': str(task_result.info)
            }
        else:
            status = 'unknown'
            progress = {'current': 0, 'total': 0, 'percentage': 0}
        
        return JsonResponse({
            'status': status,
            'progress': progress,
            'task_id': task_id
        })
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'progress': {'current': 0, 'total': 0, 'percentage': 0},
            'error': str(e)
        }, status=500)

