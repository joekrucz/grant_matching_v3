"""
Celery tasks for scraper orchestration.
"""
import requests
from celery import chain
from django.conf import settings
from django.utils import timezone
from grants.models import ScrapeLog
from grants_aggregator.celery import app


@app.task
def trigger_ukri_scrape():
    """Trigger UKRI scraper and chain to NIHR."""
    scrape_log = ScrapeLog.objects.create(
        source='ukri',
        status='running',
        started_at=timezone.now(),
    )
    
    try:
        response = requests.post(
            f"{settings.PYTHON_SCRAPER_URL}/run/ukri",
            json={'log_id': scrape_log.id},
            timeout=300,  # 5 minute timeout
        )
        response.raise_for_status()
        
        # Chain to NIHR scraper
        trigger_nihr_scrape.delay()
        
        scrape_log.status = 'success'
        scrape_log.completed_at = timezone.now()
        scrape_log.save()
    except Exception as e:
        scrape_log.status = 'error'
        scrape_log.error_message = str(e)
        scrape_log.completed_at = timezone.now()
        scrape_log.save()
        raise


@app.task
def trigger_nihr_scrape():
    """Trigger NIHR scraper and chain to Catapult."""
    scrape_log = ScrapeLog.objects.create(
        source='nihr',
        status='running',
        started_at=timezone.now(),
    )
    
    try:
        response = requests.post(
            f"{settings.PYTHON_SCRAPER_URL}/run/nihr",
            json={'log_id': scrape_log.id},
            timeout=300,
        )
        response.raise_for_status()
        
        # Chain to Catapult scraper
        trigger_catapult_scrape.delay()
        
        scrape_log.status = 'success'
        scrape_log.completed_at = timezone.now()
        scrape_log.save()
    except Exception as e:
        scrape_log.status = 'error'
        scrape_log.error_message = str(e)
        scrape_log.completed_at = timezone.now()
        scrape_log.save()
        raise


@app.task
def trigger_catapult_scrape():
    """Trigger Catapult scraper (last in chain)."""
    scrape_log = ScrapeLog.objects.create(
        source='catapult',
        status='running',
        started_at=timezone.now(),
    )
    
    try:
        response = requests.post(
            f"{settings.PYTHON_SCRAPER_URL}/run/catapult",
            json={'log_id': scrape_log.id},
            timeout=300,
        )
        response.raise_for_status()
        
        scrape_log.status = 'success'
        scrape_log.completed_at = timezone.now()
        scrape_log.save()
    except Exception as e:
        scrape_log.status = 'error'
        scrape_log.error_message = str(e)
        scrape_log.completed_at = timezone.now()
        scrape_log.save()
        raise

