"""
Celery tasks for grant matching.
"""
import logging
from django.utils import timezone
from .models import FundingSearch, GrantMatchResult
from .services import ChatGPTMatchingService, GrantMatchingError
from grants.models import Grant

logger = logging.getLogger(__name__)

# Import Celery safely
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


if CELERY_TASKS_AVAILABLE:
    @shared_task(bind=True)
    def match_grants_with_chatgpt(self, funding_search_id):
        """
        Match all grants using ChatGPT API with batch processing.
        
        Args:
            funding_search_id: ID of the FundingSearch to match grants for
        
        Returns:
            dict with status, matches_created, grants_processed
        """
        funding_search = FundingSearch.objects.get(id=funding_search_id)
        funding_search.matching_status = 'running'
        funding_search.save()
        
        try:
            project_text = funding_search.project_description
            if not project_text:
                raise ValueError("No project description available")
            
            # Get ALL grants (170 grants)
            grants = Grant.objects.all().order_by('-created_at')
            grants_list = list(grants.values(
                'id', 'title', 'source', 'summary', 'description',
                'funding_amount', 'deadline', 'status', 'slug'
            ))
            
            # Initialize matcher
            try:
                matcher = ChatGPTMatchingService()
            except GrantMatchingError as e:
                raise Exception(f"Failed to initialize matching service: {str(e)}")
            
            # Progress tracking function
            def progress_callback(current, total):
                progress = (current / total) * 100
                self.update_state(
                    state='PROGRESS',
                    meta={'current': current, 'total': total, 'progress': f'{progress:.1f}%'}
                )
            
            # Clear old matches
            GrantMatchResult.objects.filter(funding_search=funding_search).delete()
            
            # Match all grants
            print(f"Starting matching for {len(grants_list)} grants...")
            match_results = matcher.match_all_grants(
                project_text,
                grants_list,
                progress_callback=progress_callback
            )
            
            # Save results to database
            matches_created = 0
            matches_updated = 0
            for result in match_results:
                grant_idx = result['grant_index']
                if grant_idx < len(grants_list):
                    grant_data = grants_list[grant_idx]
                    grant = Grant.objects.get(id=grant_data['id'])
                    
                    # Only save matches above threshold
                    if result['score'] > 0.2:  # Lower threshold since we're processing all grants
                        # Use update_or_create to handle duplicates gracefully
                        match_obj, created = GrantMatchResult.objects.update_or_create(
                            funding_search=funding_search,
                            grant=grant,
                            defaults={
                                'match_score': result['score'],
                                'match_reasons': {
                                    'explanation': result.get('explanation', ''),
                                    'alignment_points': result.get('alignment_points', []),
                                    'concerns': result.get('concerns', []),
                                    'matched_via': 'chatgpt',
                                    'batch_processed': True,
                                }
                            }
                        )
                        if created:
                            matches_created += 1
                        else:
                            matches_updated += 1
            
            # Update funding search
            funding_search.matching_status = 'completed'
            funding_search.last_matched_at = timezone.now()
            funding_search.save()
            
            return {
                'status': 'success',
                'matches_created': matches_created,
                'matches_updated': matches_updated,
                'grants_processed': len(grants_list),
                'total_results': len(match_results),
            }
        
        except Exception as e:
            funding_search.matching_status = 'error'
            funding_search.save()
            raise Exception(f"Matching failed: {str(e)}")
else:
    # Dummy function if Celery is not available
    def match_grants_with_chatgpt(funding_search_id):
        raise Exception("Celery is not available")

