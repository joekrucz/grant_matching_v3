"""
Celery tasks for scraper orchestration.
"""
import requests
import logging
import asyncio
import time
from celery import chain
from django.conf import settings
from django.utils import timezone
from grants.models import ScrapeLog
from asgiref.sync import sync_to_async
from openai import RateLimitError, APIError

# Redis for distributed rate limiting
try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

logger = logging.getLogger(__name__)


def sanitize_checklist_items(checklist_items):
    """Remove null bytes from checklist items to prevent PostgreSQL errors.
    
    PostgreSQL cannot store null bytes (\u0000) in text/JSON fields.
    This function sanitizes checklist items by removing any null bytes.
    """
    if not checklist_items:
        return []
    sanitized = []
    for item in checklist_items:
        if isinstance(item, str):
            # Remove null bytes and other problematic characters
            sanitized_item = item.replace('\u0000', '').replace('\x00', '')
            sanitized.append(sanitized_item)
        else:
            # Convert to string and sanitize
            sanitized_item = str(item).replace('\u0000', '').replace('\x00', '')
            sanitized.append(sanitized_item)
    return sanitized


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
    @shared_task(bind=True)
    def trigger_ukri_scrape(self, chain_started_at_str=None, continue_chain=True):
        """Trigger UKRI scraper and optionally chain to NIHR."""
        logger.info("trigger_ukri_scrape task started")
        chain_started_at = timezone.now() if chain_started_at_str is None else timezone.datetime.fromisoformat(chain_started_at_str.replace('Z', '+00:00'))
        chain_total = 4 if continue_chain else 1
        scrape_log = ScrapeLog.objects.create(
            source='ukri',
            status='running',
            started_at=chain_started_at,
            metadata={
                'chain_started_at': chain_started_at.isoformat(), 
                'chain_position': 1, 
                'chain_total': chain_total,
                'task_id': self.request.id
            }
        )
        logger.info(f"Created ScrapeLog with ID: {scrape_log.id}, Task ID: {self.request.id}")
        
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
            
            # Chain to next scraper if needed
            if continue_chain:
                trigger_nihr_scrape.delay(chain_started_at.isoformat(), continue_chain=True)
        except Exception as e:
            scrape_log.refresh_from_db()
            scrape_log.status = 'error'
            scrape_log.error_message = str(e)
            scrape_log.completed_at = timezone.now()
            scrape_log.save()


    @shared_task(bind=True)
    def trigger_nihr_scrape(self, chain_started_at_str=None, continue_chain=True):
        """Trigger NIHR scraper and optionally chain to Catapult."""
        from datetime import datetime
        chain_started_at = datetime.fromisoformat(chain_started_at_str.replace('Z', '+00:00')) if chain_started_at_str else timezone.now()
        chain_total = 4 if continue_chain else 1
        scrape_log = ScrapeLog.objects.create(
            source='nihr',
            status='running',
            started_at=timezone.now(),
            metadata={
                'chain_started_at': chain_started_at.isoformat(), 
                'chain_position': 2, 
                'chain_total': chain_total,
                'task_id': self.request.id
            }
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
            
            # Chain to next scraper if needed
            if continue_chain:
                trigger_catapult_scrape.delay(chain_started_at_str, continue_chain=True)
        except Exception as e:
            scrape_log.refresh_from_db()
            scrape_log.status = 'error'
            scrape_log.error_message = str(e)
            scrape_log.completed_at = timezone.now()
            scrape_log.save()


    @shared_task(bind=True)
    def trigger_catapult_scrape(self, chain_started_at_str=None, continue_chain=True):
        """Trigger Catapult scraper and optionally chain to Innovate UK."""
        from datetime import datetime
        chain_started_at = datetime.fromisoformat(chain_started_at_str.replace('Z', '+00:00')) if chain_started_at_str else timezone.now()
        chain_total = 4 if continue_chain else 1
        scrape_log = ScrapeLog.objects.create(
            source='catapult',
            status='running',
            started_at=timezone.now(),
            metadata={
                'chain_started_at': chain_started_at.isoformat(), 
                'chain_position': 3, 
                'chain_total': chain_total,
                'task_id': self.request.id
            }
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
            
            # Chain to next scraper if needed
            if continue_chain:
                trigger_innovate_uk_scrape.delay(chain_started_at_str, continue_chain=True)
        except Exception as e:
            scrape_log.refresh_from_db()
            scrape_log.status = 'error'
            scrape_log.error_message = str(e)
            scrape_log.completed_at = timezone.now()
            scrape_log.save()


    @shared_task(bind=True)
    def trigger_innovate_uk_scrape(self, chain_started_at_str=None, continue_chain=True):
        """Trigger Innovate UK scraper (last in chain or standalone)."""
        from datetime import datetime
        chain_started_at = datetime.fromisoformat(chain_started_at_str.replace('Z', '+00:00')) if chain_started_at_str else timezone.now()
        chain_total = 4 if continue_chain else 1
        scrape_log = ScrapeLog.objects.create(
            source='innovate_uk',
            status='running',
            started_at=timezone.now(),
            metadata={
                'chain_started_at': chain_started_at.isoformat(), 
                'chain_position': 4, 
                'chain_total': chain_total,
                'task_id': self.request.id
            }
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


async def _generate_checklists_async(task_id, grants, checklist_type, client):
    """
    Async version: Generate checklists for all grants with parallel processing and rate limiting.
    """
    from grants.models import Grant
    from admin_panel.ai_client import build_grant_context
    
    processed_count = 0
    success_count = 0
    skipped_count = 0
    error_count = 0
    errors = []
    total_grants = len(grants)
    
    # Get batch size from system settings (same as grant matching)
    try:
        from admin_panel.models import SystemSettings
        system_settings = SystemSettings.get_settings()
        parallel_batch_size = max(1, min(100, system_settings.grant_matching_batch_size))  # Clamp between 1-100
    except Exception as e:
        logger.warning(f"Could not load system settings, defaulting to batch_size=50: {e}")
        parallel_batch_size = 50
    
    # Rate limiting: Optimized for tier 2 API limits (5,000 RPM)
    target_rpm = 4000  # Use 80% of 5000 RPM limit (with 0.8 safety factor = 3200 effective)
    safety_factor = 0.8
    
    parallel_factor = 1.0 + (parallel_batch_size - 1) * 0.3
    base_delay = 60.0 / (target_rpm * safety_factor)
    rate_limit_delay = base_delay * parallel_factor
    rate_limit_delay = max(0.01, min(2.0, rate_limit_delay))  # Allow down to 10ms
    
    logger.info(f"Rate limiting configured: delay={rate_limit_delay:.3f}s between requests, parallel_batch_size={parallel_batch_size}, target_rpm={target_rpm}")
    
    # Process grants in parallel batches
    semaphore = asyncio.Semaphore(parallel_batch_size)
    
    # Distributed rate limiter using Redis (coordinates across all Celery worker processes)
    redis_client = None
    if REDIS_AVAILABLE:
        try:
            from urllib.parse import urlparse
            redis_url = getattr(settings, 'REDIS_URL', 'redis://redis:6379/0')
            parsed = urlparse(redis_url)
            redis_client = redis.Redis(
                host=parsed.hostname or 'redis',
                port=parsed.port or 6379,
                db=int(parsed.path.lstrip('/')) if parsed.path else 0,
                decode_responses=False
            )
            redis_client.ping()
            logger.info("Using Redis for distributed rate limiting")
        except Exception as e:
            logger.warning(f"Redis not available for rate limiting, falling back to in-process limiter: {e}")
            redis_client = None
    
    # Fallback: in-process rate limiter
    rate_limiter_lock = asyncio.Lock()
    last_request_time = [0.0]
    adaptive_delay_multiplier = [1.0]
    
    async def process_grant_with_retry(grant, grant_index):
        """Process a single grant with retry logic."""
        nonlocal processed_count, success_count, skipped_count, error_count, errors
        
        # Check if checklist already exists and skip if it does
        skip_eligibility = False
        skip_competitiveness = False
        skip_exclusions = False
        skip_trl = False
        
        if checklist_type in ['eligibility', 'both', 'all']:
            if grant.eligibility_checklist and grant.eligibility_checklist.get('checklist_items'):
                skip_eligibility = True
        
        if checklist_type in ['competitiveness', 'both', 'all']:
            if grant.competitiveness_checklist and grant.competitiveness_checklist.get('checklist_items'):
                skip_competitiveness = True
        
        if checklist_type in ['exclusions', 'all']:
            if grant.exclusions_checklist and grant.exclusions_checklist.get('checklist_items'):
                skip_exclusions = True
        
        if checklist_type in ['trl', 'all']:
            # Skip if grant already has TRL levels OR is marked as technology-focused
            if grant.trl_requirements:
                has_trl_levels = grant.trl_requirements.get('trl_levels') and len(grant.trl_requirements.get('trl_levels', [])) > 0
                is_tech_focused = grant.trl_requirements.get('is_technology_focused', False)
                if has_trl_levels or is_tech_focused:
                    skip_trl = True
        
        # Skip this grant if all requested checklists already exist
        if checklist_type == 'eligibility' and skip_eligibility:
            skipped_count += 1
            return {'skipped': True, 'grant_id': grant.id}
        elif checklist_type == 'competitiveness' and skip_competitiveness:
            skipped_count += 1
            return {'skipped': True, 'grant_id': grant.id}
        elif checklist_type == 'exclusions' and skip_exclusions:
            skipped_count += 1
            return {'skipped': True, 'grant_id': grant.id}
        elif checklist_type == 'trl' and skip_trl:
            skipped_count += 1
            return {'skipped': True, 'grant_id': grant.id}
        elif checklist_type == 'both' and skip_eligibility and skip_competitiveness:
            skipped_count += 1
            return {'skipped': True, 'grant_id': grant.id}
        elif checklist_type == 'all' and skip_eligibility and skip_competitiveness and skip_exclusions and skip_trl:
            skipped_count += 1
            return {'skipped': True, 'grant_id': grant.id}
        
        grant_ctx = build_grant_context(grant)
        eligibility_generated = False
        competitiveness_generated = False
        exclusions_generated = False
        trl_generated = False
        
        max_retries = 3
        for attempt in range(max_retries):
            try:
                # Rate limiting
                if redis_client:
                    adaptive_key = "openai_rate_limiter:adaptive_multiplier"
                    adaptive_multiplier = 1.0
                    try:
                        adaptive_bytes = redis_client.get(adaptive_key)
                        if adaptive_bytes:
                            adaptive_multiplier = float(adaptive_bytes)
                    except Exception:
                        pass
                    
                    current_delay = rate_limit_delay * adaptive_multiplier
                    redis_key = "openai_rate_limiter:last_request"
                    current_time = time.time()
                    
                    last_time_bytes = redis_client.get(redis_key)
                    if last_time_bytes:
                        last_time = float(last_time_bytes)
                        time_since_last = current_time - last_time
                        if time_since_last < current_delay:
                            wait_time = current_delay - time_since_last
                            await asyncio.sleep(wait_time)
                            current_time = time.time()
                    
                    expiration = max(1, int(current_delay * 3))
                    redis_client.set(
                        redis_key,
                        str(current_time).encode(),
                        ex=expiration
                    )
                else:
                    async with rate_limiter_lock:
                        current_time = time.time()
                        current_delay = rate_limit_delay * adaptive_delay_multiplier[0]
                        time_since_last = current_time - last_request_time[0]
                        if time_since_last < current_delay:
                            wait_time = current_delay - time_since_last
                            await asyncio.sleep(wait_time)
                        last_request_time[0] = time.time()
                
                # Now acquire semaphore and make the actual API calls
                async with semaphore:
                    # Generate checklists
                    if checklist_type in ['eligibility', 'both', 'all'] and not skip_eligibility:
                        try:
                            parsed, raw_meta, latency_ms = await client.eligibility_checklist_async(grant_ctx)
                            checklist_data = {
                                "checklist_items": sanitize_checklist_items(parsed.get("checklist_items") or []),
                                "meta": {
                                    "model": raw_meta.get("model"),
                                    "input_tokens": (raw_meta.get("usage") or {}).get("input_tokens"),
                                    "output_tokens": (raw_meta.get("usage") or {}).get("output_tokens"),
                                    "latency_ms": latency_ms,
                                },
                            }
                            # Save to database (sync operation)
                            # Refresh grant from database to avoid stale object issues
                            def save_eligibility():
                                from grants.models import Grant
                                grant_obj = Grant.objects.filter(id=grant.id).first()
                                if grant_obj:
                                    grant_obj.eligibility_checklist = checklist_data
                                    grant_obj.save(update_fields=['eligibility_checklist'])
                                else:
                                    logger.warning(f"Grant {grant.id} not found when trying to save eligibility checklist")
                            await sync_to_async(save_eligibility)()
                            eligibility_generated = True
                            logger.debug(f"Generated eligibility checklist for grant {grant.id}")
                        except Exception as e:
                            error_msg = f"Grant {grant.id} (eligibility): {str(e)}"
                            errors.append(error_msg)
                            logger.error(error_msg, exc_info=True)
                    
                    if checklist_type in ['competitiveness', 'both', 'all'] and not skip_competitiveness:
                        try:
                            parsed, raw_meta, latency_ms = await client.competitiveness_checklist_async(grant_ctx)
                            checklist_data = {
                                "checklist_items": sanitize_checklist_items(parsed.get("checklist_items") or []),
                                "meta": {
                                    "model": raw_meta.get("model"),
                                    "input_tokens": (raw_meta.get("usage") or {}).get("input_tokens"),
                                    "output_tokens": (raw_meta.get("usage") or {}).get("output_tokens"),
                                    "latency_ms": latency_ms,
                                },
                            }
                            def save_competitiveness():
                                from grants.models import Grant
                                grant_obj = Grant.objects.filter(id=grant.id).first()
                                if grant_obj:
                                    grant_obj.competitiveness_checklist = checklist_data
                                    grant_obj.save(update_fields=['competitiveness_checklist'])
                                else:
                                    logger.warning(f"Grant {grant.id} not found when trying to save competitiveness checklist")
                            await sync_to_async(save_competitiveness)()
                            competitiveness_generated = True
                            logger.debug(f"Generated competitiveness checklist for grant {grant.id}")
                        except Exception as e:
                            error_msg = f"Grant {grant.id} (competitiveness): {str(e)}"
                            errors.append(error_msg)
                            logger.error(error_msg, exc_info=True)
                    
                    if checklist_type in ['exclusions', 'all'] and not skip_exclusions:
                        try:
                            parsed, raw_meta, latency_ms = await client.exclusions_checklist_async(grant_ctx)
                            checklist_data = {
                                "checklist_items": sanitize_checklist_items(parsed.get("checklist_items") or []),
                                "meta": {
                                    "model": raw_meta.get("model"),
                                    "input_tokens": (raw_meta.get("usage") or {}).get("input_tokens"),
                                    "output_tokens": (raw_meta.get("usage") or {}).get("output_tokens"),
                                    "latency_ms": latency_ms,
                                },
                            }
                            def save_exclusions():
                                from grants.models import Grant
                                grant_obj = Grant.objects.filter(id=grant.id).first()
                                if grant_obj:
                                    grant_obj.exclusions_checklist = checklist_data
                                    grant_obj.save(update_fields=['exclusions_checklist'])
                                else:
                                    logger.warning(f"Grant {grant.id} not found when trying to save exclusions checklist")
                            await sync_to_async(save_exclusions)()
                            exclusions_generated = True
                            logger.debug(f"Generated exclusions checklist for grant {grant.id}")
                        except Exception as e:
                            error_msg = f"Grant {grant.id} (exclusions): {str(e)}"
                            errors.append(error_msg)
                            logger.error(error_msg, exc_info=True)
                    
                    if checklist_type in ['trl', 'all'] and not skip_trl:
                        try:
                            parsed, raw_meta, latency_ms = await client.trl_requirements_async(grant_ctx)
                            trl_levels = parsed.get("trl_levels", [])
                            is_technology_focused = parsed.get("is_technology_focused", False)
                            
                            # Save if we found TRL levels OR if the grant is technology-focused
                            if (trl_levels and len(trl_levels) > 0) or is_technology_focused:
                                trl_data = {
                                    "trl_levels": trl_levels if trl_levels else [],
                                    "trl_range": parsed.get("trl_range"),
                                    "is_technology_focused": is_technology_focused,
                                    "notes": parsed.get("notes"),
                                    "meta": {
                                        "model": raw_meta.get("model"),
                                        "input_tokens": (raw_meta.get("usage") or {}).get("input_tokens"),
                                        "output_tokens": (raw_meta.get("usage") or {}).get("output_tokens"),
                                        "latency_ms": latency_ms,
                                    },
                                }
                                def save_trl():
                                    from grants.models import Grant
                                    grant_obj = Grant.objects.filter(id=grant.id).first()
                                    if grant_obj:
                                        grant_obj.trl_requirements = trl_data
                                        grant_obj.save(update_fields=['trl_requirements'])
                                    else:
                                        logger.warning(f"Grant {grant.id} not found when trying to save TRL requirements")
                                await sync_to_async(save_trl)()
                                trl_generated = True
                                if trl_levels:
                                    logger.debug(f"Generated TRL requirements for grant {grant.id}: {trl_levels}")
                                else:
                                    logger.debug(f"Grant {grant.id} marked as technology-focused (no specific TRL levels found)")
                            else:
                                # No TRL levels found and not technology-focused - don't save empty data
                                logger.debug(f"No TRL levels found and not technology-focused for grant {grant.id}")
                                trl_generated = False
                        except Exception as e:
                            error_msg = f"Grant {grant.id} (TRL): {str(e)}"
                            errors.append(error_msg)
                            logger.error(error_msg, exc_info=True)
                    
                    # Success - gradually decrease adaptive multiplier if it was increased
                    if redis_client:
                        try:
                            adaptive_key = "openai_rate_limiter:adaptive_multiplier"
                            mult_bytes = redis_client.get(adaptive_key)
                            if mult_bytes:
                                current_mult = float(mult_bytes)
                                if current_mult > 1.0:
                                    new_mult = max(1.0, current_mult * 0.95)
                                    redis_client.set(adaptive_key, str(new_mult).encode(), ex=300)
                        except Exception:
                            pass
                    else:
                        if adaptive_delay_multiplier[0] > 1.0:
                            adaptive_delay_multiplier[0] = max(1.0, adaptive_delay_multiplier[0] * 0.95)
                    
                    # Check if at least one checklist was generated
                    if (checklist_type == 'eligibility' and eligibility_generated) or \
                       (checklist_type == 'competitiveness' and competitiveness_generated) or \
                       (checklist_type == 'exclusions' and exclusions_generated) or \
                       (checklist_type == 'trl' and trl_generated) or \
                       (checklist_type == 'both' and (eligibility_generated or competitiveness_generated)) or \
                       (checklist_type == 'all' and (eligibility_generated or competitiveness_generated or exclusions_generated or trl_generated)):
                        success_count += 1
                    
                    return {
                        'skipped': False,
                        'grant_id': grant.id,
                        'eligibility_generated': eligibility_generated,
                        'competitiveness_generated': competitiveness_generated,
                        'exclusions_generated': exclusions_generated,
                        'trl_generated': trl_generated
                    }
                    
            except RateLimitError as e:
                # Increase adaptive delay multiplier on 429 error
                if redis_client:
                    try:
                        adaptive_key = "openai_rate_limiter:adaptive_multiplier"
                        current_mult = 1.0
                        mult_bytes = redis_client.get(adaptive_key)
                        if mult_bytes:
                            current_mult = float(mult_bytes)
                        new_mult = min(5.0, current_mult * 1.5)
                        redis_client.set(adaptive_key, str(new_mult).encode(), ex=300)
                        logger.warning(f"Rate limit hit - increasing adaptive delay multiplier to {new_mult:.2f}x")
                    except Exception:
                        pass
                else:
                    adaptive_delay_multiplier[0] = min(5.0, adaptive_delay_multiplier[0] * 1.5)
                    logger.warning(f"Rate limit hit - increasing adaptive delay multiplier to {adaptive_delay_multiplier[0]:.2f}x")
                
                if attempt < max_retries - 1:
                    wait_time = (2 ** attempt) * 5
                    if hasattr(e, 'response') and e.response is not None:
                        retry_after = e.response.headers.get('retry-after')
                        if retry_after:
                            try:
                                wait_time = float(retry_after) + 1
                            except (ValueError, TypeError):
                                pass
                    logger.warning(f"Grant {grant.id}, attempt {attempt + 1}: Rate limit hit, waiting {wait_time:.1f}s...")
                    await asyncio.sleep(wait_time)
                else:
                    error_count += 1
                    error_msg = f"Grant {grant.id}: Rate limit exceeded after {max_retries} retries"
                    errors.append(error_msg)
                    logger.error(error_msg)
                    return {'skipped': False, 'grant_id': grant.id, 'error': error_msg}
                    
            except (APIError, Exception) as e:
                if attempt < max_retries - 1:
                    logger.warning(f"Grant {grant.id}, attempt {attempt + 1}: Error {e}, retrying...")
                    await asyncio.sleep(2)
                else:
                    error_count += 1
                    error_msg = f"Grant {grant.id}: Error after {max_retries} retries: {str(e)}"
                    errors.append(error_msg)
                    logger.error(error_msg, exc_info=True)
                    return {'skipped': False, 'grant_id': grant.id, 'error': error_msg}
        
        return {'skipped': False, 'grant_id': grant.id}
    
    # Create tasks for all grants
    task_list = [
        asyncio.create_task(process_grant_with_retry(grant, idx))
        for idx, grant in enumerate(grants)
    ]
    
    # Process all tasks, updating progress as each completes
    completed = 0
    for done_coro in asyncio.as_completed(task_list):
        try:
            result = await done_coro
            completed += 1
            processed_count += 1
            
            # Update progress using backend directly (works from async context)
            percentage = (completed / total_grants) * 100 if total_grants > 0 else 0
            if task_id:
                try:
                    # Use backend directly to update task state (works from async context)
                    from celery import current_app
                    backend = current_app.backend
                    backend.store_result(
                        task_id,
                        {
                            'current': completed,
                            'total': total_grants,
                            'percentage': round(percentage, 1),
                            'processed': processed_count,
                            'success': success_count,
                            'skipped': skipped_count,
                            'errors': error_count
                        },
                        'PROGRESS'
                    )
                except Exception as e:
                    # Log but don't fail the job if progress update fails
                    logger.warning(f"Failed to update progress for task {task_id}: {e}")
            
            logger.info(f"Processed {completed}/{total_grants} grants")
        except Exception as e:
            logger.error(f"Unexpected error awaiting task: {e}", exc_info=True)
            completed += 1
            processed_count += 1
            error_count += 1
    
    result = {
        'status': 'completed',
        'total': total_grants,
        'processed': processed_count,
        'success': success_count,
        'skipped': skipped_count,
        'errors': error_count,
        'error_messages': errors[:10]
    }
    
    logger.info(f"Checklist generation completed: {success_count} successful, {skipped_count} skipped, {error_count} errors")
    return result


if CELERY_TASKS_AVAILABLE:
    @shared_task(bind=True)
    def generate_checklists_for_all_grants(self, checklist_type='both'):
        """
        Generate eligibility, competitiveness, and/or exclusions checklists for all grants.
        Uses async parallel processing with rate limiting optimized for tier 2 API limits.
        
        Args:
            checklist_type: 'eligibility', 'competitiveness', 'exclusions', 'both', or 'all'
            - 'both' generates eligibility and competitiveness
            - 'all' generates all three (eligibility, competitiveness, and exclusions)
        
        Returns:
            dict with status, total, processed, success, errors
        """
        from grants.models import Grant
        from admin_panel.ai_client import AiAssistantClient, build_grant_context, AiAssistantError
        
        logger.info(f"generate_checklists_for_all_grants task started for type: {checklist_type}")
        
        # Get all grants
        grants = list(Grant.objects.all())
        total_grants = len(grants)
        logger.info(f"Found {total_grants} grants to process")
        
        try:
            client = AiAssistantClient()
        except AiAssistantError as e:
            error_msg = f"Failed to initialize AI client: {str(e)}"
            logger.error(error_msg)
            return {
                'status': 'error',
                'error': error_msg,
                'total': total_grants,
                'processed': 0,
                'success': 0,
                'skipped': 0,
                'errors': 1
            }
        
        # Capture task_id before entering async context
        task_id = self.request.id
        
        # Use async processing
        return asyncio.run(_generate_checklists_async(
            task_id, grants, checklist_type, client
        ))
else:
    def refresh_companies_house_data():
        raise Exception("Celery is not available")
    
    def generate_checklists_for_all_grants():
        raise Exception("Celery is not available")

