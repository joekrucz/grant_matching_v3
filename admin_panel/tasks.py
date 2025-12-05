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
    logger.info(f"Attempting to connect to scraper service at: {url}")
    try:
        response = requests.post(
            url,
            json={'log_id': log_id},
            timeout=timeout,
        )
        response.raise_for_status()
        logger.info(f"Successfully connected to scraper service: {url}")
        return True
    except requests.exceptions.ConnectionError as e:
        logger.error(f"Scraper service connection error: {e}")
        logger.error(f"Failed to connect to: {url}")
        logger.error(f"PYTHON_SCRAPER_URL setting: {settings.PYTHON_SCRAPER_URL}")
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
        logger.info("trigger_ukri_scrape task started")
        chain_started_at = timezone.now()
        scrape_log = ScrapeLog.objects.create(
            source='ukri',
            status='running',
            started_at=chain_started_at,
            metadata={'chain_started_at': chain_started_at.isoformat(), 'chain_position': 1, 'chain_total': 3}
        )
        logger.info(f"Created ScrapeLog with ID: {scrape_log.id}")
        
        try:
            _safe_scraper_request(
                f"{settings.PYTHON_SCRAPER_URL}/run/ukri",
                scrape_log.id,
                timeout=300
            )
            
            # Chain to NIHR scraper
            trigger_nihr_scrape.delay(chain_started_at.isoformat())
            
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
    def trigger_nihr_scrape(chain_started_at_str=None):
        """Trigger NIHR scraper and chain to Catapult."""
        from datetime import datetime
        chain_started_at = datetime.fromisoformat(chain_started_at_str.replace('Z', '+00:00')) if chain_started_at_str else timezone.now()
        scrape_log = ScrapeLog.objects.create(
            source='nihr',
            status='running',
            started_at=timezone.now(),
            metadata={'chain_started_at': chain_started_at.isoformat(), 'chain_position': 2, 'chain_total': 3}
        )
        
        try:
            _safe_scraper_request(
                f"{settings.PYTHON_SCRAPER_URL}/run/nihr",
                scrape_log.id,
                timeout=300
            )
            
            # Chain to Catapult scraper
            trigger_catapult_scrape.delay(chain_started_at_str)
            
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
    def trigger_catapult_scrape(chain_started_at_str=None):
        """Trigger Catapult scraper (last in chain)."""
        from datetime import datetime
        chain_started_at = datetime.fromisoformat(chain_started_at_str.replace('Z', '+00:00')) if chain_started_at_str else timezone.now()
        scrape_log = ScrapeLog.objects.create(
            source='catapult',
            status='running',
            started_at=timezone.now(),
            metadata={'chain_started_at': chain_started_at.isoformat(), 'chain_position': 3, 'chain_total': 3}
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

