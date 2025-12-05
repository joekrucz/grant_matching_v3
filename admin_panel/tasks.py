"""
Celery tasks for scraper orchestration.
"""
import requests
import logging
from celery import chain
from django.conf import settings
from django.utils import timezone
from grants.models import ScrapeLog

logger = logging.getLogger(__name__)

# Import Celery app safely
try:
    from grants_aggregator.celery import app
except Exception as e:
    logger.error(f"Failed to import Celery app: {e}")
    app = None


def _safe_scraper_request(url, log_id, timeout=300):
    """Make HTTP request to scraper service with error handling."""
    try:
        response = requests.post(
            url,
            json={'log_id': log_id},
            timeout=timeout,
        )
        response.raise_for_status()
        return True
    except requests.exceptions.ConnectionError as e:
        logger.error(f"Scraper service connection error: {e}")
        raise Exception(f"Scraper service is not available: {str(e)}")
    except requests.exceptions.Timeout as e:
        logger.error(f"Scraper service timeout: {e}")
        raise Exception(f"Scraper service request timed out: {str(e)}")
    except requests.exceptions.RequestException as e:
        logger.error(f"Scraper service request error: {e}")
        raise Exception(f"Scraper service error: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error calling scraper: {e}")
        raise


if app is not None:
    @app.task
    def trigger_ukri_scrape():
        """Trigger UKRI scraper and chain to NIHR."""
        scrape_log = ScrapeLog.objects.create(
            source='ukri',
            status='running',
            started_at=timezone.now(),
        )
        
        try:
            _safe_scraper_request(
                f"{settings.PYTHON_SCRAPER_URL}/run/ukri",
                scrape_log.id,
                timeout=300
            )
            
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
            _safe_scraper_request(
                f"{settings.PYTHON_SCRAPER_URL}/run/nihr",
                scrape_log.id,
                timeout=300
            )
            
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
            _safe_scraper_request(
                f"{settings.PYTHON_SCRAPER_URL}/run/catapult",
                scrape_log.id,
                timeout=300
            )
            
            scrape_log.status = 'success'
            scrape_log.completed_at = timezone.now()
            scrape_log.save()
        except Exception as e:
            scrape_log.status = 'error'
            scrape_log.error_message = str(e)
            scrape_log.completed_at = timezone.now()
            scrape_log.save()
            raise
else:
    # Dummy functions if Celery is not available
    def trigger_ukri_scrape():
        raise Exception("Celery is not available")
    
    def trigger_nihr_scrape():
        raise Exception("Celery is not available")
    
    def trigger_catapult_scrape():
        raise Exception("Celery is not available")

