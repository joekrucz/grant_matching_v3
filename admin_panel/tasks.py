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

# Import Celery safely - use shared_task for better task discovery
try:
    from celery import shared_task
    CELERY_TASKS_AVAILABLE = True
except Exception as e:
    logger.warning(f"Celery tasks not available: {e}")
    CELERY_TASKS_AVAILABLE = False
    # Create a dummy decorator
    def shared_task(*args, **kwargs):
        def decorator(func):
            return func
        return decorator


def _safe_scraper_request(url, log_id, timeout=300):
    """Make HTTP request to scraper service with error handling."""
    logger.info(f"Attempting to connect to scraper service at: {url}")
    logger.info(f"PYTHON_SCRAPER_URL from settings: {settings.PYTHON_SCRAPER_URL}")
    
    # Check if URL matches settings
    if url != settings.PYTHON_SCRAPER_URL:
        logger.warning(f"URL mismatch: requested {url} but settings has {settings.PYTHON_SCRAPER_URL}")
    
    try:
        response = requests.post(
            url,
            json={'log_id': log_id},
            timeout=timeout,
            headers={'Content-Type': 'application/json'},
        )
        response.raise_for_status()
        data = response.json() if response.content else {}
        logger.info(f"Successfully connected to scraper service: {url}")
        return {"success": True, "data": data}
    except requests.exceptions.ConnectionError as e:
        logger.error(f"Scraper service connection error: {e}")
        logger.error(f"Failed to connect to: {url}")
        logger.error(f"PYTHON_SCRAPER_URL setting: {settings.PYTHON_SCRAPER_URL}")
        logger.error("Troubleshooting tips:")
        logger.error("1. Check if scraper service is running on Railway")
        logger.error("2. Verify PYTHON_SCRAPER_URL matches the scraper service's actual port")
        logger.error("3. Check scraper service logs to see what port it's using")
        logger.error("4. Ensure PYTHON_SCRAPER_URL is set in both web and Celery services")
        return {"success": False, "error": f"Scraper service is not available: {str(e)}"}
    except requests.exceptions.Timeout as e:
        logger.error(f"Scraper service timeout: {e}")
        return {"success": False, "error": f"Scraper service request timed out: {str(e)}"}
    except requests.exceptions.RequestException as e:
        logger.error(f"Scraper service request error: {e}")
        return {"success": False, "error": f"Scraper service error: {str(e)}"}
    except Exception as e:
        logger.error(f"Unexpected error calling scraper: {e}", exc_info=True)
        return {"success": False, "error": f"Unexpected scraper error: {str(e)}"}


def _extract_counts(data):
    """Extract common count fields from scraper responses."""
    if not isinstance(data, dict):
        return {"created": 0, "updated": 0, "skipped": 0, "message": None}
    return {
        "created": data.get("created", 0),
        "updated": data.get("updated", 0),
        "skipped": data.get("skipped", 0),
        "message": data.get("message"),
    }


if CELERY_TASKS_AVAILABLE:
    @shared_task
    def trigger_ukri_scrape(chain_started_at_str=None, continue_chain=True):
        """Trigger UKRI scraper and optionally chain to NIHR."""
        logger.info("trigger_ukri_scrape task started")
        chain_started_at = timezone.now() if chain_started_at_str is None else timezone.datetime.fromisoformat(chain_started_at_str.replace('Z', '+00:00'))
        chain_total = 4 if continue_chain else 1
        scrape_log = ScrapeLog.objects.create(
            source='ukri',
            status='running',
            started_at=chain_started_at,
            metadata={'chain_started_at': chain_started_at.isoformat(), 'chain_position': 1, 'chain_total': chain_total}
        )
        logger.info(f"Created ScrapeLog with ID: {scrape_log.id}")
        
        try:
            result = _safe_scraper_request(
                f"{settings.PYTHON_SCRAPER_URL}/run/ukri",
                scrape_log.id,
                timeout=300
            )
            
            counts = _extract_counts(result.get("data"))
            scrape_log.metadata = {
                **(scrape_log.metadata or {}),
                "counts": counts,
                "chain_started_at": chain_started_at.isoformat(),
                "chain_position": 1,
                "chain_total": chain_total,
            }
            # Refresh from DB to get grants_found and other counts set by Django API
            scrape_log.refresh_from_db()
            if result.get("success"):
            scrape_log.status = 'success'
            else:
                scrape_log.status = 'error'
                scrape_log.error_message = result.get("error")
            scrape_log.completed_at = timezone.now()
            scrape_log.save()
        except Exception as e:
            scrape_log.refresh_from_db()
            scrape_log.status = 'error'
            scrape_log.error_message = str(e)
            scrape_log.completed_at = timezone.now()
            scrape_log.save()
        finally:
            # Always trigger next scraper if chaining
            if continue_chain:
                trigger_nihr_scrape.delay(chain_started_at.isoformat(), continue_chain=True)


    @shared_task
    def trigger_nihr_scrape(chain_started_at_str=None, continue_chain=True):
        """Trigger NIHR scraper and optionally chain to Catapult."""
        from datetime import datetime
        chain_started_at = datetime.fromisoformat(chain_started_at_str.replace('Z', '+00:00')) if chain_started_at_str else timezone.now()
        chain_total = 4 if continue_chain else 1
        scrape_log = ScrapeLog.objects.create(
            source='nihr',
            status='running',
            started_at=timezone.now(),
            metadata={'chain_started_at': chain_started_at.isoformat(), 'chain_position': 2, 'chain_total': chain_total}
        )
        
        try:
            result = _safe_scraper_request(
                f"{settings.PYTHON_SCRAPER_URL}/run/nihr",
                scrape_log.id,
                timeout=300
            )
            
            counts = _extract_counts(result.get("data"))
            scrape_log.metadata = {
                **(scrape_log.metadata or {}),
                "counts": counts,
                "chain_started_at": chain_started_at.isoformat(),
                "chain_position": 2,
                "chain_total": chain_total,
            }
            # Refresh from DB to get grants_found and other counts set by Django API
            scrape_log.refresh_from_db()
            if result.get("success"):
            scrape_log.status = 'success'
            else:
                scrape_log.status = 'error'
                scrape_log.error_message = result.get("error")
            scrape_log.completed_at = timezone.now()
            scrape_log.save()
        except Exception as e:
            scrape_log.refresh_from_db()
            scrape_log.status = 'error'
            scrape_log.error_message = str(e)
            scrape_log.completed_at = timezone.now()
            scrape_log.save()
        finally:
            # Always trigger next scraper if chaining
            if continue_chain:
                trigger_catapult_scrape.delay(chain_started_at_str, continue_chain=True)


    @shared_task
    def trigger_catapult_scrape(chain_started_at_str=None, continue_chain=True):
        """Trigger Catapult scraper and optionally chain to Innovate UK."""
        from datetime import datetime
        chain_started_at = datetime.fromisoformat(chain_started_at_str.replace('Z', '+00:00')) if chain_started_at_str else timezone.now()
        chain_total = 4 if continue_chain else 1
        scrape_log = ScrapeLog.objects.create(
            source='catapult',
            status='running',
            started_at=timezone.now(),
            metadata={'chain_started_at': chain_started_at.isoformat(), 'chain_position': 3, 'chain_total': chain_total}
        )
        
        try:
            result = _safe_scraper_request(
                f"{settings.PYTHON_SCRAPER_URL}/run/catapult",
                scrape_log.id,
                timeout=300
            )
            
            counts = _extract_counts(result.get("data"))
            scrape_log.metadata = {
                **(scrape_log.metadata or {}),
                "counts": counts,
                "chain_started_at": chain_started_at.isoformat(),
                "chain_position": 3,
                "chain_total": chain_total,
            }
            # Refresh from DB to get grants_found and other counts set by Django API
            scrape_log.refresh_from_db()
            if result.get("success"):
                scrape_log.status = 'success'
            else:
                scrape_log.status = 'error'
                scrape_log.error_message = result.get("error")
            scrape_log.completed_at = timezone.now()
            scrape_log.save()
        except Exception as e:
            scrape_log.refresh_from_db()
            scrape_log.status = 'error'
            scrape_log.error_message = str(e)
            scrape_log.completed_at = timezone.now()
            scrape_log.save()
        finally:
            # Always trigger next scraper if chaining
            if continue_chain:
                trigger_innovate_uk_scrape.delay(chain_started_at_str, continue_chain=True)


    @shared_task
    def trigger_innovate_uk_scrape(chain_started_at_str=None, continue_chain=True):
        """Trigger Innovate UK scraper (last in chain or standalone)."""
        from datetime import datetime
        chain_started_at = datetime.fromisoformat(chain_started_at_str.replace('Z', '+00:00')) if chain_started_at_str else timezone.now()
        chain_total = 4 if continue_chain else 1
        scrape_log = ScrapeLog.objects.create(
            source='innovate_uk',
            status='running',
            started_at=timezone.now(),
            metadata={'chain_started_at': chain_started_at.isoformat(), 'chain_position': 4, 'chain_total': chain_total}
        )
        
        try:
            result = _safe_scraper_request(
                f"{settings.PYTHON_SCRAPER_URL}/run/innovate_uk",
                scrape_log.id,
                timeout=300
            )
            
            counts = _extract_counts(result.get("data"))
            scrape_log.metadata = {
                **(scrape_log.metadata or {}),
                "counts": counts,
                "chain_started_at": chain_started_at.isoformat(),
                "chain_position": 4,
                "chain_total": 4,
            }
            # Refresh from DB to get grants_found and other counts set by Django API
            scrape_log.refresh_from_db()
            if result.get("success"):
            scrape_log.status = 'success'
            else:
                scrape_log.status = 'error'
                scrape_log.error_message = result.get("error")
            scrape_log.completed_at = timezone.now()
            scrape_log.save()
        except Exception as e:
            scrape_log.refresh_from_db()
            scrape_log.status = 'error'
            scrape_log.error_message = str(e)
            scrape_log.completed_at = timezone.now()
            scrape_log.save()
else:
    # Dummy functions if Celery is not available
    def trigger_ukri_scrape():
        raise Exception("Celery is not available")
    
    def trigger_nihr_scrape():
        raise Exception("Celery is not available")
    
    def trigger_catapult_scrape():
        raise Exception("Celery is not available")
    
    def trigger_innovate_uk_scrape():
        raise Exception("Celery is not available")


if CELERY_TASKS_AVAILABLE:
    @shared_task(bind=True)
    def refresh_companies_house_data(self):
        """
        Refresh Companies House data for all registered companies.
        Updates company information and filing history.
        """
        from companies.models import Company
        from companies.services import CompaniesHouseService, CompaniesHouseError
        
        logger.info("refresh_companies_house_data task started")
        
        # Get all registered companies with company numbers
        companies = Company.objects.filter(
            is_registered=True,
            company_number__isnull=False
        ).exclude(company_number='')
        
        total_companies = companies.count()
        logger.info(f"Found {total_companies} companies to refresh")
        
        updated_count = 0
        error_count = 0
        errors = []
        
        # Progress tracking function
        def progress_callback(current, total):
            percentage = (current / total) * 100 if total > 0 else 0
            self.update_state(
                state='PROGRESS',
                meta={
                    'current': current,
                    'total': total,
                    'percentage': round(percentage, 1),
                    'updated': updated_count,
                    'errors': error_count
                }
            )
        
        for idx, company in enumerate(companies):
            try:
                # Fetch updated company data
                api_data = CompaniesHouseService.fetch_company(company.company_number)
                
                # Fetch filing history
                try:
                    filing_history = CompaniesHouseService.fetch_filing_history(company.company_number)
                except CompaniesHouseError as e:
                    logger.warning(f"Could not fetch filing history for company {company.company_number}: {e}")
                    filing_history = None
                
                # Normalize data
                normalized_data = CompaniesHouseService.normalize_company_data(api_data, filing_history)
                
                # Update company fields
                company.name = normalized_data.get('name', company.name)
                company.company_type = normalized_data.get('company_type', company.company_type)
                company.status = normalized_data.get('status', company.status)
                company.sic_codes = normalized_data.get('sic_codes', company.sic_codes)
                company.address = normalized_data.get('address', company.address)
                company.date_of_creation = normalized_data.get('date_of_creation', company.date_of_creation)
                company.raw_data = normalized_data.get('raw_data', company.raw_data)
                
                # Update filing history if available
                if filing_history:
                    company.filing_history = filing_history
                
                company.save()
                updated_count += 1
                logger.info(f"Updated company {company.company_number} ({idx + 1}/{total_companies})")
                
            except CompaniesHouseError as e:
                error_count += 1
                error_msg = f"Company {company.company_number}: {str(e)}"
                errors.append(error_msg)
                logger.error(error_msg)
            except Exception as e:
                error_count += 1
                error_msg = f"Company {company.company_number}: Unexpected error - {str(e)}"
                errors.append(error_msg)
                logger.error(error_msg, exc_info=True)
            
            # Update progress
            progress_callback(idx + 1, total_companies)
        
        result = {
            'status': 'completed',
            'total': total_companies,
            'updated': updated_count,
            'errors': error_count,
            'error_messages': errors[:10]  # Limit to first 10 errors
        }
        
        logger.info(f"Refresh completed: {updated_count} updated, {error_count} errors")
        return result
else:
    def refresh_companies_house_data():
        raise Exception("Celery is not available")

